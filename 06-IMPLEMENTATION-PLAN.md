# Implementation Plan
## AI News Bot | WhatsApp Channel Automation

**Version:** 1.0  
**Build Approach:** Phase-by-phase. Each phase is independently testable. Never move to next phase until current phase passes all tests.

---

## Phase Map Overview

```
Phase 1:  Project scaffold + secrets + Supabase setup
Phase 2:  RSS fetcher + normalizer (Python)
Phase 3:  Filter engine + deduplication (Python)
Phase 4:  OG image extractor (Python)
Phase 5:  LLM fallback chain (Python)
Phase 6:  Message formatter + payload writer (Python)
Phase 7:  GitHub Actions workflow (Python side only, no WA yet)
Phase 8:  Baileys WhatsApp session setup (first-time QR scan)
Phase 9:  Baileys sender + Supabase auth state (Node.js)
Phase 10: End-to-end integration + anti-ban layer
Phase 11: Production hardening + monitoring queries
```

**Estimated build time:** 8–12 days working solo, ~2-3 hours/day.

---

## Phase 1: Project Scaffold + Secrets + Supabase Setup

**Goal:** Everything is wired up, all credentials work, DB tables exist.

### 1.1 Create GitHub Repository

```bash
# Initialize repo
git init whatsapp-newsbot
cd whatsapp-newsbot
git checkout -b main

# Create directory structure
mkdir -p orchestrator/fetcher
mkdir -p orchestrator/filter
mkdir -p orchestrator/dedup
mkdir -p orchestrator/extractor
mkdir -p orchestrator/llm
mkdir -p orchestrator/formatter
mkdir -p orchestrator/models
mkdir -p baileys-sender/auth
mkdir -p baileys-sender/utils
mkdir -p .github/workflows
```

### 1.2 Create `.gitignore`

```gitignore
# Python
__pycache__/
*.pyc
.venv/
.env

# Node
node_modules/
baileys-sender/node_modules/

# Secrets — never commit
.env
*.json.local
creds.json
auth_info_*

# Temp files
/tmp/
*.tmp
article_payload.json
```

### 1.3 Create `requirements.txt`

```
feedparser==6.0.11
httpx==0.27.0
beautifulsoup4==4.12.3
lxml==5.2.2
supabase==2.4.0
openai==1.35.0
mistralai==1.0.0
google-generativeai==0.7.0
python-dotenv==1.0.1
python-dateutil==2.9.0
```

### 1.4 Create `orchestrator/config.py`

```python
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class Config:
    supabase_url: str
    supabase_key: str
    groq_api_key: str
    mistral_api_key: str
    openrouter_api_key: str
    gemini_api_key: str
    whatsapp_channel_jid: str
    max_posts_per_day: int = 5
    poll_lookback_hours: int = 24
    similarity_threshold: float = 0.75

def load_config() -> Config:
    required = [
        'SUPABASE_URL', 'SUPABASE_KEY', 'GROQ_API_KEY',
        'MISTRAL_API_KEY', 'OPENROUTER_API_KEY', 'GEMINI_API_KEY',
        'WHATSAPP_CHANNEL_JID'
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise ValueError(f"Missing required environment variables: {missing}")
    
    return Config(
        supabase_url=os.environ['SUPABASE_URL'],
        supabase_key=os.environ['SUPABASE_KEY'],
        groq_api_key=os.environ['GROQ_API_KEY'],
        mistral_api_key=os.environ['MISTRAL_API_KEY'],
        openrouter_api_key=os.environ['OPENROUTER_API_KEY'],
        gemini_api_key=os.environ['GEMINI_API_KEY'],
        whatsapp_channel_jid=os.environ['WHATSAPP_CHANNEL_JID'],
    )
```

### 1.5 Set Up Supabase

