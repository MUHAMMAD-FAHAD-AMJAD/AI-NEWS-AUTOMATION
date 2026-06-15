# Backend Schema Document
## AI News Bot | WhatsApp Channel Automation

**Version:** 1.0  
**Database:** Supabase PostgreSQL (Free Tier)  
**Status:** Pre-Implementation

---

## 1. Supabase Project Setup

### 1.1 Free Tier Limits Reference

| Resource | Free Tier Limit | Expected Usage | Buffer |
|----------|----------------|----------------|--------|
| Database storage | 500 MB | < 5 MB (text only) | 99% free |
| Rows | Unlimited | ~4,500/month | N/A |
| API requests | 500K/month | ~6,000/month | 99% free |
| Realtime connections | 200 concurrent | 0 (not used) | N/A |

This project will use < 1% of Supabase free tier capacity.

---

## 2. Schema — Full SQL

Run this in Supabase SQL Editor to create all tables:

```sql
-- ============================================================
-- AI NEWS BOT — SUPABASE SCHEMA
-- Run once on fresh Supabase project
-- ============================================================


-- ============================================================
-- TABLE 1: articles
-- Tracks every article seen by the bot
-- Primary deduplication source
-- ============================================================

CREATE TABLE IF NOT EXISTS articles (
    hash            TEXT PRIMARY KEY,
    -- MD5 hash of normalized URL (url.strip().lower())
    -- Used as fast exact-duplicate check (Layer 1 dedup)

    title           TEXT NOT NULL,
    -- Original article title from RSS/API
    -- Used for similarity dedup (Layer 2 — SequenceMatcher)

    url             TEXT NOT NULL UNIQUE,
    -- Original article URL — stored for reference
    -- UNIQUE constraint prevents raw URL duplicates

    source          TEXT NOT NULL,
    -- Which feed this came from
    -- Values: 'techcrunch' | 'theverge' | 'venturebeat' |
    --         'mittr' | 'wired' | 'huggingface' | 'googleai' |
    --         'openai' | 'hackernews' | 'reddit'

    fetched_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- When the bot first saw this article (UTC)

    posted_at       TIMESTAMP WITH TIME ZONE,
    -- When this article was successfully sent to WhatsApp (UTC)
    -- NULL until successfully posted

    status          TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'POSTED', 'FAILED', 'FILTERED', 'DUPLICATE')),
    -- PENDING:   Passed dedup, queued for LLM + posting
    -- POSTED:    Successfully delivered to WhatsApp Channel
    -- FAILED:    WhatsApp delivery failed after retry
    -- FILTERED:  Did not pass keyword/recency filter
    -- DUPLICATE: Caught by Layer 1 or Layer 2 dedup

    llm_provider    TEXT,
    -- Which LLM provider generated the summary
    -- Values: 'groq' | 'mistral' | 'openrouter_llama' |
    --         'openrouter_mistral' | 'gemini' | 'raw'
    -- NULL until article reaches summarization step

    had_image       BOOLEAN DEFAULT FALSE,
    -- Whether OG image was successfully extracted and sent
    -- Used for analytics on image vs text-only post quality

    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    -- Record creation timestamp (same as fetched_at for most cases)
);

-- Indexes for articles
CREATE INDEX IF NOT EXISTS idx_articles_status
    ON articles(status);
-- Fast: SELECT * FROM articles WHERE status = 'POSTED'

CREATE INDEX IF NOT EXISTS idx_articles_fetched_at
    ON articles(fetched_at DESC);
-- Fast: ORDER BY fetched_at for recent articles query

CREATE INDEX IF NOT EXISTS idx_articles_source
    ON articles(source);
-- Fast: GROUP BY source for analytics

CREATE INDEX IF NOT EXISTS idx_articles_posted_at
    ON articles(posted_at DESC NULLS LAST);
-- Fast: ORDER BY posted_at for recent posts query


-- ============================================================
-- TABLE 2: post_log
-- Audit trail for every WhatsApp delivery attempt
-- Used for daily cap enforcement
-- ============================================================

CREATE TABLE IF NOT EXISTS post_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Auto-incrementing surrogate key

    article_hash    TEXT NOT NULL REFERENCES articles(hash) ON DELETE CASCADE,
    -- Foreign key to articles table
    -- Cascade delete: if article removed, log removed too

    posted_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- When delivery was attempted (UTC)
    -- Used for rolling 24-hour cap check

    status          TEXT NOT NULL CHECK (status IN ('success', 'failed', 'retry_success')),
    -- success:       First attempt succeeded
    -- failed:        Both attempts failed
    -- retry_success: First attempt failed, retry succeeded

    whatsapp_msg_id TEXT,
    -- Message ID returned by Baileys after successful send
    -- Format: "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
    -- NULL if delivery failed

    llm_provider    TEXT,
    -- Copy of which LLM was used (denormalized for fast analytics)
    -- Avoids JOIN to articles table for provider breakdown queries

    had_image       BOOLEAN DEFAULT FALSE,
    -- Copy of whether image was included (denormalized)

    error_detail    TEXT,
    -- Populated if status = 'failed'
    -- Brief error message for debugging

    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for post_log
CREATE INDEX IF NOT EXISTS idx_post_log_posted_at
    ON post_log(posted_at DESC);
-- Critical for daily cap check query:
-- SELECT COUNT(*) FROM post_log WHERE posted_at > NOW() - INTERVAL '24 hours'

CREATE INDEX IF NOT EXISTS idx_post_log_article_hash
    ON post_log(article_hash);
-- Fast: lookup all posts for a given article

CREATE INDEX IF NOT EXISTS idx_post_log_status
    ON post_log(status);
-- Fast: SELECT COUNT(*) ... WHERE status = 'success'


-- ============================================================
-- TABLE 3: whatsapp_auth
-- Stores complete Baileys session state as JSONB
-- Replaces useMultiFileAuthState() for ephemeral environments
-- ============================================================

CREATE TABLE IF NOT EXISTS whatsapp_auth (
    key             TEXT PRIMARY KEY,
    -- The auth state key name used by Baileys internals
    -- Examples: 'creds', 'app-state-sync-key-xxxx',
    --           'session-xxxx', 'pre-key-xxxx', 'sender-key-xxxx'
    -- These key names are generated by Baileys — do not hardcode

    value           JSONB NOT NULL,
    -- The entire auth state value for this key
    -- JSONB for efficient storage and querying
    -- Typically: serialized credentials, Signal protocol keys,
    --            session state, pre-keys, sender keys

    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    -- When this key was last written
    -- Used to detect stale sessions
);

-- Trigger: auto-update updated_at on UPSERT
CREATE OR REPLACE FUNCTION update_whatsapp_auth_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER whatsapp_auth_updated_at
    BEFORE UPDATE ON whatsapp_auth
    FOR EACH ROW
    EXECUTE FUNCTION update_whatsapp_auth_timestamp();


-- ============================================================
-- TABLE 4: error_log
-- Structured error tracking for all components
-- Enables post-mortem analysis without server logs
-- ============================================================

CREATE TABLE IF NOT EXISTS error_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    timestamp       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    component       TEXT NOT NULL
                    CHECK (component IN (
                        'fetcher', 'filter', 'dedup',
                        'og_extractor', 'llm', 'formatter',
                        'whatsapp', 'db', 'startup'
                    )),
    -- Which part of the pipeline failed

    provider        TEXT,
    -- For component='llm': which LLM provider failed
    -- For component='fetcher': which RSS source failed
    -- For component='whatsapp': 'baileys'
    -- NULL for other components

    error_type      TEXT,
    -- Short error class: 'timeout', 'rate_limit', 'parse_error',
    --                    'connection_refused', 'invalid_response', etc.

    error_message   TEXT NOT NULL,
    -- Full error message or exception string

    article_hash    TEXT,
    -- NULL if error occurred before article was identified
    -- Populated once we're processing a specific article

    article_url     TEXT,
    -- Redundant with article_hash but faster for human debugging

    run_id          TEXT,
    -- UUID generated at pipeline start — groups errors from same run
    -- Allows: "show me all errors from the 14:30 run"

    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for error_log
CREATE INDEX IF NOT EXISTS idx_error_log_timestamp
    ON error_log(timestamp DESC);
-- Fast: recent errors first

CREATE INDEX IF NOT EXISTS idx_error_log_component
    ON error_log(component);
-- Fast: GROUP BY component for error frequency analysis

CREATE INDEX IF NOT EXISTS idx_error_log_provider
    ON error_log(provider);
-- Fast: which LLM/RSS source is failing most
```

