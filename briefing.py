"""
Daily Briefing - 6-hourly news briefing pipeline.

Flow:
  1. Pull last ~7 hours of headlines from all curated RSS feeds.
  2. Deduplicate near-identical headlines.
  3. Send compact list to Gemini 2.5 Flash with a tight prompt.
  4. Gemini returns 5-8 SIGNAL items in structured JSON, mixed-language
     (headline original + analysis Bahasa Indonesia + 'why it matters').
  5. Format as Telegram MarkdownV2 and send.

Run via: python briefing.py
Env required: GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import requests

from sources import ALL_SOURCES

LOG = logging.getLogger("briefing")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---- Config -----------------------------------------------------------------

WIB = timezone(timedelta(hours=7))
LOOKBACK_HOURS = 7  # 6h slot + 1h overlap for safety
MAX_HEADLINES_TO_LLM = 120  # cap context size
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# ---- Helpers ----------------------------------------------------------------


def env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        LOG.error("Missing env var: %s", key)
        sys.exit(1)
    return val


def parse_date(entry: dict) -> datetime | None:
    """Extract a timezone-aware UTC datetime from a feed entry."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        struct = entry.get(field)
        if struct:
            try:
                return datetime(*struct[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)  # strip HTML
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_feed(source: dict) -> list[dict]:
    """Fetch one RSS feed; return list of normalized articles."""
    LOG.info("Fetching: %s", source["name"])
    try:
        resp = requests.get(
            source["url"],
            headers={"User-Agent": "DailyBriefingBot/1.0 (+github.com/your-repo)"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        LOG.warning("  Failed: %s (%s)", source["name"], e)
        return []

    parsed = feedparser.parse(resp.content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    items: list[dict] = []
    for entry in parsed.entries[:60]:  # cap per-feed
        published = parse_date(entry)
        if published is None:
            # If no date present, accept (Google News sometimes lacks date in items)
            published = datetime.now(timezone.utc)
        if published < cutoff:
            continue

        title = clean_text(entry.get("title", ""))
        summary = clean_text(entry.get("summary") or entry.get("description", ""))
        if not title:
            continue

        items.append(
            {
                "title": title,
                "summary": summary[:280],
                "link": entry.get("link", ""),
                "source": source["name"],
                "published": published.isoformat(),
                "weight": source.get("weight", 1.0),
            }
        )
    LOG.info("  -> %d items", len(items))
    return items


def dedupe(articles: list[dict]) -> list[dict]:
    """Drop near-duplicate titles (e.g. same Reuters story repeated by AP)."""
    seen: set[str] = set()
    out = []
    for a in articles:
        key = re.sub(r"[^a-z0-9]+", "", a["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


# ---- Gemini -----------------------------------------------------------------

PROMPT_SYSTEM = """Kamu adalah analis intelijen geopolitik & ekonomi senior buat brief seseorang.
Audience-mu adalah orang Indonesia yang cerdas dan ingin SINYAL, bukan noise.

Tugasmu: dari list headline mentah berikut, pilih HANYA 5-8 item paling penting yang
benar-benar membantu pembaca berpikir lebih baik dan ambil keputusan lebih baik.

Filter ketat:
- Tolak: gosip selebriti, olahraga rutin, opini, kontroversi politik domestik kecil
- Loloskan HANYA: hal yang benar-benar bisa mengubah lanskap geopolitik/ekonomi/lingkungan/kesehatan/teknologi
- Prioritas tinggi untuk: konflik militer, krisis ekonomi, bencana mayor, terobosan AI/tech, outbreak penyakit
- Selalu sertakan minimal 1 item Indonesia kalau ada yang relevan & penting

Output WAJIB JSON valid dengan struktur ini saja, tanpa markdown fences:
{
  "summary_id": "1-2 kalimat ringkasan situasi global saat ini dalam Bahasa Indonesia",
  "items": [
    {
      "category": "Geopolitik|Ekonomi|Lingkungan|Kesehatan|Teknologi & AI",
      "headline_original": "judul asli persis seperti di sumber (jangan diubah)",
      "source": "nama sumber",
      "what_happened_id": "1-2 kalimat fakta dalam Bahasa Indonesia, padat",
      "why_it_matters_id": "1-2 kalimat analisis tajam dalam Bahasa Indonesia: kenapa ini penting, dampak ke depan, atau apa yang harus diperhatikan",
      "severity": 1-10
    }
  ]
}

Aturan ekstra:
- Jangan reproduksi >15 kata berturut-turut dari isi summary sumber (hak cipta).
- Tulis 'why_it_matters_id' dengan tajam: jangan generic 'ini penting karena...', tapi spesifik 'ini menggeser X karena Y'.
- Jangan halusinasi fakta yang tidak ada di headline/summary.
"""


def call_gemini(api_key: str, articles: list[dict]) -> dict:
    """Send articles to Gemini, expect structured JSON back."""
    payload_articles = [
        {
            "title": a["title"],
            "summary": a["summary"],
            "source": a["source"],
        }
        for a in articles[:MAX_HEADLINES_TO_LLM]
    ]

    user_text = (
        f"Tanggal: {datetime.now(WIB).strftime('%A, %d %B %Y %H:%M WIB')}\n\n"
        f"Total {len(payload_articles)} headline mentah dari {LOOKBACK_HOURS} jam terakhir.\n\n"
        + json.dumps(payload_articles, ensure_ascii=False, indent=1)
    )

    body = {
        "system_instruction": {"parts": [{"text": PROMPT_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }

    LOG.info("Calling Gemini with %d articles...", len(payload_articles))
    for attempt in range(3):
        try:
            resp = requests.post(
                GEMINI_URL,
                params={"key": api_key},
                json=body,
                timeout=60,
            )
            if resp.status_code == 429:
                LOG.warning("Rate-limited; backoff %ds", 5 * (attempt + 1))
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            LOG.warning("Gemini call failed (attempt %d): %s", attempt + 1, e)
            if attempt == 2:
                raise
            time.sleep(3)

    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


# ---- Telegram ---------------------------------------------------------------

CATEGORY_EMOJI = {
    "Geopolitik": "[GEO]",
    "Ekonomi": "[EKON]",
    "Lingkungan": "[LING]",
    "Kesehatan": "[KES]",
    "Teknologi & AI": "[AI]",
}


def md_escape(text: str) -> str:
    """Telegram MarkdownV2 reserved chars.

    Order matters: escape backslash FIRST, then the other reserved chars,
    otherwise the backslashes added by escaping `[`, `*`, etc. will themselves
    get double-escaped.
    """
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    for ch in "_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def format_brief(brief: dict) -> str:
    now = datetime.now(WIB).strftime("%a %d %b %Y %H:%M WIB")
    parts = [
        f"*DAILY BRIEFING* {md_escape('|')} {md_escape(now)}",
        "",
        md_escape(brief.get("summary_id", "")),
        "",
    ]
    for i, item in enumerate(brief.get("items", []), 1):
        cat = item.get("category", "")
        tag = CATEGORY_EMOJI.get(cat, "[*]")
        sev = item.get("severity", 0)
        sev_marker = " [HIGH]" if sev >= 8 else ""
        parts.append(
            f"*{i}\\. {md_escape(tag)} {md_escape(cat)}*{md_escape(sev_marker)}"
        )
        parts.append(f"_{md_escape(item.get('headline_original', ''))}_")
        parts.append(md_escape(item.get("what_happened_id", "")))
        parts.append(f">{md_escape(item.get('why_it_matters_id', ''))}")
        parts.append(f"`{md_escape(item.get('source', ''))}`")
        parts.append("")
    parts.append(md_escape(f"-- end of brief -- next in 6h --"))
    return "\n".join(parts)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Send message; auto-split if too long (4096 char Telegram limit)."""
    chunks = [text[i : i + 3900] for i in range(0, len(text), 3900)]
    for chunk in chunks:
        resp = requests.post(
            TELEGRAM_API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if not resp.ok:
            LOG.error("Telegram error: %s %s", resp.status_code, resp.text)
            # Fallback: try plain text
            requests.post(
                TELEGRAM_API.format(token=token),
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=20,
            )


# ---- Main -------------------------------------------------------------------


def main() -> None:
    gemini_key = env("GEMINI_API_KEY")
    bot_token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")

    LOG.info("=== Daily Briefing run @ %s ===", datetime.now(WIB).isoformat())

    all_items: list[dict] = []
    for src in ALL_SOURCES:
        all_items.extend(fetch_feed(src))

    LOG.info("Total raw items: %d", len(all_items))
    items = dedupe(all_items)
    LOG.info("After dedupe: %d", len(items))

    if not items:
        LOG.warning("No items in window; sending heartbeat.")
        send_telegram(
            bot_token,
            chat_id,
            md_escape(
                f"[heartbeat] briefing run @ {datetime.now(WIB).strftime('%H:%M WIB')} -- "
                f"no items in last {LOOKBACK_HOURS}h window."
            ),
        )
        return

    # Sort by weighted recency (highest weight first, newest first)
    items.sort(key=lambda x: (x["weight"], x["published"]), reverse=True)

    try:
        brief = call_gemini(gemini_key, items)
    except Exception as e:
        LOG.exception("Gemini call failed: %s", e)
        send_telegram(
            bot_token,
            chat_id,
            md_escape(f"[error] briefing failed: {e}. Will retry next slot."),
        )
        sys.exit(2)

    msg = format_brief(brief)
    send_telegram(bot_token, chat_id, msg)
    LOG.info("Briefing sent: %d items", len(brief.get("items", [])))


if __name__ == "__main__":
    main()
