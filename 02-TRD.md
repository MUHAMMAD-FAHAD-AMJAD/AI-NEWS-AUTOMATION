# TRD — Technical Requirements Document
## AI News Bot | WhatsApp Channel Automation

**Version:** 1.0  
**Status:** Pre-Implementation

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    GITHUB ACTIONS CRON                          │
│                   (Every 30 minutes)                            │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                  PYTHON ORCHESTRATOR                             │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  RSS FETCHER │  │  API FETCHER │  │   FILTER ENGINE      │  │
│  │  (feedparser)│  │  (HN+Reddit) │  │  (recency+keywords)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         └─────────────────┴──────────────────────┘             │
│                            │                                    │
│                            ▼                                    │
│                 ┌──────────────────────┐                       │
│                 │  DEDUPLICATION       │                       │
│                 │  Layer 1: URL hash   │                       │
│                 │  Layer 2: Title sim  │                       │
│                 └──────────┬───────────┘                       │
│                            │                                    │
│                            ▼                                    │
│                 ┌──────────────────────┐                       │
│                 │  DAILY CAP CHECK     │                       │
│                 │  (Supabase query)    │                       │
│                 └──────────┬───────────┘                       │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                LLM FALLBACK CHAIN                       │   │
│  │  Groq → Mistral → OpenRouter(x2) → Gemini → Raw RSS    │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                    │
│                            ▼                                    │
│                 ┌──────────────────────┐                       │
│                 │  MESSAGE FORMATTER   │                       │
│                 │  (locked template)   │                       │
│                 └──────────┬───────────┘                       │
│                            │                                    │
│                            ▼                                    │
│                 ┌──────────────────────┐                       │
│                 │  OG IMAGE EXTRACTOR  │                       │
│                 │  (httpx + BS4)       │                       │
│                 └──────────┬───────────┘                       │
│                            │                                    │
│         Writes article + formatted text to temp file           │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼  (Only if article confirmed ready)
┌─────────────────────────────────────────────────────────────────┐
│                   NODE.JS BAILEYS SCRIPT                        │
│                                                                 │
│  ┌────────────────────────┐  ┌──────────────────────────────┐  │
│  │  useSupabaseAuthState  │  │  Channel Post Handler        │  │
│  │  (load creds from DB)  │  │  (image+caption or text)     │  │
│  └────────────┬───────────┘  └──────────────┬───────────────┘  │
│               │                              │                  │
│               └──────────┬───────────────────┘                  │
│                          │                                      │
│                 ┌────────▼──────────┐                           │
│                 │  Anti-Ban Layer   │                           │
│                 │  - Random delay   │                           │
│                 │  - Composing sim  │                           │
│                 │  - UA rotation    │                           │
│                 └────────┬──────────┘                           │
│                          │                                      │
│                 ┌────────▼──────────┐                           │
│                 │  WhatsApp Channel │                           │
│                 │  (newsletter JID) │                           │
│                 └───────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SUPABASE POSTGRESQL                          │
│         articles | post_log | whatsapp_auth                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Technology Stack

### 2.1 Hosting & Scheduler

| Component | Technology | Reason |
|-----------|-----------|--------|
| Scheduler | GitHub Actions cron (`*/30 * * * *`) | Free, reliable, no always-on server needed, ephemeral Ubuntu runners |
| Python runtime | ubuntu-latest + Python 3.11 | Stable, compatible with all libraries |
| Node.js runtime | ubuntu-latest + Node 20 LTS | Required for Baileys |
| Secrets management | GitHub Actions Secrets | Secure env var injection, no .env files in repo |

**Critical note on GitHub Actions free tier:**
- 2,000 minutes/month on free tier
- 48 runs/day × 30 days × ~2 min/run = ~2,880 min/month
- This **exceeds** the free tier limit by ~880 minutes
- **Mitigation:** Keep runs under 60 seconds average (most runs find nothing new and exit fast). Target: 2,000 runs/month × 1 min average = within limit. Monitor usage in first week.
- **Alternative if minutes run out:** Switch cron to `0 */2 * * *` (every 2 hours, 12 runs/day = 720 min/month).