---

## 3. Row-Level Security (RLS) Policies

Enable RLS on all tables to protect data. Since we use the anon key in the application, we need explicit policies:

```sql
-- Enable RLS on all tables
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE post_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_auth ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_log ENABLE ROW LEVEL SECURITY;

-- Allow anon key to read and write articles
CREATE POLICY "newsbot_articles_all" ON articles
    FOR ALL USING (true) WITH CHECK (true);

-- Allow anon key to read and write post_log
CREATE POLICY "newsbot_post_log_all" ON post_log
    FOR ALL USING (true) WITH CHECK (true);

-- Allow anon key to read and write whatsapp_auth
CREATE POLICY "newsbot_whatsapp_auth_all" ON whatsapp_auth
    FOR ALL USING (true) WITH CHECK (true);

-- Allow anon key to read and write error_log
CREATE POLICY "newsbot_error_log_all" ON error_log
    FOR ALL USING (true) WITH CHECK (true);
```

> **Security note:** These policies allow any request with your anon key to read/write all rows. Since the anon key is in GitHub Secrets (not public), this is acceptable. For a multi-user system, use more restrictive policies with auth.uid().

---

## 4. Critical Queries

### 4.1 Daily Cap Check (called every run)

```sql
SELECT COUNT(*) as posts_today
FROM post_log
WHERE posted_at > NOW() - INTERVAL '24 hours'
AND status IN ('success', 'retry_success');
```

