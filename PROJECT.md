# PROJECT.md — AI News Bot Build Tracker
## WhatsApp Channel Automation | Production Build Log

> **Purpose:** This file is updated at the end of every phase so any agent or
> developer can open it and immediately understand: what's built, what's tested,
> what's pending, and any known issues.
> 
> **Update rule:** After each phase completes, update Phase Status, Files
> section, Test Results, and Known Issues.

---

## 🗂 Project Overview

| Field | Value |
|-------|-------|
| **Repo** | `MUHAMMAD-FAHAD-AMJAD/AI-NEWS-AUTOMATION` |
| **Supabase Project ID** | `aqrdhxcrhwvcuasqinis` |
| **Supabase Region** | `ap-northeast-2` (Seoul) |
| **Supabase URL** | `https://aqrdhxcrhwvcuasqinis.supabase.co` |
| **WhatsApp Channel** | `https://whatsapp.com/channel/0029Vb7saIyBfxo16VOMZj3x` |
| **WhatsApp JID** | ⚠️ `PLACEHOLDER_FILL_IN_PHASE_8` |
| **GitHub Actions cron** | `*/30 * * * *` (every 30 min) |
| **Daily post cap** | 5 posts per 24-hour window |

---

## 📋 Phase Status

| Phase | Description | Status | Tests |
|-------|-------------|--------|-------|
| **Phase 1** | Scaffold + Secrets + Supabase | ✅ COMPLETE | ✅ Config tests passing |
| **Phase 2** | RSS Fetcher + Normalizer | ✅ COMPLETE | ✅ 33/33 tests passing (21 unit + 12 integration) |
| **Phase 3** | Filter Engine + Deduplication | ✅ COMPLETE | ✅ 38/38 unit tests passing |
| **Phase 4** | OG Image Extractor | ✅ COMPLETE | ✅ 19/19 tests passing (16 unit + 3 integration) |
| **Phase 5** | LLM Fallback Chain | ✅ COMPLETE | ✅ 33/33 unit tests passing |
| **Phase 6** | Message Formatter + Payload Writer | ✅ COMPLETE | ✅ 33/33 unit tests passing |
| **Phase 7** | GitHub Actions Workflow | ✅ COMPLETE | ✅ 2 workflow files created |
| **Phase 8** | Baileys WhatsApp Session Setup | ⏳ PENDING | — |
| **Phase 9** | Baileys Sender + Supabase Auth State | ⏳ PENDING | — |
| **Phase 10** | End-to-End Integration + Anti-Ban | ⏳ PENDING | — |
| **Phase 11** | Production Hardening + Monitoring | ⏳ PENDING | — |

---

## 📁 Files Created Per Phase

### Phase 1 — Scaffold + Secrets + Supabase ✅

| File | Purpose | Status |
|------|---------|--------|
| `orchestrator/__init__.py` | Package init | ✅ |
| `orchestrator/config.py` | Env var loading + validation | ✅ |
| `requirements.txt` | Pinned Python deps | ✅ |
| `.gitignore` | Exclude secrets + artifacts | ✅ |
| `.env.example` | Template for local dev | ✅ |
| `README.md` | Architecture overview | ✅ |
| Supabase tables | `articles`, `post_log`, `whatsapp_auth`, `error_log` | ✅ |
| GitHub Secrets | All 7 secrets set as Repository Secrets | ✅ |

**Phase 1 test result:**
```
✅ ConfigError raised when vars missing
✅ Config loads correctly with vars present
✅ __repr__ hides secret values
```

---

### Phase 2 — RSS Fetcher + Normalizer ✅

| File | Purpose | Status |
|------|---------|--------|
| `orchestrator/models/article.py` | Article dataclass with validation + MD5 hash | ✅ |
| `orchestrator/models/__init__.py` | Models package init | ✅ |
| `orchestrator/fetcher/rss.py` | 8-feed concurrent RSS fetcher | ✅ |
| `orchestrator/fetcher/hackernews.py` | HN Algolia API fetcher | ✅ |
| `orchestrator/fetcher/reddit.py` | Reddit r/artificial JSON fetcher | ✅ |
| `orchestrator/fetcher/__init__.py` | `fetch_all()` combined entry point | ✅ |
| `orchestrator/tests/__init__.py` | Tests package init | ✅ |
| `orchestrator/tests/test_fetcher.py` | Full test suite (unit + integration) | ✅ |
| `pytest.ini` | Pytest config with asyncio + markers | ✅ |
| `conftest.py` | Root conftest for sys.path setup | ✅ |
| `requirements.txt` | Added `pytest==8.2.2`, `pytest-asyncio==0.23.7` | ✅ |