### 2.2 WhatsApp Delivery

| Component | Technology | Reason |
|-----------|-----------|--------|
| WA Engine | Baileys (latest) | Only free open-source WhatsApp multi-device client |
| Connection type | Newsletter JID (`120363xxxxxxxxxx@newsletter`) | Required for WhatsApp Channels |
| Session storage | Supabase JSONB (custom auth state) | Survives GitHub Actions container wipe |
| Anti-ban | Random delays, composing simulation, UA rotation | Reduces fingerprinting risk |

### 2.3 News Fetching

| Source Type | Technology | Libraries |
|-------------|-----------|-----------|
| RSS feeds | feedparser 6.x | `feedparser` |
| OG image | Article HTML scrape | `httpx`, `beautifulsoup4`, `lxml` |
| Hacker News | Algolia Search API | `httpx` |
| Reddit | JSON API endpoint | `httpx` |

### 2.4 LLM Summarization Chain

| Priority | Provider | Model | Free Limit | Failure Action |
|----------|---------|-------|-----------|----------------|
| 1 | Groq | llama-3.3-70b-versatile | 14,400 req/day | Raise exception → next |
| 2 | Mistral API | mistral-small-latest | 1 req/sec, limited daily | Raise exception → next |
| 3a | OpenRouter | meta/llama-3.3-70b-instruct:free | Shared pool | Raise exception → next |
| 3b | OpenRouter | mistralai/mistral-small-3.2-24b:free | Shared pool | Raise exception → next |
| 4 | Gemini | gemini-1.5-flash | 15 RPM, 1M TPD | Raise exception → next |
| 5 | Raw RSS | N/A — direct description | Always works | Final fallback |

### 2.5 Database

| Component | Technology | Reason |
|-----------|-----------|--------|
| Primary DB | Supabase PostgreSQL (free tier) | 500MB storage, REST API, no server needed |
| Client | `supabase-py` | Official Python client |
| Session storage | Supabase JSONB column | Stores entire Baileys auth state as JSON |

### 2.6 Deduplication

| Layer | Method | Threshold | Purpose |
|-------|--------|-----------|---------|
| Layer 1 | MD5(url) hash lookup in `articles` table | Exact match | Catches same URL from any source |
| Layer 2 | `SequenceMatcher(title_a, title_b).ratio()` against last 48h posted titles | ≥ 0.75 | Catches same story from different sources with different URLs |

---

## 3. GitHub Actions Workflow Design

### 3.1 Workflow File: `.github/workflows/newsbot.yml`

```yaml
name: AI News Bot
on:
  schedule:
    - cron: '*/30 * * * *'
  workflow_dispatch:  # Manual trigger for testing

jobs:
  run-newsbot:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: baileys-sender/package-lock.json

      - name: Install Python dependencies
        run: pip install -r requirements.txt

      - name: Install Node dependencies
        working-directory: baileys-sender
        run: npm ci

      - name: Run Python Orchestrator
        id: orchestrator
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          MISTRAL_API_KEY: ${{ secrets.MISTRAL_API_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          WHATSAPP_CHANNEL_JID: ${{ secrets.WHATSAPP_CHANNEL_JID }}
        run: python orchestrator/main.py

      - name: Run Baileys Sender (only if article ready)
        if: steps.orchestrator.outputs.has_article == 'true'
        working-directory: baileys-sender
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          WHATSAPP_CHANNEL_JID: ${{ secrets.WHATSAPP_CHANNEL_JID }}
          ARTICLE_PAYLOAD_PATH: ${{ steps.orchestrator.outputs.payload_path }}
        run: node sender.js
```

**Key design decision:** The Python step sets a GitHub Actions output variable `has_article=true/false`. The Node.js Baileys step only runs if `has_article == 'true'`. This means Baileys connects to WhatsApp at most 5 times per day — never 48. This is the primary anti-ban mechanism.

