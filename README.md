# AI News Bot — WhatsApp Channel Automation

Fully automated WhatsApp Channel news bot. Monitors AI/tech news sources every 30 minutes, generates LLM summaries, and publishes premium-formatted posts automatically.

## Architecture

```
GitHub Actions (cron) → Python Orchestrator → Node.js Baileys → WhatsApp Channel
                                    ↕
                              Supabase PostgreSQL
```

## Tech Stack

- **Scheduler:** GitHub Actions cron (`*/30 * * * *`)
- **News fetching:** feedparser (RSS) + httpx (HN + Reddit APIs)
- **Deduplication:** MD5 URL hash + SequenceMatcher title similarity
- **LLM chain:** Groq → Mistral → OpenRouter (×2) → Gemini → Raw RSS fallback
- **WhatsApp delivery:** Baileys (Node.js)
- **Session storage:** Supabase JSONB
- **Database:** Supabase PostgreSQL (free tier)

## Build Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Project scaffold + secrets + Supabase setup | 🔨 In Progress |
| 2 | RSS fetcher + normalizer | ⏳ Pending |
| 3 | Filter engine + deduplication | ⏳ Pending |
| 4 | OG image extractor | ⏳ Pending |
| 5 | LLM fallback chain | ⏳ Pending |
| 6 | Message formatter + payload writer | ⏳ Pending |
| 7 | GitHub Actions workflow | ⏳ Pending |
| 8 | Baileys first-time QR setup | ⏳ Pending |
| 9 | Baileys sender + Supabase auth state | ⏳ Pending |
| 10 | End-to-end integration | ⏳ Pending |
| 11 | Production hardening | ⏳ Pending |

## Required GitHub Actions Secrets

| Secret | Where to Get |
|--------|-------------|
| `SUPABASE_URL` | Supabase project settings |
| `SUPABASE_KEY` | Supabase project settings → API → anon key |
| `GROQ_API_KEY` | console.groq.com |
| `MISTRAL_API_KEY` | console.mistral.ai |
| `OPENROUTER_API_KEY` | openrouter.ai/keys |
| `GEMINI_API_KEY` | aistudio.google.com |
| `WHATSAPP_CHANNEL_JID` | Extracted in Phase 8 via first-time-setup.js |

## Local Development Setup

```bash
cp .env.example .env
# Fill in all values in .env

pip install -r requirements.txt

# Test config loads
python -c "from orchestrator.config import load_config; c = load_config(); print('Config OK:', repr(c))"
```

## Operating Cost

**$0/month** — GitHub Actions free tier + Supabase free tier + free LLM APIs only.