**RSS Sources configured:**

| Source Slug | Feed URL |
|-------------|----------|
| `techcrunch` | `https://techcrunch.com/category/artificial-intelligence/feed/` |
| `theverge` | `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml` |
| `venturebeat` | `https://venturebeat.com/category/ai/feed/` |
| `mittr` | `https://www.technologyreview.com/feed/` |
| `wired` | `https://www.wired.com/feed/tag/ai/latest/rss` |
| `huggingface` | `https://huggingface.co/blog/feed.xml` |
| `googleai` | `https://blog.google/technology/ai/rss/` |
| `openai` | `https://openai.com/blog/rss.xml` |

**Phase 2 test command:**
```bash
python -m pytest orchestrator/tests/test_fetcher.py -v
# For unit tests only (no network):
python -m pytest orchestrator/tests/test_fetcher.py -v -m "not integration"
# For integration tests (needs internet):
python -m pytest orchestrator/tests/test_fetcher.py -v -m integration
```

**Phase 2 test results:** 🔄 AWAITING USER CONFIRMATION

---

### Phase 3 — Filter Engine + Deduplication ✅

| File | Purpose | Status |
|------|---------|--------|
| `orchestrator/filter/recency.py` | 24h recency filter with partition helper | ✅ |
| `orchestrator/filter/keywords.py` | Include/exclude keyword filter + debug helper | ✅ |
| `orchestrator/filter/__init__.py` | `apply_filters()` combined entry point | ✅ |
| `orchestrator/dedup/hash.py` | Layer 1: URL hash Supabase lookup | ✅ |
| `orchestrator/dedup/similarity.py` | Layer 2: SequenceMatcher title dedup (batch) | ✅ |
| `orchestrator/dedup/__init__.py` | `run_deduplication()` combined entry point | ✅ |
| `orchestrator/tests/test_filter.py` | 38 unit tests — all passing | ✅ |

**Phase 3 test results:**
```
✅ 38/38 unit tests passed
   - 7 recency filter tests
   - 12 keyword filter tests
   - 4 dedup Layer 1 (hash) tests
   - 9 dedup Layer 2 (similarity) tests
   - 3 combined dedup pipeline tests
   - 4 apply_filters() integration tests
```

---

### Phase 4 — OG Image Extractor ✅

| File | Purpose | Status |
|------|---------|--------|
| `orchestrator/extractor/og_image.py` | Async httpx fetcher, og:image → twitter:image → twitter:image:src | ✅ |
| `orchestrator/extractor/__init__.py` | Extractor package init | ✅ |
| `orchestrator/tests/test_extractor.py` | 19 tests (16 unit + 3 integration) — all passing | ✅ |

**Phase 4 test results:**
```
✅ 16/16 unit tests passed (all mocked — no network)
   - og:image returned when present
   - twitter:image fallback when og:image absent
   - twitter:image:src fallback (third priority)
   - og:image preferred over twitter:image
   - Returns None on HTTP 404, 500, timeout, connection error
   - Returns None when no image tags found
   - Returns None for relative URLs (no http prefix)
   - Returns None for empty content attribute
   - Non-http og:image falls through to twitter:image
   - Never raises on generic exception
   - SECURITY: Article URL not logged in error output ✅

✅ 3/3 integration tests passed
   - TechCrunch returned real og:image: https://techcrunch.com/wp-content/uploads/...
   - Fake URL returned None (ConnectError handled gracefully)
   - VentureBeat returned None (DNS blocked, handled gracefully)
```

---

### Phase 5 — LLM Fallback Chain ✅