---

## 4. Environment Variables & Secrets

### 4.1 GitHub Actions Secrets Required

| Secret Name | Value | Where to Get |
|-------------|-------|-------------|
| `SUPABASE_URL` | `https://xxxx.supabase.co` | Supabase project settings |
| `SUPABASE_KEY` | `eyJ...` (anon key) | Supabase project settings → API |
| `GROQ_API_KEY` | `gsk_...` | console.groq.com |
| `MISTRAL_API_KEY` | `...` | console.mistral.ai |
| `OPENROUTER_API_KEY` | `sk-or-...` | openrouter.ai/keys |
| `GEMINI_API_KEY` | `AIza...` | aistudio.google.com |
| `WHATSAPP_CHANNEL_JID` | `120363xxxxxxxxxx@newsletter` | Extracted from Baileys on first scan |

---

## 5. File & Directory Structure

```
whatsapp-newsbot/
│
├── .github/
│   └── workflows/
│       └── newsbot.yml               # GitHub Actions cron workflow
│
├── orchestrator/                     # Python package
│   ├── main.py                       # Entry point — orchestrates all steps
│   ├── config.py                     # Loads env vars, validates presence
│   ├── db.py                         # Supabase client + all DB operations
│   │
│   ├── fetcher/
│   │   ├── __init__.py
│   │   ├── rss.py                    # feedparser RSS fetch + normalize
│   │   ├── hackernews.py             # HN Algolia API fetch
│   │   ├── reddit.py                 # Reddit JSON API fetch
│   │   └── normalizer.py             # Article dataclass + source normalization
│   │
│   ├── filter/
│   │   ├── __init__.py
│   │   ├── recency.py                # 24-hour published_at check
│   │   └── keywords.py               # Include/exclude keyword matching
│   │
│   ├── dedup/
│   │   ├── __init__.py
│   │   ├── hash.py                   # MD5 URL hash generation
│   │   └── similarity.py             # SequenceMatcher title similarity
│   │
│   ├── extractor/
│   │   ├── __init__.py
│   │   └── og_image.py               # httpx + BS4 OG image extraction
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── prompt.py                 # Shared summarization prompt
│   │   ├── groq_provider.py
│   │   ├── mistral_provider.py
│   │   ├── openrouter_provider.py
│   │   ├── gemini_provider.py
│   │   ├── raw_fallback.py           # RSS description passthrough
│   │   └── summarizer.py             # Fallback chain orchestrator
│   │
│   ├── formatter/
│   │   ├── __init__.py
│   │   └── message.py                # Locked template builder
│   │
│   └── models/
│       ├── __init__.py
│       ├── article.py                # Article dataclass
│       └── summary.py                # SummaryResult dataclass
│
├── baileys-sender/                   # Node.js package
│   ├── package.json
│   ├── package-lock.json
│   ├── sender.js                     # Main Baileys entry point
│   ├── auth/
│   │   └── supabaseAuthState.js      # Custom useSupabaseAuthState()
│   └── utils/
│       └── antiBan.js                # Delays, composing sim, UA rotation
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 6. Article Data Model

### 6.1 Python Article Dataclass

```python
@dataclass
class Article:
    hash: str                          # MD5(url)
    title: str
    url: str
    description: str                   # Raw RSS description
    published_at: datetime             # UTC-aware datetime
    source: str                        # e.g., "techcrunch", "hackernews"
    og_image_url: Optional[str] = None # Extracted after filter passes

@dataclass
class SummaryResult:
    headline: str                      # CAPS version of title
    paragraph_1: str
    paragraph_2: str
    paragraph_3: str
    point_1: str
    point_2: str
    point_3: str
    point_4: str
    point_5: str
    conclusion: str
    llm_provider: str                  # Which provider succeeded
    used_raw_fallback: bool = False
