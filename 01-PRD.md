# PRD — Product Requirements Document
## AI News Bot | WhatsApp Channel Automation

**Version:** 1.0  
**Status:** Pre-Implementation  
**Last Updated:** June 2026

---

## 1. Product Overview

### 1.1 Product Name
**AI News Bot** — Fully Automated WhatsApp Channel Publishing System

### 1.2 One-Line Definition
A zero-maintenance Python + Node.js pipeline that monitors 10 AI/tech news sources every 30 minutes, filters for significance, generates structured LLM summaries, and publishes premium-formatted posts (image + caption) to a WhatsApp Channel — automatically, indefinitely, at $0/month.

### 1.3 Problem Statement
AI news moves fast and is scattered across dozens of sources. Manually curating, summarizing, and publishing daily updates to a WhatsApp Channel requires 1–2 hours of focused work per day. Existing automation tools either cost money, require always-on servers, or can't deliver to WhatsApp Channels. The target audience — developers, AI practitioners, founders — consumes content on mobile and wants concise, structured, visually clean summaries, not raw links or text walls.

### 1.4 The Opportunity
WhatsApp Channels are massively underserved for AI content compared to Telegram or Twitter. A consistently high-quality, structured AI news feed on WhatsApp can build a loyal subscriber base with zero paid distribution cost. The only input required is the initial build — after deployment, it runs forever.

---

## 2. Goals & Non-Goals

### 2.1 Goals (v1)
- Automatically publish 3–5 high-quality AI/tech news posts per day to a WhatsApp Channel
- Zero manual effort after initial deployment
- Never post duplicate articles — across runs, restarts, and source overlaps
- Survive GitHub Actions container restarts via Supabase session persistence
- Degrade gracefully on every failure point — no silent death, no missed posts
- Stay within $0/month operating cost permanently

### 2.2 Non-Goals (v1 — explicitly excluded)
- Web dashboard or admin UI
- Manual override / on-demand posting trigger
- Subscriber analytics or channel growth tracking
- Multi-channel or multi-platform support (Telegram, Instagram, etc.)
- Paid source ingestion (Bloomberg, Reuters premium)
- Content moderation beyond keyword filtering
- A/B testing message formats
- Reply handling or subscriber interaction

---

## 3. Users

### 3.1 Channel Subscribers (End Consumers)
- Developers, AI researchers, startup founders, tech-curious professionals
- Consume on mobile — WhatsApp is their primary messaging app
- Want dense, structured, readable summaries — not raw links
- Intolerant of spam — 5+ posts/day from a channel = muted
- Trust built through consistency and quality, not volume

### 3.2 Channel Operator (Builder — You)
- Wants 100% hands-off operation after deployment
- Cannot babysit a server — needs true zero-maintenance
- No budget for paid services — hard $0/month constraint
- Needs the system to self-heal on failures without manual intervention

---

## 4. User Stories

| # | Actor | Story | Priority |
|---|-------|-------|----------|
| US-01 | Subscriber | I want structured AI news in a mobile-readable format so I can consume it in under 60 seconds | P0 |
| US-02 | Subscriber | I want max 5 posts/day so I am not spammed and don't mute the channel | P0 |
| US-03 | Subscriber | I want a thumbnail image with each post so the feed looks premium and visual | P1 |
| US-04 | Subscriber | I want the same story to never appear twice, even if covered by multiple sources | P0 |
| US-05 | Operator | I want zero daily manual actions — no logins, no triggers, no monitoring | P0 |
| US-06 | Operator | I want all errors logged so I can audit what failed and why, without babysitting | P1 |
| US-07 | Operator | I want the bot to continue posting even if one LLM provider or RSS source fails | P0 |
| US-08 | Operator | I want the WhatsApp session to survive container restarts without requiring re-pairing | P0 |
| US-09 | Operator | I want the system to never exceed the 5-posts/day cap even across multiple GitHub Actions runs | P0 |
| US-10 | Operator | I want total infrastructure cost to remain $0/month permanently | P0 |

---

## 5. MVP Feature Scope

### 5.1 In Scope — v1
| Feature | Description |
|---------|-------------|
| RSS Polling | Fetch all 8 RSS feeds every 30 minutes via GitHub Actions cron |
| API Aggregation | Fetch from HN Algolia + Reddit JSON APIs |
| Recency Filter | Only articles published in last 24 hours pass |
| Keyword Filter | Include/exclude keyword matching on title + description |
| Two-Layer Deduplication | URL hash + title similarity (SequenceMatcher ≥ 0.75) |
| Daily Cap Enforcement | Hard 5-post limit per rolling 24-hour window, persisted in Supabase |
| OG Image Extraction | Extract thumbnail from article's `<meta og:image>` tag |
| LLM Summarization | 5-level fallback chain — Groq → Mistral → OpenRouter → Gemini → Raw |
| Locked Message Formatting | Enforced template: headline, 3 paragraphs, 5 bullet points, conclusion |
| WhatsApp Channel Delivery | Baileys Node.js — image+caption to newsletter JID |
| Session Persistence | Baileys creds.json + Signal keys serialized to Supabase JSONB |
| Anti-Ban Measures | Randomized delays, composing state, metadata rotation |
| Graceful Degradation | Every component has a defined fallback — nothing causes a hard crash |
| Error Logging | All failures logged to Supabase with timestamp, component, and context |

### 5.2 Out of Scope — v1
- Admin dashboard
- Subscriber count tracking
- Manual posting trigger
- Multi-channel support
- Content quality scoring beyond keyword filter
- Auto-recovery notifications (e.g., email on failure)

---

## 6. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Daily uptime | Posts delivered on ≥ 28 of 30 days/month | Manual audit of post_log |
| Posts per day | 3–5 (never 0, never >5) | post_log count per date |
| Duplicate post rate | 0 | Manual audit of articles table |
| LLM fallback recovery | 100% — never a skipped post due to LLM failure | error_log audit |
| WhatsApp delivery success | ≥ 95% of formatted articles sent successfully | post_log status |
| Session persistence | 0 manual re-pair events per month | Observation |
| Monthly infrastructure cost | $0 | Billing check |
| Manual interventions required | 0 per week after deployment | Observation |

---

## 7. Constraints

| Constraint | Value |
|-----------|-------|
| Total monthly cost | $0 — no exceptions |
| Posts per day | Maximum 5, hard cap |
| WhatsApp delivery method | Baileys only — no Meta Cloud API |
| Hosting | GitHub Actions cron only — no always-on server |
| Session storage | Supabase only — no local disk (ephemeral in GH Actions) |
| LLM providers | Only free tiers — no paid model calls |
| Source access | Only public RSS/APIs — no authenticated paid sources |

---

## 8. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| WhatsApp bans the posting number | High | Dedicated SIM, lazy auth, anti-ban measures, human simulation delays |
| Baileys session corruption in Supabase | High | Validate session on load, full re-serialization on every save |
| GitHub Actions free tier cron unreliability | Medium | Cron runs every 30 min — missing one run ≠ missing a post |
| All LLM providers fail simultaneously | Low | Raw RSS fallback always executes — post never skipped |
| Supabase free tier row limits hit | Low | Max 5 posts/day = ~150/month — far below 500MB free limit |
| RSS source blocks GitHub Actions IP range | Medium | try/except per source — one blocked source doesn't kill the run |
| OG image URL expires or hotlink-blocked | Low | Fallback to text-only post — delivery continues |

---