| File | Purpose | Status |
|------|---------|--------|
| `orchestrator/models/summary.py` | SummaryResult dataclass (10 content fields + provider + raw flag) | ✅ |
| `orchestrator/llm/parser.py` | Exact parser from §6 spec: labeled field accumulation, HEADLINE required | ✅ |
| `orchestrator/llm/prompt.py` | SYSTEM_PROMPT (locked) + build_user_prompt() | ✅ |
| `orchestrator/llm/groq_provider.py` | Groq: llama-3.3-70b-versatile, temp=0.4, timeout=30 | ✅ |
| `orchestrator/llm/mistral_provider.py` | Mistral: mistral-small-latest, SDK async client | ✅ |
| `orchestrator/llm/openrouter_provider.py` | OpenRouter: llama-3.3-70b:free → mistral-small-3.2:free | ✅ |
| `orchestrator/llm/gemini_provider.py` | Gemini: gemini-1.5-flash, asyncio.to_thread for sync SDK | ✅ |
| `orchestrator/llm/raw_fallback.py` | Raw: always succeeds, 800-char truncation at sentence boundary | ✅ |
| `orchestrator/llm/summarizer.py` | Fallback chain: Groq→Mistral→OpenRouter→Gemini→Raw, 2s delay | ✅ |
| `orchestrator/llm/__init__.py` | Exports summarize_with_fallback only | ✅ |
| `orchestrator/tests/test_llm.py` | 33 unit tests (13 parser + 13 raw fallback + 6 summarizer + 1 integration) | ✅ |

**Phase 5 test results:**
```
✅ 33/33 unit tests passed (all mocked — no real API calls)
   - 13 parser tests: field parsing, uppercase, multi-line, N/A→None, security
   - 13 raw fallback tests: HTML strip, 800-char truncation, edge cases
   - 6 summarizer tests: chain order, 2s delay, never-raises contract
   - 1 integration test (Groq real API call, marked @integration)

📊 Cumulative unit tests across all phases: 108/108 ✅
```

---

### Phase 6 — Message Formatter + Payload Writer ✅

| File | Purpose | Status |
|------|---------|--------|
| `orchestrator/formatter/message.py` | `build_message()`, `build_fallback_message()`, `validate_message()` from spec §7+§8 | ✅ |
| `orchestrator/formatter/__init__.py` | Formatter package init | ✅ |
| `orchestrator/main.py` | Full pipeline entry point — all phases wired together | ✅ |
| `orchestrator/tests/test_formatter.py` | 33 unit tests — all passing | ✅ |

**Phase 6 test results:**
```
✅ 33/33 unit tests passed
   - 15 build_message() tests: template structure, bullets, 4096 cap, truncation
   - 7  build_fallback_message() tests: HTML strip, 800-char truncation
   - 12 validate_message() tests: all 7 quality checks (URL, hashtag, source, headline, conclusion)

📊 Cumulative unit tests across all phases: 141/141 ✅
```

---

### Phase 7 — GitHub Actions Workflow ✅

| File | Purpose | Status |
|------|---------|--------|
| `.github/workflows/newsbot.yml` | Main pipeline: hourly cron, Python → Node.js conditional chain | ✅ |
| `.github/workflows/health-check.yml` | Weekly Monday 9AM UTC session warm-up + error_log | ✅ |

**Cron schedule decisions:**
```
newsbot.yml:      0 * * * *     # Hourly — 24 runs/day × ~2 min = 720 min/month ✅
health-check.yml: 0 9 * * 1    # Weekly Monday 9AM UTC — keeps WA session alive

Rejected: */30 (every 30 min) = 48 runs/day × ~2 min = ~2,880 min/month
         EXCEEDS 2,000 min/month free tier
```

**newsbot.yml design decisions:**
- `environment: production` — secrets scoped to production environment
- `concurrency: newsbot-pipeline` — prevents overlapping runs
- `cancel-in-progress: false` — never cancel a mid-run post
- Node.js steps 5-7 are conditional: `if: steps.orchestrator.outputs.has_article == 'true'`
- Baileys connects at most 5×/day (daily cap) not 24×/day — primary anti-ban mechanism
- Explicit `timeout-minutes` on every single step
- All secrets via `${{ secrets.NAME }}` — never hardcoded
- `PAYLOAD_PATH: /tmp/article_payload.json` injected to orchestrator
- `ARTICLE_PAYLOAD_PATH` passed from orchestrator output to sender

**health-check.yml design decisions:**
- Runs Node.js health-check.js — verifies Baileys session without posting
- Always logs result (success or fail) to Supabase `error_log` table via inline Python
- `if: always()` on logging step so failures are captured toosApp Session Setup ⏳ PENDING

Files to build:
- `baileys-sender/first-time-setup.js` — QR scan, JID extraction
- `baileys-sender/package.json`

---

### Phase 8 — Baileys WhatsApp Session Setup ⏳ PENDING

Files to build:
- `baileys-sender/first-time-setup.js` — QR scan, JID extraction
- `baileys-sender/package.json`

**Blocker:** `WHATSAPP_CHANNEL_JID` must be filled in GitHub Secrets after
running `first-time-setup.js` and scanning QR code.