Returns an integer. If >= 5, abort the run.

### 4.2 Layer 1 Deduplication Check

```sql
SELECT 1 FROM articles WHERE hash = $1 LIMIT 1;
```

Returns 1 row if duplicate, 0 rows if new.

### 4.3 Layer 2 — Fetch Recent Titles for Similarity Check

```sql
SELECT title FROM articles
WHERE fetched_at > NOW() - INTERVAL '48 hours'
AND status IN ('POSTED', 'PENDING');
```

Returns list of recent titles. Run SequenceMatcher in Python against each.

### 4.4 Mark Article as Posted

```sql
UPDATE articles
SET status = 'POSTED',
    posted_at = NOW(),
    had_image = $2,
    llm_provider = $3
WHERE hash = $1;
```

### 4.5 Insert Post Log Entry

```sql
INSERT INTO post_log (article_hash, status, whatsapp_msg_id, llm_provider, had_image)
VALUES ($1, 'success', $2, $3, $4);
```

### 4.6 Log Error

```sql
INSERT INTO error_log (component, provider, error_type, error_message, article_hash, article_url, run_id)
VALUES ($1, $2, $3, $4, $5, $6, $7);
```

### 4.7 Monitoring — Last 7 Days Post Volume

```sql
SELECT
    DATE(posted_at AT TIME ZONE 'Asia/Karachi') as date_pkt,
    COUNT(*) as posts,
    COUNT(CASE WHEN had_image THEN 1 END) as with_image,
    MODE() WITHIN GROUP (ORDER BY llm_provider) as top_llm
FROM post_log
WHERE status IN ('success', 'retry_success')
AND posted_at > NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1 DESC;
```

### 4.8 LLM Provider Breakdown (all time)

