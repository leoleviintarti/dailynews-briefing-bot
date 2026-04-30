"""
Real-time alert checker - runs every 15 minutes via GitHub Actions.

Goal: catch BIG events between scheduled briefings, ping Telegram immediately.

Flow:
  1. Pull last 45 minutes from a tight set of high-signal feeds (USGS, GDACS,
     Bloomberg, AP, Reuters, BBC, Indonesia disaster/economy watchers).
  2. Hash each headline -> check against state file (alerts_state.json) so we
     never alert the same story twice. State file is committed back by Actions.
  3. Send compact list to Gemini 2.5 Flash-Lite with strict severity rubric.
  4. Only items with severity >= 8 trigger Telegram alert.
  5. Persist seen hashes (rolling 7-day window).

Run: python alert.py
Env: GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from briefing import (
    WIB,
    clean_text,
    env,
    fetch_feed,
    md_escape,
    parse_date,
    send_telegram,
)
from sources import ALERT_SOURCES

LOG = logging.getLogger("alert")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

LOOKBACK_MIN = 45  # 15-min cron + 30-min overlap buffer
STATE_FILE = Path("alerts_state.json")
STATE_RETENTION_DAYS = 7
SEVERITY_THRESHOLD = 8

GEMINI_MODEL_LITE = "gemini-2.5-flash-lite"
GEMINI_URL_LITE = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL_LITE}:generateContent"
)

ALERT_PROMPT = """Kamu adalah analis breaking news. Tugasmu: scan list headline
ini, dan tentukan apakah ADA yang termasuk BIG EVENT yang layak alert instan.

Kriteria BIG EVENT (severity 8-10):
- Konflik militer mayor: serangan rudal lintas negara, deklarasi perang, eskalasi NATO/Asia, kudeta
- Crash pasar: indeks major (S&P/Nasdaq/IHSG/Nikkei) turun >3% intraday, USD/IDR lompat ekstrim, stablecoin de-peg, bank major collapse
- Bencana mayor GLOBAL: gempa M>=7, tsunami warning, erupsi vulkanik mayor, badai kategori 4+
- Bencana di Indonesia (level apapun): gempa M>=5 di Indonesia, banjir besar, kebakaran hutan luas, erupsi
- AI breakthrough mayor: rilis model frontier baru (GPT-5+/Claude 5+/Gemini 3+), AGI claim kredibel, hardware game-changer
- Outbreak penyakit: WHO PHEIC declaration, virus baru spreading cross-border, kasus ekstrim Indonesia
- Kematian/penurunan pemimpin negara major

Skor severity:
- 1-3: noise, skip
- 4-7: penting tapi tunggu briefing rutin
- 8-10: ALERT SEKARANG

Output WAJIB JSON valid, tanpa markdown fences:
{
  "alerts": [
    {
      "hash_id": "id dari input",
      "headline_original": "headline asli persis",
      "category": "Geopolitik|Ekonomi|Lingkungan|Kesehatan|Teknologi & AI",
      "severity": 1-10,
      "what_happened_id": "1 kalimat fakta padat dalam Bahasa Indonesia",
      "why_now_id": "1 kalimat kenapa ini layak interrupt: dampak/urgency"
    }
  ]
}

Hanya keluarkan items dengan severity >= 8. Kalau gak ada yang qualify,
kembalikan {"alerts": []}.

Jangan halusinasi. Jangan reproduksi >15 kata berturut-turut dari summary sumber.
"""


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            LOG.warning("State file corrupt; resetting.")
    return {"seen": {}}


def save_state(state: dict) -> None:
    # Prune entries older than retention window
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STATE_RETENTION_DAYS)).isoformat()
    state["seen"] = {h: ts for h, ts in state["seen"].items() if ts >= cutoff}
    STATE_FILE.write_text(json.dumps(state, indent=2))


def hash_headline(title: str) -> str:
    norm = "".join(c for c in title.lower() if c.isalnum())[:80]
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def fetch_alert_candidates() -> list[dict]:
    """Pull last LOOKBACK_MIN minutes from alert sources."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MIN)
    candidates: list[dict] = []
    for src in ALERT_SOURCES:
        items = fetch_feed(src)
        for item in items:
            try:
                pub = datetime.fromisoformat(item["published"])
            except Exception:
                continue
            if pub >= cutoff:
                candidates.append(item)
    return candidates


