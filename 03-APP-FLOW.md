# App Flow Document
## AI News Bot | WhatsApp Channel Automation

**Version:** 1.0  
**Status:** Pre-Implementation

---

## 1. Master Flow Overview

```
GitHub Actions Cron (every 30 min)
           │
           ▼
    ┌─────────────┐
    │   STARTUP   │ ← Load config, init Supabase client
    └──────┬──────┘
           │
           ▼
    ┌─────────────────┐
    │  DAILY CAP      │ ── posts_today >= 5? ──► EXIT (log: cap reached)
    │  CHECK          │
    └──────┬──────────┘
           │ posts_today < 5
           ▼
    ┌─────────────────┐
    │  FETCH ALL      │ ← Parallel async fetch from all 10 sources
    │  SOURCES        │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  NORMALIZE      │ ← Convert all to Article dataclass
    │  ARTICLES       │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  FILTER         │ ← Recency (24h) + Keywords (include/exclude)
    │  ENGINE         │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  DEDUPLICATE    │ ← Layer 1: URL hash | Layer 2: Title similarity
    │  (2 layers)     │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  SCORE & SORT   │ ← By recency (newest first)
    │  CANDIDATES     │
    └──────┬──────────┘
           │
           │  For each candidate (until cap hit):
           ▼
    ┌─────────────────┐
    │  OG IMAGE       │ ← httpx GET → parse og:image → validate URL
    │  EXTRACTION     │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  LLM FALLBACK   │ ← Groq → Mistral → OpenRouter → Gemini → Raw
    │  CHAIN          │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  FORMAT         │ ← Build locked template string
    │  MESSAGE        │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  WRITE PAYLOAD  │ ← /tmp/article_payload.json
    │  TO DISK        │   + set GH Actions output: has_article=true
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  INSERT ARTICLE │ ← articles table: status=PENDING
    │  TO SUPABASE    │
    └──────┬──────────┘
           │
           ▼  (Python step ends — Node.js step begins)
    ┌─────────────────┐
    │  BAILEYS LOADS  │ ← Read creds from whatsapp_auth Supabase table
    │  SESSION        │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  ANTI-BAN       │ ← Random delay 5-15s + composing simulation
    │  LAYER          │
    └──────┬──────────┘
           │
           ▼
    ┌─────────────────┐
    │  SEND TO        │ ← image+caption OR text-only to newsletter JID
    │  WA CHANNEL     │
    └──────┬──────────┘
           │
    ┌──────┴──────────────────────────────┐
    │ SUCCESS                  FAILURE    │
    ▼                             ▼       │
┌──────────┐              ┌──────────┐   │
│ Update   │              │ Log to   │   │
│ articles │              │ error_log│   │
│ POSTED   │              │ retry 1x │   │
│ Insert   │              └──────────┘   │
│ post_log │                             │
└──────────┘                             │
           │                             │
           ▼                             │
    ┌─────────────────┐                  │
    │  SAVE BAILEYS   │ ← Re-serialize   │
    │  SESSION        │   creds to       │
    └──────┬──────────┘   Supabase       │
           │                             │
           ▼                             │
    ┌─────────────────┐                  │
    │  PROCESS NEXT   │ ──────────────────
    │  CANDIDATE      │ (if cap not hit)
    └─────────────────┘
```

---

## 2. Detailed Step-by-Step Flow

### Step 1: GitHub Actions Triggers

```
Trigger: Cron */30 * * * *
OR:      workflow_dispatch (manual)

Runner spins up ubuntu-latest
→ Python 3.11 installed
→ Node.js 20 installed
→ Dependencies installed (cached where possible)
→ Secrets injected as environment variables
→ Python orchestrator/main.py executed
```

---

### Step 2: Startup & Configuration

```
orchestrator/main.py:

1. Load config.py
   → Read all env vars
   → Validate all required vars are present
   → Raise ConfigError immediately if any missing
   → Log startup: timestamp, run ID

2. Initialize Supabase client (db.py)
   → Test connection with lightweight query
   → If connection fails: log error, exit with code 1

3. Log: "Run started — checking feeds"
```

---

### Step 3: Daily Cap Check

```
db.py → get_posts_today()

Query:
SELECT COUNT(*) FROM post_log
WHERE posted_at > NOW() - INTERVAL '24 hours'
AND status = 'success'

→ Result >= 5:
   Log: "Daily cap reached (X/5). Exiting."
   Set GH Actions output: has_article=false
   Exit cleanly (code 0)

→ Result < 5:
   remaining = 5 - result
   Log: "Cap check passed. {remaining} posts remaining today."
   Continue to fetch.
```

---

### Step 4: Parallel Feed Fetch