```

### 6.2 Article Payload (Python → Node.js handoff)

Written to `/tmp/article_payload.json` by Python, read by Baileys:

```json
{
  "article_hash": "abc123...",
  "formatted_message": "📰 *HEADLINE...*\n\n📋 *Summary:*...",
  "og_image_url": "https://example.com/image.jpg",
  "has_image": true
}
```

---

## 7. API Specifications

### 7.1 Supabase REST — articles insert
```
POST {SUPABASE_URL}/rest/v1/articles
Authorization: Bearer {SUPABASE_KEY}
Content-Type: application/json

{
  "hash": "md5hash",
  "title": "...",
  "url": "...",
  "source": "techcrunch",
  "status": "POSTED"
}
```

### 7.2 Groq API (OpenAI-compatible)
```
POST https://api.groq.com/openai/v1/chat/completions
Authorization: Bearer {GROQ_API_KEY}

{
  "model": "llama-3.3-70b-versatile",
  "messages": [{"role": "user", "content": "{PROMPT}"}],
  "max_tokens": 1200,
  "temperature": 0.3
}
```

### 7.3 OpenRouter API (OpenAI-compatible)
```
POST https://openrouter.ai/api/v1/chat/completions
Authorization: Bearer {OPENROUTER_API_KEY}
HTTP-Referer: https://github.com/{YOUR_REPO}
X-Title: AI News Bot

{
  "model": "meta-llama/llama-3.3-70b-instruct:free",
  "messages": [...],
  "max_tokens": 1200
}
```

### 7.4 Gemini API
```
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}

{
  "contents": [{"parts": [{"text": "{PROMPT}"}]}],
  "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.3}
}
```

### 7.5 Baileys — Channel Post
```javascript
// Image + caption
await sock.sendMessage(channelJid, {
  image: { url: og_image_url },
  caption: formatted_message
});

// Text only (no image)
await sock.sendMessage(channelJid, {
  text: formatted_message
});
```

---

## 8. Dependencies

### 8.1 Python — `requirements.txt`
```
feedparser==6.0.11
httpx==0.27.0
beautifulsoup4==4.12.3
lxml==5.2.2
supabase==2.4.0
openai==1.35.0          # Used for Groq + OpenRouter (both OAI-compatible)
mistralai==1.0.0
google-generativeai==0.7.0
python-dotenv==1.0.1
python-dateutil==2.9.0
```

### 8.2 Node.js — `baileys-sender/package.json`
```json
{
  "name": "baileys-sender",
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "@whiskeysockets/baileys": "latest",
    "@supabase/supabase-js": "^2.43.0",
    "pino": "^9.0.0",
    "qrcode-terminal": "^0.12.0"
  }
}
```

---

## 9. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| API keys in code | All secrets via GitHub Actions Secrets only — never in repo |
| WhatsApp number ban | Dedicated SIM, lazy auth, anti-ban layer, max 5 WA connections/day |
| Supabase key exposure | Use anon key with RLS policies — only allow insert/select on own tables |
| RSS feed injection | feedparser sanitizes feed content — no eval/exec on feed data |
| OG image SSRF | Validate image URL scheme (`https://`) before passing to Baileys |

---

## 10. Monitoring & Observability

Since there is no dashboard, observability is entirely through Supabase:

| What to Check | How |
|--------------|-----|
| Posts sent today | `SELECT COUNT(*) FROM post_log WHERE posted_at > NOW() - INTERVAL '24 hours' AND status = 'success'` |
| Last successful post | `SELECT posted_at FROM post_log ORDER BY posted_at DESC LIMIT 1` |
| Error frequency | `SELECT component, COUNT(*) FROM error_log GROUP BY component ORDER BY 2 DESC` |
| LLM provider breakdown | `SELECT llm_provider, COUNT(*) FROM post_log GROUP BY llm_provider` |
| Articles seen but not posted | `SELECT * FROM articles WHERE status = 'PENDING' ORDER BY fetched_at DESC` |

---
