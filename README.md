# Daily Briefing Bot

Telegram bot that pings you 4x/day with a curated, AI-filtered news briefing
(geopolitics, economy, environment, health, tech & AI), and sends instant
alerts when major events break. Runs 100% free on GitHub Actions.

**Cost: $0/month.** Hosting via GitHub Actions (unlimited minutes on public
repos), AI via Gemini free tier (250 req/day Flash + 1000 req/day Flash-Lite),
news via public RSS feeds.

---

## What you get

- **Briefing every 6 hours** at 06:00, 12:00, 18:00, 00:00 WIB. 5-8 curated
  items with `headline_original` (English/ID as published) plus
  `what_happened` and `why_it_matters` analysis in Bahasa Indonesia.
- **Alert checker every 15 min** that pings instantly when any of these hit:
  major military conflict, market crash >3%, gempa M>=7 global / M>=5 Indonesia,
  WHO outbreak declaration, frontier AI model release.
- Sources: BBC, FT, Bloomberg, Al Jazeera, Reuters, AP, USGS, GDACS, The Verge,
  Ars Technica + Antara, Tempo, Kontan, Kompas + Indonesia disaster/economy
  watch feeds. All filtered by Gemini so you only see signal.

---

## Setup (one-time, ~15 min)

### 1. Get your Gemini API key

Go to https://aistudio.google.com/apikey -> sign in with Google -> "Create API
key". Copy it. Free tier is automatic.

### 2. Get your Telegram bot token

You said you already have a bot. If you misplaced the token: open Telegram ->
chat with `@BotFather` -> `/mybots` -> pick your bot -> `API Token`.

### 3. Get your Telegram chat ID

Open Telegram, send any message to your bot first (so the bot can "see" you).
Then in a browser:

```
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```

Look for `"chat":{"id":<NUMBER>` -- that number is your `TELEGRAM_CHAT_ID`.

### 4. Create the GitHub repo

1. Create a new **public** repo on GitHub (e.g. `daily-briefing`). Public is
   important: GitHub Actions free minutes are unlimited only on public repos.
2. Clone it locally, drop in all files from this folder:
   ```
   .github/workflows/briefing.yml
   .github/workflows/alert.yml
   sources.py
   briefing.py
   alert.py
   requirements.txt
   alerts_state.json
   .gitignore
   README.md
   ```
3. Push to GitHub.

### 5. Add Secrets to the repo

In your GitHub repo: **Settings -> Secrets and variables -> Actions -> New
repository secret**. Add three secrets:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from step 1 |
| `TELEGRAM_BOT_TOKEN` | from step 2 |
| `TELEGRAM_CHAT_ID` | from step 3 |

### 6. Test it

Go to **Actions** tab in your repo -> pick `Daily Briefing` -> `Run workflow`.
Within ~2 min you should get a Telegram message. If not, click the run -> see
logs to debug.

Same for `Real-time Alert Checker` -> `Run workflow`. (Likely no alert if
nothing major broke in the last 45 min, which is fine -- check logs to confirm
it ran clean.)

---

## How it works (architecture)

```
              every 6h                          every 15 min
            (cron via GH Actions)            (cron via GH Actions)
                  |                                  |
                  v                                  v
            briefing.py                         alert.py
                  |                                  |
       fetch ~17 RSS feeds                fetch ~9 alert feeds
                  |                                  |
            dedupe + filter                  dedupe vs state
                  |                                  |
       Gemini 2.5 Flash                  Gemini 2.5 Flash-Lite
       (250 req/day quota)              (1000 req/day quota)
                  |                                  |
       JSON: 5-8 items                   JSON: severity-scored
                  |                                  |
       Telegram MarkdownV2          if severity>=8 -> Telegram
                  |                                  |
                  v                                  v
              YOU                            commit state file
```

Daily quota usage: 4 briefing calls + 96 alert calls = ~100 Gemini calls/day.
Well under the 1250 combined daily limit.

---

## Tuning

Open `sources.py` to add/remove feeds. Open `briefing.py` `PROMPT_SYSTEM` to
change tone or filter strictness. Open `alert.py` `SEVERITY_THRESHOLD` (default
8) -- lower it to 7 if you want more alerts, raise to 9 if too noisy.

To change schedule: edit `.github/workflows/briefing.yml` cron line. Cron is
in UTC, so subtract 7 hours from your WIB target.

---

## Troubleshooting

**No briefing arrives:** check Actions tab logs. Most common: one of the three
secrets is wrong/missing. Re-do step 5.

**"Telegram error 400":** message had a special character that broke
MarkdownV2 escaping. The script has a plaintext fallback so you should still
get the message, just unformatted. Open an issue if it keeps happening.

**Gemini 429 rate limit:** unlikely under this design, but if Google tightens
the free tier further, edit `briefing.py` to use `gemini-2.5-flash-lite`
instead and lower `MAX_HEADLINES_TO_LLM` to 80.

**Alert checker never alerts:** that's actually normal most of the time --
truly major events are rare. To verify it's working, manually run with
`workflow_dispatch` and check logs for "Fetched N candidates".

**State file conflicts (rare):** if two alert runs collide, GitHub will block
one of the commits. Concurrency group is set to prevent this, but if it
happens just delete `alerts_state.json` and let it rebuild.

---

## Limits & honest tradeoffs

- **Alert latency: up to 30 min** worst case (15-min cron + RSS feed publish
  delay). Not literal real-time. To go faster you'd need paid webhooks or
  always-on hosting.
- **Indonesia coverage** depends on Antara/Tempo/Kontan/Kompas RSS uptime + a
  Google News proxy for Kompas. If a feed dies the script logs the failure and
  carries on with the rest.
- **Gemini quotas** can change. Google slashed limits in Dec 2025. Watch
  https://ai.google.dev/gemini-api/docs/rate-limits if briefings start failing.
- **Reuters & AP** removed public RSS in 2020. We use Google News as a proxy,
  which works well but has a ~1 hour lag.

Built 2026-04-30.