```
fetcher/rss.py (async):

Sources fetched concurrently via asyncio.gather():
- TechCrunch AI RSS
- The Verge AI RSS
- VentureBeat AI RSS
- MIT Technology Review RSS
- Wired AI RSS
- Hugging Face Blog RSS
- Google AI Blog RSS
- OpenAI Blog RSS

Per source (all in try/except):
  1. feedparser.parse(url) with timeout=15s
  2. If parse error → log to error_log, skip source, continue
  3. Extract: title, link, summary/description, published
  4. Parse published to UTC-aware datetime
  5. Normalize to Article dataclass

fetcher/hackernews.py:
  GET https://hn.algolia.com/api/v1/search?tags=story&query=AI&hitsPerPage=5
  → Parse hits[] → normalize to Article dataclass

fetcher/reddit.py:
  GET https://www.reddit.com/r/artificial/top.json?limit=5&t=day
  Headers: User-Agent: newsbot/1.0
  → Parse data.children[] → normalize to Article dataclass

All results merged into single list: List[Article]
Log: "Fetched {N} raw articles from {M} sources"
```

---

### Step 5: Filter Engine

```
filter/recency.py:
  For each article:
  → article.published_at > (NOW() - 24 hours)?
  → No → discard
  → Yes → keep

filter/keywords.py:
  INCLUDE_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "model",
    "agent", "startup", "funding", "open source",
    "anthropic", "openai", "deepmind", "mistral",
    "machine learning", "neural", "transformer"
  ]

  EXCLUDE_KEYWORDS = [
    "celebrity", "sports", "nfl", "nba", "fifa",
    "entertainment", "music", "movie", "election",
    "political party", "vote"
  ]

  Check: (title + description).lower()
  → Contains any EXCLUDE keyword → discard
  → Contains any INCLUDE keyword → keep
  → Contains neither → discard (not clearly AI/tech)

Log: "Filtered to {N} relevant articles from last 24 hours"
```

---

### Step 6: Two-Layer Deduplication

```
dedup/hash.py — LAYER 1:
  For each filtered article:
  → hash = md5(article.url.strip().lower())
  → Query Supabase: SELECT 1 FROM articles WHERE hash = ?
  → Exists → mark as duplicate, skip
  → Not exists → pass to Layer 2

dedup/similarity.py — LAYER 2:
  For each Layer 1 survivor:
  → Fetch from Supabase: titles of articles posted in last 48h
  → For each posted title:
      ratio = SequenceMatcher(None, new_title.lower(), posted_title.lower()).ratio()
      ratio >= 0.75 → mark as duplicate, skip
  → All ratios < 0.75 → article passes deduplication

Log: "Dedup complete. {N} new unique articles to process."

Edge case: If 0 articles survive dedup:
→ Log: "No new unique articles this run."
→ Set has_article=false
→ Exit cleanly
```

---

### Step 7: Score & Sort

```
Sort surviving articles by published_at descending (newest first)
Slice to first (remaining_cap) articles
→ These are the candidates for this run
```

---

### Step 8: OG Image Extraction

```
extractor/og_image.py (per article):

1. httpx.get(article.url, timeout=10, follow_redirects=True)
   → Headers: User-Agent: Mozilla/5.0 (compatible; newsbot/1.0)

2. If request fails (timeout, 403, 404, connection error):
   → article.og_image_url = None
   → Log warning, continue (no crash)

3. Parse HTML with BeautifulSoup(html, 'lxml')
4. Find: soup.find('meta', property='og:image')
5. Extract content attribute value
6. Validate: must start with 'https://'
7. If valid → article.og_image_url = url
8. If invalid/missing → article.og_image_url = None
```

---

### Step 9: LLM Fallback Chain

```
llm/summarizer.py (per article):

article_content = article.title + "\n\n" + article.description

PROVIDER_CHAIN = [
  GroqProvider(),
  MistralProvider(),
  OpenRouterProvider(model="meta-llama/llama-3.3-70b-instruct:free"),
  OpenRouterProvider(model="mistralai/mistral-small-3.2-24b-instruct:free"),
  GeminiProvider()
]

for provider in PROVIDER_CHAIN:
  try:
    result = provider.summarize(article.title, article_content)
    result.llm_provider = provider.name
    Log: "Summarized via {provider.name}"
    return result
  except Exception as e:
    log_error(component="llm", provider=provider.name, error=str(e), hash=article.hash)
    continue

# All providers failed:
Log: "All LLM providers failed. Using raw RSS fallback."
return raw_fallback(article)
→ result.used_raw_fallback = True
→ result.llm_provider = "raw"
```

---

### Step 10: Message Formatting

```
formatter/message.py:

Build string using locked template:
→ Replace all None/empty fields with safe defaults
→ Truncate conclusion if total > 4096 chars
→ Validate output contains all required sections

If used_raw_fallback:
→ Use simplified fallback template (see Document 4)
→ paragraph_2, paragraph_3, points all omitted

Output: formatted_text: str
```

---

### Step 11: Write Payload & Set Output

```
Write to /tmp/article_payload.json:
{
  "article_hash": "...",
  "formatted_message": "...",
  "og_image_url": "https://..." or null,
  "has_image": true/false
}

Set GitHub Actions output:
  echo "has_article=true" >> $GITHUB_OUTPUT
  echo "payload_path=/tmp/article_payload.json" >> $GITHUB_OUTPUT

Insert to Supabase articles table:
  status = 'PENDING'
  fetched_at = NOW()

Python step ends.
```

---

### Step 12: Baileys Session Load