---

### Phase 9 — Baileys Sender + Supabase Auth State ⏳ PENDING

Files to build:
- `baileys-sender/sender.js`
- `baileys-sender/auth/supabaseAuthState.js`
- `baileys-sender/utils/antiBan.js`

---

### Phase 10 — End-to-End Integration ⏳ PENDING

- Wire all phases together in `orchestrator/main.py`
- `orchestrator/db.py` — Supabase client + all DB operations
- Full pipeline test run

---

### Phase 11 — Production Hardening ⏳ PENDING

- Error recovery testing
- Monitoring queries validation
- Final GitHub Actions secrets verification

---

## ⚙️ Architecture Quick Reference

```
GitHub Actions cron (0 * * * *) ← CHANGED from */30 to hourly in Phase 7
        │
        ▼
orchestrator/main.py
  ├── config.py         → Load + validate 7 env vars
  ├── db.py             → Supabase client
  ├── fetcher/          → 8 RSS + HN + Reddit → List[Article]
  ├── filter/           → Recency (24h) + Keywords
  ├── dedup/            → Layer1 (URL hash) + Layer2 (title similarity)
  ├── extractor/        → og:image URL
  ├── llm/              → Groq → Mistral → OpenRouter → Gemini → Raw
  └── formatter/        → Locked WhatsApp template → payload.json
        │
        ▼ (only if has_article=true)
baileys-sender/sender.js
  ├── supabaseAuthState → Load/save WA session from Supabase
  ├── antiBan.js        → Random delays, composing simulation
  └── WhatsApp Channel  → image+caption OR text-only post
```

---

## 🔐 Secrets Checklist

| Secret Name | Status | Notes |
|-------------|--------|-------|
| `SUPABASE_URL` | ✅ Set | `https://aqrdhxcrhwvcuasqinis.supabase.co` |
| `SUPABASE_KEY` | ✅ Set | anon/public key |
| `GROQ_API_KEY` | ✅ Set | `gsk_...` |
| `MISTRAL_API_KEY` | ✅ Set | |
| `OPENROUTER_API_KEY` | ✅ Set | |
| `GEMINI_API_KEY` | ✅ Set | |
| `WHATSAPP_CHANNEL_JID` | ⚠️ Placeholder | Fill in Phase 8 after QR scan |

---

## ⚠️ Known Issues / Notes

1. **`WHATSAPP_CHANNEL_JID`** is set to `PLACEHOLDER_FILL_IN_PHASE_8` — this
   must be replaced with the real `120363xxxxxxxxxx@newsletter` JID after
   running Phase 8's `first-time-setup.js` and scanning the QR code.

2. **Gemini API key format** — The provided key starts with `AQ.Ab8RN` rather
   than the typical `AIza` prefix. This may be a Gemini Advanced/Vertex key.
   Will need verification when Phase 5 (LLM chain) is built.

3. **GitHub Actions minutes (FIXED IN PHASE 7)** — Original cron `*/30 * * * *`
   = 48 runs/day × ~2 min = **~2,880 min/month** which exceeds the 2,000 min
   free tier limit. **Resolution:** Phase 7 workflow will use `0 * * * *`
   (hourly) = 24 runs/day × ~2 min = **~720 min/month** — well within free tier.
   At 5 posts/day cap, hourly is more than sufficient.

4. **feedparser timeout** — feedparser has no native `timeout` parameter.
   Timeout is handled by the OS via `socket.setdefaulttimeout()`. Current
   implementation uses per-request Connection:close header to avoid hangs.
   Consider adding `import socket; socket.setdefaulttimeout(15)` in main.py
   if hangs are observed.

---

## 📅 Build Log

