"""
orchestrator/main.py
----------------------
Pipeline entry point — wires together all phases (1–6).

Pipeline flow per 06-IMPLEMENTATION-PLAN.md §6.2:
  1. Load config + connect Supabase
  2. Daily cap check (5 posts/day max)
  3. Fetch articles from all sources
  4. Filter (recency + keywords) + deduplicate (URL hash + title similarity)
  5. Take first candidate article
  6. Extract OG image
  7. LLM summarize (Groq → Mistral → OpenRouter → Gemini → Raw)
  8. Format message + validate
  9. Write payload.json
  10. Insert article as PENDING in Supabase
  11. Set GitHub Actions outputs

Node.js Baileys sender reads payload.json in the next workflow step.

SECURITY:
- No secrets logged
- Article content logged only as: title[:60]
- All errors logged by component, not content
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from supabase import create_client

from orchestrator.config import ConfigError, load_config
from orchestrator.dedup import run_deduplication
from orchestrator.extractor import extract_og_image
from orchestrator.fetcher import fetch_all
from orchestrator.filter import apply_filters
from orchestrator.formatter import build_fallback_message, build_message, validate_message
from orchestrator.llm import summarize_with_fallback
from orchestrator.models.summary import SummaryResult


# Payload written here — read by Node.js Baileys step
PAYLOAD_PATH = os.environ.get("PAYLOAD_PATH", "/tmp/article_payload.json")


# ------------------------------------------------------------------ #
# Daily Cap Helper                                                     #
# ------------------------------------------------------------------ #

def get_last_post_time(supabase):
    """
    Return the posted_at timestamp of the most recently POSTED article.

    Returns None if no articles posted yet, or on any DB error.
    Fail-open: if DB is unreachable, we allow the post.
    """
    try:
        result = (
            supabase.table("articles")
            .select("posted_at")
            .eq("status", "POSTED")
            .order("posted_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            posted_at_str = result.data[0].get("posted_at")
            if posted_at_str:
                return datetime.fromisoformat(
                    posted_at_str.replace("Z", "+00:00")
                )
        return None
    except Exception as e:
        print(
            f"[THROTTLE] DB query failed: {type(e).__name__} — allowing post",
            file=sys.stderr,
        )
        return None


# ------------------------------------------------------------------ #
# GitHub Actions Output Helper                                        #
# ------------------------------------------------------------------ #

def set_gh_output(key: str, value: str) -> None:
    """
    Write a GitHub Actions step output variable.

    In local dev (no GITHUB_OUTPUT env var), prints to stdout instead.
    """
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    else:
        # Local dev fallback — visible in terminal
        print(f"[OUTPUT] {key}={value}")


# ------------------------------------------------------------------ #
# Main Pipeline                                                        #
# ------------------------------------------------------------------ #

async def run_pipeline() -> None:
    run_id = str(uuid.uuid4())[:8]
    print(f"[RUN {run_id}] Starting pipeline")

    # ── Phase 1: Config + DB ─────────────────────────────────────────
    try:
        config = load_config()
    except ConfigError as e:
        print(f"[CONFIG] {e}", file=sys.stderr)
        sys.exit(1)

    supabase = create_client(config.supabase_url, config.supabase_key)
    print(f"[RUN {run_id}] Config loaded. DB connected.")

    # ── Phase 3 (pre-fetch): 45-minute throttle check ─────────────────
    last_post_time = get_last_post_time(supabase)
    if last_post_time is not None:
        elapsed = datetime.now(tz=timezone.utc) - last_post_time
        min_gap = timedelta(minutes=config.min_minutes_between_posts)
        if elapsed < min_gap:
            remaining = int((min_gap - elapsed).total_seconds() / 60)
            print(
                f"[THROTTLE] Last post was {int(elapsed.total_seconds()/60)}m ago — "
                f"minimum {config.min_minutes_between_posts}m required. "
                f"Skip ({remaining}m remaining)."
            )
            set_gh_output("has_article", "false")
            return
        print(
            f"[THROTTLE] Last post: {int(elapsed.total_seconds()/60)}m ago — OK to post."
        )
    else:
        print("[THROTTLE] No previous posts found — OK to post.")

    # ── Phase 2: Fetch articles ───────────────────────────────────────
    print(f"[FETCH] Fetching articles from all sources...")
    try:
        articles = await fetch_all()
    except Exception as e:
        print(f"[FETCH] Failed: {type(e).__name__}", file=sys.stderr)
        set_gh_output("has_article", "false")
        return

    print(f"[FETCH] {len(articles)} articles fetched")

    if not articles:
        print("[DONE] No articles fetched this run.")
        set_gh_output("has_article", "false")
        return

    # ── Phase 3: Filter (recency + keywords) ─────────────────────────
    filtered = apply_filters(articles, lookback_hours=config.poll_lookback_hours)
    print(f"[FILTER] {len(filtered)}/{len(articles)} articles passed filters")

    if not filtered:
        print("[DONE] No articles passed filters this run.")
        set_gh_output("has_article", "false")
        return

    # ── Phase 3: Deduplication (URL hash + title similarity) ─────────
    candidates = run_deduplication(
        filtered,
        supabase,
        similarity_threshold=config.similarity_threshold,
    )
    print(f"[DEDUP] {len(candidates)}/{len(filtered)} articles are new (post-dedup)")

    if not candidates:
        print("[DONE] No new unique articles this run.")
        set_gh_output("has_article", "false")
        return

    # ── Process first candidate ───────────────────────────────────────
    article = candidates[0]
    print(f"[ARTICLE] Processing: {article.title[:60]}")

    # ── Phase 4: OG Image (HTTP + RSS fallback) ─────────────────────
    print(f"[IMAGE] Extracting OG image...")
    og_image_url = await extract_og_image(article.url)
    if og_image_url:
        print(f"[IMAGE] Found OG image via HTTP meta tags")
    elif article.rss_image_url:
        og_image_url = article.rss_image_url
        print(f"[IMAGE] Found image via RSS media tag (fallback)")
    else:
        print(f"[IMAGE] No OG image found — will post text-only")

    # ── Phase 5: LLM Summarize ───────────────────────────────────────
    print(f"[LLM] Starting summarization fallback chain...")
    summary: SummaryResult = await summarize_with_fallback(
        article=article,
        groq_api_key=config.groq_api_key,
        mistral_api_key=config.mistral_api_key,
        openrouter_api_key=config.openrouter_api_key,
        gemini_api_key=config.gemini_api_key,
    )
    print(f"[LLM] Summary generated via: {summary.llm_provider}")

    # ── Phase 6: Format + Validate ───────────────────────────────────
    if summary.used_raw_fallback:
        # Raw fallback — use the dedicated raw message builder
        message = build_fallback_message(article)
    else:
        message = build_message(summary)

    message = validate_message(message, article=article)
    print(f"[FORMAT] Message ready — {len(message)} chars")

    # ── Write payload.json ────────────────────────────────────────────
    payload = {
        "article_hash": article.hash,
        "formatted_message": message,
        "og_image_url": og_image_url,
        "has_image": og_image_url is not None,
        "run_id": run_id,
        "llm_provider": summary.llm_provider,
        "used_raw_fallback": summary.used_raw_fallback,
    }

    # Ensure directory exists (on Windows /tmp may not exist)
    payload_file = Path(PAYLOAD_PATH)
    payload_file.parent.mkdir(parents=True, exist_ok=True)

    with open(payload_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[PAYLOAD] Written to: {payload_file}")

    # ── Insert article as PENDING in Supabase ────────────────────────
    try:
        supabase.table("articles").upsert(
            {
                "hash": article.hash,
                "title": article.title,
                "url": article.url,
                "source": article.source,
                # fetched_at and created_at default to NOW() — do not pass
                "status": "PENDING",
                "llm_provider": summary.llm_provider,
                "had_image": payload["has_image"],
                # formatted_message is not a column in the articles table
            },
            on_conflict="hash",
        ).execute()
        print(f"[DB] Article inserted as PENDING")
    except Exception as e:
        # Log DB failure but don't abort — payload is already written
        print(f"[DB] Insert failed: {type(e).__name__}", file=sys.stderr)

    # ── Signal GitHub Actions next step ──────────────────────────────
    set_gh_output("has_article", "true")
    set_gh_output("payload_path", str(payload_file))
    print(f"[DONE] Run {run_id} complete. Article: {article.title[:60]}")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