def call_gemini_lite(api_key: str, items: list[dict]) -> dict:
    payload = [
        {
            "hash_id": it["hash_id"],
            "title": it["title"],
            "summary": it["summary"],
            "source": it["source"],
        }
        for it in items
    ]
    user_text = (
        f"Waktu: {datetime.now(WIB).strftime('%A, %d %B %Y %H:%M WIB')}\n"
        f"Total {len(payload)} headline dari {LOOKBACK_MIN} menit terakhir.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )
    body = {
        "system_instruction": {"parts": [{"text": ALERT_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                GEMINI_URL_LITE,
                headers={"x-goog-api-key": api_key},  # header auth, never URL
                json=body,
                timeout=60,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = 8 * (attempt + 1)
                LOG.warning(
                    "Gemini-Lite transient %s; backoff %ds",
                    resp.status_code, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except requests.RequestException as e:
            # Never log the exception's str() form -- it may contain the URL with key
            LOG.warning("Gemini-Lite attempt %d failed: %s", attempt + 1, type(e).__name__)
            if attempt == 2:
                LOG.warning("Giving up after 3 attempts; will try next cron slot.")
                return {"alerts": []}
            time.sleep(8 * (attempt + 1))
    return {"alerts": []}


CATEGORY_TAG = {
    "Geopolitik": "[GEO]",
    "Ekonomi": "[EKON]",
    "Lingkungan": "[LING]",
    "Kesehatan": "[KES]",
    "Teknologi & AI": "[AI]",
}


def format_alert(alert: dict) -> str:
    now = datetime.now(WIB).strftime("%H:%M WIB")
    cat = alert.get("category", "")
    tag = CATEGORY_TAG.get(cat, "[*]")
    sev = alert.get("severity", 0)
    parts = [
        f"*[ALERT \\| sev {sev}/10]* {md_escape(tag)} {md_escape(cat)}",
        f"_{md_escape(alert.get('headline_original', ''))}_",
        "",
        md_escape(alert.get("what_happened_id", "")),
        "",
        f">*Why now:* {md_escape(alert.get('why_now_id', ''))}",
        "",
        md_escape(f"-- pinged {now} --"),
    ]
    return "\n".join(parts)


def main() -> None:
    gemini_key = env("GEMINI_API_KEY")
    bot_token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")

    LOG.info("=== Alert run @ %s ===", datetime.now(WIB).isoformat())
    state = load_state()

    candidates = fetch_alert_candidates()
    LOG.info("Fetched %d candidates from alert feeds", len(candidates))

    # Filter out already-seen
    fresh = []
    for c in candidates:
        h = hash_headline(c["title"])
        if h in state["seen"]:
            continue
        c["hash_id"] = h
        fresh.append(c)

    LOG.info("Fresh (unseen) items: %d", len(fresh))
    if not fresh:
        LOG.info("Nothing new; exit clean.")
        save_state(state)
        return

    # Mark all fresh as seen BEFORE LLM call (so a crash mid-flight won't re-alert)
    now_iso = datetime.now(timezone.utc).isoformat()
    for c in fresh:
        state["seen"][c["hash_id"]] = now_iso

    try:
        result = call_gemini_lite(gemini_key, fresh)
    except Exception as e:
        LOG.exception("Gemini-Lite call failed: %s", e)
        save_state(state)
        return

    alerts = [a for a in result.get("alerts", []) if a.get("severity", 0) >= SEVERITY_THRESHOLD]
    LOG.info("Qualifying alerts (sev >= %d): %d", SEVERITY_THRESHOLD, len(alerts))

    for alert in alerts[:5]:  # safety cap: max 5 alerts per run
        msg = format_alert(alert)
        send_telegram(bot_token, chat_id, msg)
        time.sleep(1)

    save_state(state)
    LOG.info("Alert run done.")


if __name__ == "__main__":
    main()