| Date | Phase | Action |
|------|-------|--------|
| 2026-06-14 | Phase 1 | Project scaffold created, config.py built, Supabase tables created |
| 2026-06-14 | Phase 1 | GitHub Secrets added as Repository Secrets (7 secrets) |
| 2026-06-15 | Phase 2 | article.py, rss.py, hackernews.py, reddit.py, fetcher/__init__.py created |
| 2026-06-15 | Phase 2 | test_fetcher.py created — 33/33 tests pass (21 unit + 12 integration) |
| 2026-06-15 | Phase 3 | recency.py, keywords.py, hash.py, similarity.py + __init__.py files created |
| 2026-06-15 | Phase 3 | test_filter.py created — 38/38 unit tests pass |
| 2026-06-15 | Phase 4 | og_image.py, extractor/__init__.py, test_extractor.py created |
| 2026-06-15 | Phase 4 | 19/19 tests pass (16 unit + 3 integration). TechCrunch og:image confirmed |
| 2026-06-15 | Phase 5 | summary.py, parser.py, prompt.py, all 4 LLM providers, raw_fallback.py, summarizer.py created |
| 2026-06-15 | Phase 6 | message.py (build + validate), formatter/__init__.py, main.py created |
| 2026-06-15 | Phase 7 | newsbot.yml (hourly cron, Python+Node, 7 secrets) created |
| 2026-06-15 | Phase 7 | health-check.yml (weekly Monday, session warm-up + error_log) created |
| 2026-06-15 | Phase 7 FIX | GitHub Actions run #1 failed — 3 issues found and fixed: |
| 2026-06-15 | Phase 7 FIX | (1) supabase==2.4.0 required httpx<0.26 → upgraded to supabase>=2.7 (resolves to 2.16.0) |
| 2026-06-15 | Phase 7 FIX | (2) python-dateutil==2.9.0 rejected by mistralai 1.0.0 → loosened to >=2.9.0.post0 |
| 2026-06-15 | Phase 7 FIX | (3) Action versions updated to Node24: checkout@v4.2.2, setup-python@v5.3.0, setup-node@v4.1.0 |
| 2026-06-15 | Phase 7 FIX | (4) Removed environment:production — was blocking secret injection (secrets are repo-level) |
| 2026-06-15 | Phase 7 FIX | (5) Added FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true to suppress Node20 deprecation warning |
| 2026-06-15 | Phase 7 FIX | Commit 5b5df13 pushed — triggering manual workflow_dispatch run #2 |
| 2026-06-15 | Phase 7 FIX | Run #2: PYTHONPATH missing — ModuleNotFoundError for orchestrator package |
| 2026-06-15 | Phase 7 FIX | Added PYTHONPATH=${{ github.workspace }} to orchestrator step (commit 424790d) |
| 2026-06-15 | Phase 7 FIX | Run #3: Python ✅ — Node.js setup failed: baileys-sender/package-lock.json missing |
| 2026-06-15 | Phase 7 FIX | Removed npm cache from setup-node (package-lock.json not created until Phase 9) |
| 2026-06-15 | Phase 7 FIX | Run #4: Python ✅, article fetched — npm ci failed: baileys-sender/ dir not found |
| 2026-06-15 | Phase 7 FIX | Added hashFiles('baileys-sender/package.json') guard to steps 5+6+7 (commit 7c1a712) |
| 2026-06-15 | Phase 7 ✅  | Run #5: FULLY GREEN — pipeline fetched article, Groq summarized, payload.json written |
| 2026-06-15 | Bug Fix     | similarity.py: raw SQL '48 hours' → Python datetime.now(utc) - timedelta(hours=48) |
| 2026-06-15 | Bug Fix     | main.py insert: removed published_at + formatted_message (columns not in schema) |
| 2026-06-15 | Bug Fix     | 141/141 unit tests still passing after both fixes (commit b72b538) |

| 2026-06-15 | Phase 9 ✅  | antiBan.js created — humanDelay, simulateComposing, getRandomBrowser |
| 2026-06-15 | Phase 9 ✅  | sender.js created — loads session from Supabase, sends to channel, updates post_log |
| 2026-06-15 | Phase 9 FIX | lid-mapping keys filtered from supabaseAuthState — stopped Supabase flood |
| 2026-06-15 | Phase 9 FIX | Channel delay reduced to 2-4s (was 10-15s → caused 408 timeout) |
| 2026-06-15 | Phase 9 FIX | Added retry on 408 disconnect (up to 2 retries) |
| 2026-06-15 | Phase 9 ✅  | LOCAL TEST PASSED — "Test post from NewsBot Phase 9" delivered to AI News channel |
| 2026-06-15 | Phase 9 ✅  | Message ID: 3EB031832F7F99F69D30D2 — confirmed in WhatsApp Channel |
| 2026-06-15 | Phase 10    | package-lock.json committed — enables npm ci in GitHub Actions |
| 2026-06-15 | Phase 10    | newsbot.yml updated — npm cache restored, sender timeout increased to 4min |
| 2026-06-15 | Phase 10    | Triggering full end-to-end GitHub Actions run (commit 0e43422) |

---

*Last updated: Phase 9 local test PASSED. Phase 10 workflow pushed — triggering Actions run.*
