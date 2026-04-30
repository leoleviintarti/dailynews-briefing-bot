"""
Curated RSS sources for daily briefing system.
All URLs verified live as of 2026-04-30.

Tier classification:
- TIER1_GLOBAL: International tier-1 newswires (Reuters, AP, BBC, FT, Bloomberg, Al Jazeera)
- TIER1_INDONESIA: Indonesia tier-1 (Antara, Tempo, Kontan, Kompas)
- DISASTER: Real-time disaster feeds (USGS earthquakes, GDACS multi-hazard)
- TECH_AI: Tech & AI breakthroughs (The Verge, Ars Technica)
"""

# Tier-1 international newswires
TIER1_GLOBAL = [
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "lang": "en",
        "weight": 1.0,
    },
    {
        "name": "Financial Times - World",
        "url": "https://www.ft.com/world?format=rss",
        "lang": "en",
        "weight": 1.0,
    },
    {
        "name": "Financial Times - Home",
        "url": "https://www.ft.com/rss/home",
        "lang": "en",
        "weight": 1.0,
    },
    {
        "name": "Bloomberg Markets",
        "url": "https://feeds.bloomberg.com/markets/news.rss",
        "lang": "en",
        "weight": 1.0,
    },
    {
        "name": "Al Jazeera",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "lang": "en",
        "weight": 0.9,
    },
    {
        "name": "Reuters (via Google News)",
        "url": "https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en",
        "lang": "en",
        "weight": 1.0,
    },
    {
        "name": "AP News (via Google News)",
        "url": "https://news.google.com/rss/search?q=site:apnews.com&hl=en-US&gl=US&ceid=US:en",
        "lang": "en",
        "weight": 1.0,
    },
]

# Tier-1 Indonesia sources
TIER1_INDONESIA = [
    {
        "name": "Antara - Terkini",
        "url": "https://www.antaranews.com/rss/terkini.xml",
        "lang": "id",
        "weight": 1.0,
    },
    {
        "name": "Tempo - Nasional",
        "url": "https://rss.tempo.co/nasional",
        "lang": "id",
        "weight": 1.0,
    },
    {
        "name": "Kontan - Markets/Ekonomi",
        "url": "https://www.kontan.co.id/rss",
        "lang": "id",
        "weight": 1.0,
    },
    {
        "name": "Kompas (via Google News)",
        "url": "https://news.google.com/rss/search?q=site:kompas.com&hl=id&gl=ID&ceid=ID:id",
        "lang": "id",
        "weight": 1.0,
    },
    {
        "name": "Indonesia Disaster Watch (Google News)",
        "url": "https://news.google.com/rss/search?q=indonesia+gempa+OR+banjir+OR+kebakaran+OR+bencana+OR+tsunami&hl=id&gl=ID&ceid=ID:id",
        "lang": "id",
        "weight": 1.1,
    },
    {
        "name": "Indonesia Economy Watch (Google News)",
        "url": "https://news.google.com/rss/search?q=rupiah+OR+IHSG+OR+inflasi+indonesia&hl=id&gl=ID&ceid=ID:id",
        "lang": "id",
        "weight": 1.0,
    },
]

# Disaster / hazard real-time feeds
DISASTER = [
    {
        "name": "USGS Significant Earthquakes",
        "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.atom",
        "lang": "en",
        "weight": 1.5,  # high priority
    },
    {
        "name": "GDACS Global Disasters",
        "url": "https://www.gdacs.org/xml/rss.xml",
        "lang": "en",
        "weight": 1.5,
    },
]

# Tech & AI breakthroughs
TECH_AI = [
    {
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
        "lang": "en",
        "weight": 0.9,
    },
    {
        "name": "Ars Technica",
        "url": "https://arstechnica.com/feed/",
        "lang": "en",
        "weight": 0.9,
    },
    {
        "name": "AI Breakthroughs (Google News)",
        "url": "https://news.google.com/rss/search?q=%22OpenAI%22+OR+%22Anthropic%22+OR+%22Google+DeepMind%22+OR+%22GPT%22+OR+%22Claude%22+OR+%22Gemini%22+breakthrough+OR+release&hl=en-US&gl=US&ceid=US:en",
        "lang": "en",
        "weight": 1.0,
    },
]

# All feeds combined
ALL_SOURCES = TIER1_GLOBAL + TIER1_INDONESIA + DISASTER + TECH_AI

# Lighter set used by alert checker (focused on high-signal feeds)
ALERT_SOURCES = (
    DISASTER
    + [s for s in TIER1_GLOBAL if s["name"] in ("BBC World", "Bloomberg Markets", "Reuters (via Google News)", "AP News (via Google News)")]
    + [s for s in TIER1_INDONESIA if "Disaster" in s["name"] or "Economy" in s["name"] or s["name"] == "Antara - Terkini"]
    + [s for s in TECH_AI if "Breakthroughs" in s["name"]]
)