```
baileys-sender/sender.js:

1. Read ARTICLE_PAYLOAD_PATH env var
2. Load and parse /tmp/article_payload.json
3. Initialize Supabase client (JS)
4. Call useSupabaseAuthState(supabase)
   → Reads all rows from whatsapp_auth table
   → Reconstructs Baileys auth state object in memory
   → Returns { state, saveCreds }

5. Create Baileys socket:
   makeWASocket({
     auth: state,
     logger: pino({ level: 'silent' }),
     browser: ['NewsBot', 'Chrome', '120.0.0'],
     generateHighQualityLinkPreview: false,
     connectTimeoutMs: 30000
   })

6. Wait for connection.update event:
   → 'open' → proceed to send
   → 'close' (not reconnecting) → log error, exit 1
   → QR code required → THIS MEANS SESSION EXPIRED
     Log error: "Session expired — manual re-pair required"
     Exit 1 (this triggers error in GitHub Actions — visible in Actions log)
```

---

### Step 13: Anti-Ban Layer

```
baileys-sender/utils/antiBan.js:

1. Random delay: await sleep(randomInt(5000, 15000)) // 5-15 seconds

2. Composing simulation:
   await sock.sendPresenceUpdate('composing', channelJid)
   await sleep(randomInt(2000, 4000))
   await sock.sendPresenceUpdate('paused', channelJid)
   await sleep(randomInt(1000, 2000))

3. UA rotation (via browser param in makeWASocket):
   Randomly select from:
   ['Chrome', '120.0.0'], ['Chrome', '121.0.0'],
   ['Safari', '17.0'], ['Firefox', '121.0']
```

---

### Step 14: Send to WhatsApp Channel

```
const channelJid = process.env.WHATSAPP_CHANNEL_JID

if (payload.has_image && payload.og_image_url) {
  await sock.sendMessage(channelJid, {
    image: { url: payload.og_image_url },
    caption: payload.formatted_message
  })
} else {
  await sock.sendMessage(channelJid, {
    text: payload.formatted_message
  })
}
```

---

### Step 15: Post-Send Logging

```
ON SUCCESS:
1. Call supabase update articles SET status='POSTED', posted_at=NOW() WHERE hash=?
2. Insert into post_log: { article_hash, posted_at, status='success' }
3. Call saveCreds() → re-serialize entire Baileys auth state to whatsapp_auth table
4. Log: "Posted successfully. Session saved."
5. Exit 0

ON FAILURE:
1. Log error to console
2. Wait 60 seconds
3. Retry send once
4. If retry fails:
   → Supabase: INSERT into error_log
   → Supabase: UPDATE articles SET status='FAILED' WHERE hash=?
   → Exit 1 (GitHub Actions marks step as failed — visible in UI)
```

---

## 3. Edge Case Flows

### 3.1 Zero New Articles

```
All 10 sources return only articles seen before
→ Both dedup layers filter everything
→ Log: "No new unique articles this run"
→ Set has_article=false
→ Python exits 0
→ Baileys step SKIPPED (conditional: has_article == 'true')
→ Total run time: ~30 seconds
→ No WhatsApp connection made
```

### 3.2 Daily Cap Already Reached

```
Step 3 query returns >= 5
→ Log: "Daily cap reached"
→ Exit immediately (Python)
→ Baileys NEVER runs
→ Total run time: ~5 seconds
```

### 3.3 All LLMs Down Simultaneously

```
All 5 providers in chain raise exceptions
→ raw_fallback() called
→ SummaryResult built from raw RSS description
→ used_raw_fallback = True
→ Simplified format template used
→ Post still sent — never skipped
```

### 3.4 WhatsApp Session Expired

```
Baileys loads state from Supabase
→ Connection attempt results in QR code required
→ Log: "SESSION EXPIRED — manual re-pair required"
→ Exit 1
→ GitHub Actions step marked FAILED
→ Email notification (if GitHub notifications enabled for Actions failures)
→ Operator must run manual setup to re-pair
```

### 3.5 Supabase Down

```
Python startup: Supabase connection fails
→ Log: "Supabase connection failed: {error}"
→ Exit 1 (cannot proceed — dedup requires DB)
→ This run is lost — no post this run
→ Next run in 30 minutes retries
```

### 3.6 Image URL Returns 4xx / Hotlink Blocked

```
OG image extraction:
→ httpx raises exception or returns 403/404
→ article.og_image_url = None
→ has_image = false in payload
→ Baileys sends text-only post
→ Post delivered — not skipped
```

---

## 4. Daily Timeline (Example)

```
00:00  Run 1:  3 new articles found → 1 passes all filters → POSTED (1/5)
00:30  Run 2:  0 new unique articles → exit cleanly
01:00  Run 3:  0 new unique articles → exit cleanly
...
06:30  Run 14: 2 new articles found → POSTED (2/5, 3/5)
...
12:00  Run 25: 1 new article found → POSTED (4/5)
...
18:30  Run 38: 1 new article found → POSTED (5/5)
19:00  Run 39: cap check → 5/5 → exit immediately
...
23:30  Run 48: cap check → 5/5 → exit immediately
00:00  NEXT DAY: first run → cap resets → resumes normal flow
```

---