```sql
SELECT
    llm_provider,
    COUNT(*) as posts,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM post_log
WHERE status IN ('success', 'retry_success')
GROUP BY llm_provider
ORDER BY 2 DESC;
```

### 4.9 Error Frequency by Component

```sql
SELECT
    component,
    provider,
    COUNT(*) as errors,
    MAX(timestamp) as last_seen
FROM error_log
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY component, provider
ORDER BY 3 DESC;
```

---

## 5. Baileys Auth State — How It Works

The `whatsapp_auth` table stores Baileys' entire authentication state. Here's what gets stored:

| Key Pattern | Contents | Notes |
|-------------|---------|-------|
| `creds` | Main WA credentials JSON | Account registration, identity keys, server config |
| `app-state-sync-key-*` | App state sync keys | Multiple rows, one per key ID |
| `session-*` | Signal session records | One per contact/device pair |
| `pre-key-*` | Signal pre-keys | Batch of one-time keys |
| `sender-key-*` | Group/channel sender keys | One per group/channel |

**Total rows expected:** 50–200 depending on channel activity. Well within Supabase limits.

### 5.1 Custom Auth State Implementation (JavaScript)

```javascript
// baileys-sender/auth/supabaseAuthState.js

import { createClient } from '@supabase/supabase-js'
import { proto } from '@whiskeysockets/baileys'
import { initAuthCreds, BufferJSON } from '@whiskeysockets/baileys'

export async function useSupabaseAuthState(supabase) {
  
  // Load all auth keys from Supabase on startup
  async function loadState() {
    const { data, error } = await supabase
      .from('whatsapp_auth')
      .select('key, value')
    
    if (error) throw new Error(`Failed to load auth state: ${error.message}`)
    
    const state = {}
    for (const row of (data || [])) {
      state[row.key] = JSON.parse(JSON.stringify(row.value), BufferJSON.reviver)
    }
    return state
  }

  const authState = await loadState()

  const creds = authState['creds'] 
    ? authState['creds'] 
    : initAuthCreds()

  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const result = {}
          for (const id of ids) {
            const key = `${type}-${id}`
            result[id] = authState[key]
              ? JSON.parse(JSON.stringify(authState[key]), BufferJSON.reviver)
              : undefined
          }
          return result
        },
        set: async (data) => {
          const upserts = []
          for (const category in data) {
            for (const id in data[category]) {
              const key = `${category}-${id}`
              const value = data[category][id]
                ? JSON.parse(JSON.stringify(data[category][id], BufferJSON.replacer))
                : null
              
              if (value) {
                upserts.push({ key, value })
                authState[key] = data[category][id]
              } else {
                // Null value = delete this key
                await supabase.from('whatsapp_auth').delete().eq('key', key)
                delete authState[key]
              }
            }
          }
          
          if (upserts.length > 0) {
            const { error } = await supabase
              .from('whatsapp_auth')
              .upsert(upserts, { onConflict: 'key' })
            if (error) console.error('Auth state save error:', error.message)
          }
        }
      }
    },
    saveCreds: async () => {
      const { error } = await supabase
        .from('whatsapp_auth')
        .upsert(
          { 
            key: 'creds', 
            value: JSON.parse(JSON.stringify(creds, BufferJSON.replacer))
          },
          { onConflict: 'key' }
        )
      if (error) console.error('Creds save error:', error.message)
    }
  }
}
```

---

## 6. Data Retention

Since this is a free tier project with no cleanup automation, the data volume is naturally small:

| Table | Growth Rate | After 1 Year |
|-------|-------------|-------------|
| articles | ~50 rows/day (most filtered) | ~18,000 rows ≈ 3 MB |
| post_log | ~4 rows/day | ~1,460 rows ≈ 0.2 MB |
| whatsapp_auth | Static ~100 rows | 100 rows ≈ 0.5 MB |
| error_log | ~20 rows/day (estimate) | ~7,300 rows ≈ 1 MB |
| **Total** | | **~5 MB** (vs 500 MB limit) |

No cleanup required for at least 3+ years on free tier.

---