1. Go to [supabase.com](https://supabase.com) → New project
2. Note your Project URL and anon/public API key
3. Open SQL Editor → paste entire SQL from Document 5 → Run
4. Verify all 4 tables created: `articles`, `post_log`, `whatsapp_auth`, `error_log`

### 1.6 Set GitHub Actions Secrets

In your repo: Settings → Secrets and variables → Actions → New repository secret

Add all 7 secrets:
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `GROQ_API_KEY`
- `MISTRAL_API_KEY`
- `OPENROUTER_API_KEY`
- `GEMINI_API_KEY`
- `WHATSAPP_CHANNEL_JID` ← leave empty for now, fill in Phase 8

### 1.7 Phase 1 Test

```bash
# Create local .env for testing
cp .env.example .env
# Fill in all values

# Test config loads
cd orchestrator
python -c "from config import load_config; c = load_config(); print('Config OK:', c.supabase_url[:30])"

# Test Supabase connection
python -c "
from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv()
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
res = sb.table('articles').select('count').execute()
print('Supabase OK:', res)
"
```

**Phase 1 done when:** Config loads, Supabase connection succeeds, all 4 tables exist.

---

## Phase 2: RSS Fetcher + Normalizer

**Goal:** Fetch articles from all 10 sources, normalize to Article dataclass.

### 2.1 Create `orchestrator/models/article.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import hashlib

@dataclass
class Article:
    title: str
    url: str
    description: str
    published_at: datetime
    source: str
    hash: str = field(init=False)
    og_image_url: Optional[str] = None

    def __post_init__(self):
        self.hash = hashlib.md5(self.url.strip().lower().encode()).hexdigest()
    
    def __repr__(self):
        return f"Article(source={self.source}, title={self.title[:60]}...)"
```

### 2.2 Create `orchestrator/fetcher/rss.py`

Full implementation: parse all 8 RSS feeds, normalize each entry, handle errors per-source, return `List[Article]`.

Key points:
- Use `asyncio.gather` with `asyncio.to_thread(feedparser.parse, url)` — feedparser is sync
- Wrap each source in try/except — log to stderr, continue
- Parse `published_parsed` → UTC datetime using `calendar.timegm()`
- Strip HTML from description using BeautifulSoup
- Set timeout via `feedparser.parse(url, agent='newsbot/1.0', request_headers={'Connection': 'close'})`

### 2.3 Create `orchestrator/fetcher/hackernews.py`

```python
import httpx
from orchestrator.models.article import Article
from datetime import datetime, timezone

async def fetch_hackernews() -> list[Article]:
    url = "https://hn.algolia.com/api/v1/search?tags=story&query=AI&hitsPerPage=5"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        
        articles = []
        for hit in data.get('hits', []):
            if not hit.get('url') or not hit.get('title'):
                continue
            articles.append(Article(
                title=hit['title'],
                url=hit['url'],
                description=hit.get('story_text', '') or hit.get('title', ''),
                published_at=datetime.fromtimestamp(
                    hit['created_at_i'], tz=timezone.utc
                ),
                source='hackernews'
            ))
        return articles
    except Exception as e:
        print(f"[ERROR] HN fetch failed: {e}")
        return []
```

### 2.4 Create `orchestrator/fetcher/reddit.py`

Similar to HN fetcher. Use `https://www.reddit.com/r/artificial/top.json?limit=5&t=day` with `User-Agent: newsbot/1.0` header.

### 2.5 Phase 2 Test

```python
# test_fetcher.py
import asyncio
from orchestrator.fetcher.rss import fetch_all_rss
from orchestrator.fetcher.hackernews import fetch_hackernews
from orchestrator.fetcher.reddit import fetch_reddit

async def test():
    rss = await fetch_all_rss()
    hn = await fetch_hackernews()
    reddit = await fetch_reddit()
    
    all_articles = rss + hn + reddit
    print(f"Total articles fetched: {len(all_articles)}")
    for a in all_articles[:5]:
        print(f"  [{a.source}] {a.title[:80]}")

asyncio.run(test())
```

**Phase 2 done when:** 20–80 articles printed from multiple sources, no unhandled exceptions.

---

## Phase 3: Filter Engine + Deduplication

**Goal:** Only unique, relevant, recent articles pass to the next stage.

### 3.1 Create `orchestrator/filter/recency.py`

```python
from datetime import datetime, timezone, timedelta

def is_recent(article, lookback_hours: int = 24) -> bool:
    if not article.published_at:
        return False
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    return article.published_at > cutoff
```

### 3.2 Create `orchestrator/filter/keywords.py`

```python
INCLUDE = [
    "ai", "llm", "gpt", "claude", "gemini", "model", "agent",
    "startup", "funding", "open source", "anthropic", "openai",
    "deepmind", "mistral", "hugging face", "machine learning",
    "neural", "transformer", "generative", "chatbot", "copilot",
    "nvidia", "inference", "fine-tun", "foundation model"
]

EXCLUDE = [
    "celebrity", "sports", "nfl", "nba", "fifa", "soccer",
    "entertainment", "music video", "box office", "election",
    "vote", "political party", "congress bill", "senate",
    "gossip", "dating", "romance"
]

def passes_keyword_filter(article) -> bool:
    text = (article.title + " " + article.description).lower()
    if any(kw in text for kw in EXCLUDE):
        return False
    if any(kw in text for kw in INCLUDE):
        return True
    return False
```

### 3.3 Create `orchestrator/dedup/hash.py`

```python
from supabase import Client

def is_url_duplicate(article, supabase: Client) -> bool:
    result = supabase.table('articles').select('hash').eq('hash', article.hash).limit(1).execute()
    return len(result.data) > 0
```

### 3.4 Create `orchestrator/dedup/similarity.py`

```python
from difflib import SequenceMatcher
from supabase import Client

def is_title_duplicate(article, supabase: Client, threshold: float = 0.75) -> bool:
    result = supabase.table('articles') \
        .select('title') \
        .gte('fetched_at', 'now() - interval \'48 hours\'') \
        .in_('status', ['POSTED', 'PENDING']) \
        .execute()
    
    for row in result.data:
        ratio = SequenceMatcher(
            None,
            article.title.lower(),
            row['title'].lower()
        ).ratio()
        if ratio >= threshold:
            return True
    return False
```

### 3.5 Phase 3 Test

```python
# test_filter.py — run after Phase 2
# Feed all fetched articles through filter + dedup
# Print pass/fail reason for each
# Expected: 5-20% pass rate on a typical run
```

**Phase 3 done when:** Filters correctly eliminate old, off-topic, and duplicate articles. Test by running twice — second run should return 0 new articles.

---

## Phase 4: OG Image Extractor

**Goal:** Extract article thumbnail or return None gracefully.

### 4.1 Create `orchestrator/extractor/og_image.py`

```python
import httpx
from bs4 import BeautifulSoup
from typing import Optional

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-US,en;q=0.9',
}

async def extract_og_image(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(
            timeout=10,
            follow_redirects=True,
            headers=HEADERS
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            
            soup = BeautifulSoup(resp.text, 'lxml')
            
            # Try og:image first
            og = soup.find('meta', property='og:image')
            if og and og.get('content', '').startswith('https://'):
                return og['content']
            
            # Try twitter:image as fallback
            tw = soup.find('meta', attrs={'name': 'twitter:image'})
            if tw and tw.get('content', '').startswith('https://'):
                return tw['content']
            
            return None
    except Exception:
        return None  # Never crash on image extraction failure
```

### 4.2 Phase 4 Test

```python
import asyncio
from orchestrator.extractor.og_image import extract_og_image

urls = [
    "https://techcrunch.com/2024/01/01/example/",
    "https://www.theverge.com/example",
    "https://this-url-will-timeout.fake/",
]

async def test():
    for url in urls:
        img = await extract_og_image(url)
        print(f"URL: {url[:50]}... → Image: {img[:60] if img else 'None'}")

asyncio.run(test())
```

**Phase 4 done when:** Returns valid HTTPS URL for real articles, returns None for failures, never raises exception.

---

## Phase 5: LLM Fallback Chain

**Goal:** Generate structured SummaryResult from any article. Never fail silently.

### 5.1 Create `orchestrator/models/summary.py`

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class SummaryResult:
    headline: str
    paragraph_1: str
    paragraph_2: str
    paragraph_3: str
    point_1: str
    point_2: str
    point_3: str
    point_4: Optional[str]
    point_5: str
    conclusion: str
    llm_provider: str
    used_raw_fallback: bool = False
```

### 5.2 Create `orchestrator/llm/prompt.py`

Store the system prompt template from Document 4, Section 5.

### 5.3 Create Each Provider

Each provider implements:
```python
async def summarize(title: str, content: str) -> SummaryResult:
    # Call API
    # Parse response using parse_llm_response()
    # Return SummaryResult
    # Raise exception on any failure — do NOT return None
```

**Groq provider:** Use `openai` library, base URL `https://api.groq.com/openai/v1`, model `llama-3.3-70b-versatile`

**Mistral provider:** Use `mistralai` library, model `mistral-small-latest`

**OpenRouter provider:** Use `openai` library, base URL `https://openrouter.ai/api/v1`, with `HTTP-Referer` and `X-Title` headers

**Gemini provider:** Use `google-generativeai` library, model `gemini-1.5-flash`

### 5.4 Create `orchestrator/llm/summarizer.py`

```python
from orchestrator.llm.groq_provider import GroqProvider
from orchestrator.llm.mistral_provider import MistralProvider
from orchestrator.llm.openrouter_provider import OpenRouterProvider
from orchestrator.llm.gemini_provider import GeminiProvider
from orchestrator.llm.raw_fallback import build_raw_summary

async def summarize_with_fallback(article, config, supabase, run_id: str) -> SummaryResult:
    providers = [
        GroqProvider(config.groq_api_key),
        MistralProvider(config.mistral_api_key),
        OpenRouterProvider(config.openrouter_api_key, model="meta-llama/llama-3.3-70b-instruct:free"),
        OpenRouterProvider(config.openrouter_api_key, model="mistralai/mistral-small-3.2-24b-instruct:free"),
        GeminiProvider(config.gemini_api_key),
    ]
    
    content = article.title + "\n\n" + article.description
    
    for provider in providers:
        try:
            result = await provider.summarize(article.title, content)
            result.llm_provider = provider.name
            print(f"[LLM] Success via {provider.name}")
            return result
        except Exception as e:
            # Log to Supabase error_log
            supabase.table('error_log').insert({
                'component': 'llm',
                'provider': provider.name,
                'error_type': type(e).__name__,
                'error_message': str(e)[:500],
                'article_hash': article.hash,
                'article_url': article.url,
                'run_id': run_id
            }).execute()
            print(f"[LLM] {provider.name} failed: {type(e).__name__}")
            continue
    
    print("[LLM] All providers failed. Using raw fallback.")
    return build_raw_summary(article)
```

### 5.5 Phase 5 Test

```python
# test_llm.py
import asyncio
from orchestrator.models.article import Article
from orchestrator.llm.summarizer import summarize_with_fallback

# Use a real recent article
article = Article(
    title="Anthropic Releases Claude 4 with Extended Context",
    url="https://example.com/test",
    description="Anthropic today announced Claude 4...",
    published_at=datetime.now(timezone.utc),
    source="test"
)

async def test():
    result = await summarize_with_fallback(article, config, supabase, "test-run")
    print(f"Provider: {result.llm_provider}")
    print(f"Headline: {result.headline}")
    print(f"P1: {result.paragraph_1[:100]}...")

asyncio.run(test())
```

Then test fallback by providing invalid API keys — verify raw fallback activates.

**Phase 5 done when:** All 5 providers tested individually, fallback chain verified, raw fallback confirmed.

---

## Phase 6: Message Formatter + Payload Writer

**Goal:** Build the locked template string, write payload file, set GitHub Actions output.

### 6.1 Create `orchestrator/formatter/message.py`

Implement `build_message(summary: SummaryResult) -> str` and `build_fallback_message(article) -> str` from Document 4, Section 7.

Include `validate_message(message: str) -> str` that runs all quality checks from Document 4, Section 8.

### 6.2 Create `orchestrator/main.py` (partial — up to payload write)

At this point, wire together all phases:

```python
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

async def main():
    run_id = str(uuid.uuid4())[:8]
    print(f"[RUN {run_id}] Starting pipeline")
    
    # Phase 1: Config + DB
    config = load_config()
    supabase = create_client(config.supabase_url, config.supabase_key)
    
    # Phase 3: Daily cap check
    posts_today = get_posts_today(supabase)
    if posts_today >= config.max_posts_per_day:
        print(f"[CAP] Daily cap reached ({posts_today}/5). Exiting.")
        set_gh_output('has_article', 'false')
        return
    
    # Phase 2: Fetch
    articles = await fetch_all(supabase)
    
    # Phase 3: Filter + Dedup
    candidates = filter_and_dedup(articles, supabase, config)
    
    if not candidates:
        print("[DONE] No new unique articles this run.")
        set_gh_output('has_article', 'false')
        return
    
    # Process first candidate
    article = candidates[0]
    
    # Phase 4: OG image
    article.og_image_url = await extract_og_image(article.url)
    
    # Phase 5: LLM summarize
    summary = await summarize_with_fallback(article, config, supabase, run_id)
    
    # Phase 6: Format
    message = build_message(summary)
    message = validate_message(message)
    
    # Write payload
    payload = {
        'article_hash': article.hash,
        'formatted_message': message,
        'og_image_url': article.og_image_url,
        'has_image': article.og_image_url is not None
    }
    
    payload_path = '/tmp/article_payload.json'
    with open(payload_path, 'w') as f:
        json.dump(payload, f)
    
    # Insert to DB as PENDING
    supabase.table('articles').upsert({
        'hash': article.hash,
        'title': article.title,
        'url': article.url,
        'source': article.source,
        'status': 'PENDING',
        'llm_provider': summary.llm_provider,
        'had_image': payload['has_image']
    }).execute()
    
    # Signal Node.js step
    set_gh_output('has_article', 'true')
    set_gh_output('payload_path', payload_path)
    print(f"[DONE] Article ready: {article.title[:60]}")

def set_gh_output(key: str, value: str):
    gh_output = os.environ.get('GITHUB_OUTPUT')
    if gh_output:
        with open(gh_output, 'a') as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"[OUTPUT] {key}={value}")  # Local dev fallback

if __name__ == '__main__':
    asyncio.run(main())
```

### 6.3 Phase 6 Test

Run `python orchestrator/main.py` locally. Verify:
- `/tmp/article_payload.json` created with valid content
- `articles` table in Supabase has new PENDING row
- Output printed: `has_article=true`

**Phase 6 done when:** Payload file contains correct formatted message, DB row inserted.

---

## Phase 7: GitHub Actions Workflow (Python Side)

**Goal:** Python pipeline runs correctly in GitHub Actions environment.

### 7.1 Create `.github/workflows/newsbot.yml`

Use the workflow from TRD Document 2, Section 3.1.

**Important:** For now, the `run: node sender.js` step should be:
```yaml
- name: Run Baileys Sender (PLACEHOLDER — Phase 9)
  if: steps.orchestrator.outputs.has_article == 'true'
  run: echo "Baileys sender not yet implemented"
```

### 7.2 Push to GitHub

```bash
git add .
git commit -m "feat: python pipeline complete (phases 1-6)"
git push origin main
```

### 7.3 Trigger Manual Run

GitHub repo → Actions tab → AI News Bot → Run workflow

### 7.4 Phase 7 Test

Check Actions run log. Verify:
- All dependencies install cleanly
- Python pipeline runs without error
- `has_article` output set correctly
- Check Supabase `articles` table for new row

**Phase 7 done when:** GitHub Actions run completes successfully end-to-end for Python side.

---

## Phase 8: Baileys WhatsApp Session Setup (First-Time QR Scan)

**Goal:** Pair your WhatsApp number, extract Channel JID, persist session to Supabase.

**This phase requires physical access to your phone.**

### 8.1 Create `baileys-sender/package.json`

Use dependency list from TRD Document 2, Section 8.2.

```bash
cd baileys-sender
npm install
```

### 8.2 Create `baileys-sender/auth/supabaseAuthState.js`

Use implementation from Document 5, Section 5.1.

### 8.3 Create `baileys-sender/setup/first-time-setup.js`

A one-time script that:
1. Connects Baileys and shows QR code in terminal
2. On successful connection, lists all newsletter JIDs the account is admin of
3. Saves session to Supabase
4. Exits

```javascript
// first-time-setup.js
import makeWASocket, { DisconnectReason } from '@whiskeysockets/baileys'
import { createClient } from '@supabase/supabase-js'
import { useSupabaseAuthState } from '../auth/supabaseAuthState.js'
import qrcode from 'qrcode-terminal'
import dotenv from 'dotenv'

dotenv.config()

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_KEY
)

const { state, saveCreds } = await useSupabaseAuthState(supabase)

const sock = makeWASocket({
  auth: state,
  printQRInTerminal: true,
  browser: ['NewsBot', 'Chrome', '120.0.0.0']
})

sock.ev.on('creds.update', saveCreds)

sock.ev.on('connection.update', async ({ connection, qr, lastDisconnect }) => {
  if (qr) {
    console.log('\n=== SCAN THIS QR CODE WITH YOUR WHATSAPP ===\n')
  }
  
  if (connection === 'open') {
    console.log('\n✅ Connected successfully!\n')
    
    // List all newsletters (channels) this account manages
    try {
      const channels = await sock.getNewsletterInfo()
      console.log('\n=== YOUR WHATSAPP CHANNELS ===')
      if (channels && channels.length > 0) {
        channels.forEach(ch => {
          console.log(`Name: ${ch.name}`)
          console.log(`JID: ${ch.id}`)
          console.log('---')
        })
        console.log('\nCopy your channel JID and add it to GitHub Secrets as WHATSAPP_CHANNEL_JID')
      } else {
        console.log('No channels found. Create a WhatsApp Channel first.')
        console.log('Or find your channel JID manually via WhatsApp → Channel → Link → copy the ID')
      }
    } catch (e) {
      console.log('Could not auto-list channels:', e.message)
      console.log('Find your channel JID in WhatsApp app settings.')
    }
    
    await saveCreds()
    console.log('\n✅ Session saved to Supabase successfully.')
    console.log('You can now close this script.')
    process.exit(0)
  }
})
```

### 8.4 Run First-Time Setup

```bash
cd baileys-sender
# Create local .env with SUPABASE_URL + SUPABASE_KEY
node setup/first-time-setup.js
```

1. QR code appears in terminal
2. Open WhatsApp on your phone → Settings → Linked Devices → Link a device
3. Scan QR code
4. Wait for "Connected successfully!"
5. Copy the Channel JID printed (format: `120363xxxxxxxxxx@newsletter`)
6. Add to GitHub Actions Secrets as `WHATSAPP_CHANNEL_JID`
7. Verify `whatsapp_auth` table in Supabase has rows

**Phase 8 done when:** Session rows exist in Supabase `whatsapp_auth` table, Channel JID confirmed.

---

## Phase 9: Baileys Sender (Node.js)

**Goal:** Read payload from Python, send to WhatsApp Channel, update Supabase.

### 9.1 Create `baileys-sender/utils/antiBan.js`

```javascript
export const sleep = (ms) => new Promise(r => setTimeout(r, ms))
export const randomInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min

export async function humanDelay() {
  const delay = randomInt(5000, 15000)
  console.log(`[ANTI-BAN] Waiting ${delay}ms before send...`)
  await sleep(delay)
}

export async function simulateComposing(sock, jid) {
  await sock.sendPresenceUpdate('composing', jid)
  await sleep(randomInt(2000, 4000))
  await sock.sendPresenceUpdate('paused', jid)
  await sleep(randomInt(500, 1500))
}

const BROWSERS = [
  ['Chrome', '120.0.0.0'],
  ['Chrome', '121.0.0.0'],
  ['Chrome', '122.0.0.0'],
]

export function getRandomBrowser() {
  return BROWSERS[randomInt(0, BROWSERS.length - 1)]
}
```

### 9.2 Create `baileys-sender/sender.js`

Full implementation:

```javascript
import makeWASocket, { DisconnectReason, delay } from '@whiskeysockets/baileys'
import { createClient } from '@supabase/supabase-js'
import { useSupabaseAuthState } from './auth/supabaseAuthState.js'
import { humanDelay, simulateComposing, getRandomBrowser } from './utils/antiBan.js'
import { readFileSync } from 'fs'
import pino from 'pino'

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_KEY
)

// Load payload from Python
const payloadPath = process.env.ARTICLE_PAYLOAD_PATH || '/tmp/article_payload.json'
const payload = JSON.parse(readFileSync(payloadPath, 'utf8'))
const channelJid = process.env.WHATSAPP_CHANNEL_JID

console.log(`[BAILEYS] Loading session from Supabase...`)
const { state, saveCreds } = await useSupabaseAuthState(supabase)

const browser = getRandomBrowser()
const sock = makeWASocket({
  auth: state,
  logger: pino({ level: 'silent' }),
  browser: ['NewsBot', browser[0], browser[1]],
  generateHighQualityLinkPreview: false,
  connectTimeoutMs: 30000
})

sock.ev.on('creds.update', saveCreds)

let sent = false

sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
  if (qr) {
    console.error('[ERROR] Session expired — QR code required. Manual re-pair needed.')
    process.exit(1)
  }

  if (connection === 'open' && !sent) {
    sent = true
    console.log('[BAILEYS] Connected. Executing anti-ban sequence...')
    
    try {
      // Anti-ban: human delay
      await humanDelay()
      
      // Anti-ban: composing simulation
      await simulateComposing(sock, channelJid)
      
      // Send the message
      let msgResult
      if (payload.has_image && payload.og_image_url) {
        console.log('[SEND] Sending image + caption...')
        msgResult = await sock.sendMessage(channelJid, {
          image: { url: payload.og_image_url },
          caption: payload.formatted_message
        })
      } else {
        console.log('[SEND] Sending text only (no image)...')
        msgResult = await sock.sendMessage(channelJid, {
          text: payload.formatted_message
        })
      }
      
      const msgId = msgResult?.key?.id || null
      console.log(`[SEND] Success. Message ID: ${msgId}`)
      
      // Update Supabase
      await supabase.from('articles').update({
        status: 'POSTED',
        posted_at: new Date().toISOString()
      }).eq('hash', payload.article_hash)
      
      await supabase.from('post_log').insert({
        article_hash: payload.article_hash,
        status: 'success',
        whatsapp_msg_id: msgId,
        had_image: payload.has_image
      })
      
      // Save session state
      await saveCreds()
      console.log('[BAILEYS] Session saved. Exiting.')
      process.exit(0)
      
    } catch (err) {
      console.error('[ERROR] Send failed:', err.message)
      
      // Log to Supabase
      await supabase.from('error_log').insert({
        component: 'whatsapp',
        provider: 'baileys',
        error_type: err.constructor.name,
        error_message: err.message,
        article_hash: payload.article_hash
      })
      
      await supabase.from('articles').update({ status: 'FAILED' })
        .eq('hash', payload.article_hash)
      
      process.exit(1)
    }
  }

  if (connection === 'close') {
    const code = lastDisconnect?.error?.output?.statusCode
    if (code !== DisconnectReason.loggedOut) {
      console.log('[BAILEYS] Reconnecting...')
      // Brief reconnect attempt - if this fails, process exits via timeout
    } else {
      console.error('[ERROR] Logged out. Session invalid.')
      process.exit(1)
    }
  }
})

// Safety timeout: if nothing happens in 60s, exit
setTimeout(() => {
  console.error('[TIMEOUT] Baileys did not connect within 60 seconds.')
  process.exit(1)
}, 60000)
```

### 9.3 Phase 9 Test

Manually create a test payload:
```bash
echo '{"article_hash":"test123","formatted_message":"📰 *TEST POST FROM BOT*\n\n📋 *Summary:*\nThis is a test post.\n\n*💡 Conclusion:*\nBot is working.","og_image_url":null,"has_image":false}' > /tmp/article_payload.json

SUPABASE_URL=xxx SUPABASE_KEY=xxx WHATSAPP_CHANNEL_JID=xxx ARTICLE_PAYLOAD_PATH=/tmp/article_payload.json node baileys-sender/sender.js
```

Check WhatsApp Channel on your phone — test message should appear.

**Phase 9 done when:** Test message delivered to Channel, Supabase `post_log` has success row.

---

## Phase 10: End-to-End Integration

**Goal:** Full pipeline runs in GitHub Actions, real article posted to Channel.

### 10.1 Update GitHub Actions Workflow

Replace placeholder Baileys step with real implementation:

```yaml
- name: Run Baileys Sender
  if: steps.orchestrator.outputs.has_article == 'true'
  working-directory: baileys-sender
  env:
    SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
    SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
    WHATSAPP_CHANNEL_JID: ${{ secrets.WHATSAPP_CHANNEL_JID }}
    ARTICLE_PAYLOAD_PATH: ${{ steps.orchestrator.outputs.payload_path }}
  run: node sender.js
  timeout-minutes: 3
```

### 10.2 Trigger Full Test Run

Manually trigger Actions → verify in Channel within 5 minutes.

### 10.3 Monitor First 48 Hours

Check every 6 hours:
- Actions runs succeeding (green checkmarks)
- Posts appearing in WhatsApp Channel
- Supabase `post_log` accumulating success rows
- No ban or session expiry

**Phase 10 done when:** 5 consecutive posts delivered across different runs, zero duplicates, all from GitHub Actions.

---

## Phase 11: Production Hardening

**Goal:** System is production-grade, monitoring queries saved, edge cases handled.

### 11.1 Verify GitHub Actions Minute Budget

After 1 week, check: GitHub → Billing → Actions usage.
If approaching 2,000 min/month:
- Change cron from `*/30 * * * *` to `0 */1 * * *` (hourly)
- This halves usage to ~720 min/month

### 11.2 Save Monitoring Queries in Supabase Dashboard

Save all queries from TRD Document 2, Section 10 as named queries in Supabase SQL Editor for quick access.

### 11.3 Verify WhatsApp Token / Session Health

Create a simple Node.js script that runs weekly (separate workflow):
- Connects to WA via saved session
- Sends "session health check" log to Supabase (not to Channel)
- Disconnects
- This keeps the session alive and detects expiry before it becomes a problem

### 11.4 Final Checklist

Before declaring production-ready:

- [ ] All 7 GitHub Secrets set correctly
- [ ] Supabase tables verified with correct schema
- [ ] Session persists across 3 simulated restarts (delete runner manually, verify session reloads)
- [ ] Daily cap enforced: post 5 articles, verify run #6 skips
- [ ] Duplicate check: same article URL fetched twice → second attempt filtered
- [ ] Title similarity: two articles about same event → second filtered
- [ ] All LLM providers tested individually
- [ ] Raw fallback tested (mock all providers to fail)
- [ ] OG image failure handled: set `og_image_url=null` in payload, verify text-only post sends
- [ ] GitHub Actions cron confirmed active (check next scheduled run in Actions UI)

---

## Appendix: Common Failure Scenarios & Recovery

| Scenario | Symptom | Fix |
|----------|---------|-----|
| WhatsApp session expired | Actions step exits 1 with "QR code required" | Run `first-time-setup.js` locally, re-scan QR, new session saved to Supabase |
| All LLMs rate-limited simultaneously | Posts using raw RSS fallback | Normal behavior — will resolve within 1 hour |
| Supabase project paused (free tier inactivity) | Actions fails on DB connection | Log into Supabase dashboard → restore project (takes 30 seconds) |
| GitHub Actions minutes exhausted | Cron jobs don't run | Change cron to `0 */2 * * *` (every 2 hours) to halve usage |
| RSS source permanently gone | Source always returns 0 articles | Remove from `fetch_all_rss()` sources list |
| WhatsApp number banned | Baileys gets 403/unauthorized | Use different SIM/number, re-scan QR |

---
