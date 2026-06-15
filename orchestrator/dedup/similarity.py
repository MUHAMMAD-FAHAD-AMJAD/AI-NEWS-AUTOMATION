"""
orchestrator/dedup/similarity.py
----------------------------------
Layer 2 deduplication — title similarity check against recently posted articles.

Uses Python's difflib.SequenceMatcher to compute the ratio between the
candidate article's title and each title posted in the last 48 hours.

Threshold: 0.75 (from config.similarity_threshold)
  - ratio >= 0.75 → DUPLICATE (same story, different source or wording)
  - ratio < 0.75  → NEW (sufficiently different story)

Per 05-BACKEND-SCHEMA.md §4.3:
  SELECT title FROM articles
  WHERE fetched_at > NOW() - INTERVAL '48 hours'
  AND status IN ('POSTED', 'PENDING')

This catches the case where:
  "OpenAI Releases GPT-5 With New Capabilities"  (from TechCrunch)
  "OpenAI Launches GPT-5 Model"                  (from The Verge)
  → ratio ≈ 0.82 → DUPLICATE → second article rejected

SECURITY: Only titles are fetched from DB — no content, no URLs.
"""

import sys
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from supabase import Client

from orchestrator.models.article import Article


def _similarity_ratio(title_a: str, title_b: str) -> float:
    """
    Compute SequenceMatcher ratio between two lowercased titles.

    Returns:
        float: 0.0 (completely different) to 1.0 (identical).
    """
    return SequenceMatcher(
        None,
        title_a.lower().strip(),
        title_b.lower().strip(),
    ).ratio()


def is_title_duplicate(
    article: Article,
    supabase: Client,
    threshold: float = 0.75,
) -> bool:
    """
    Return True if a sufficiently similar title exists in the last 48 hours.

    Fetches all recent posted/pending article titles from Supabase and
    runs SequenceMatcher against each. Stops early on first match found.

    Args:
        article:    Article to check.
        supabase:   Initialized Supabase client.
        threshold:  Similarity ratio above which we consider it a duplicate.
                    Default: 0.75

    Returns:
        bool: True if duplicate (too similar to recent article), else False.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        result = (
            supabase.table("articles")
            .select("title")
            .gte("fetched_at", cutoff.isoformat())
            .in_("status", ["POSTED", "PENDING"])
            .execute()
        )
    except Exception as e:
        # Fail-open: if we can't check, assume not duplicate
        print(
            f"[WARN] [dedup/similarity] DB fetch failed: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return False

    for row in result.data:
        existing_title = row.get("title", "")
        if not existing_title:
            continue
        ratio = _similarity_ratio(article.title, existing_title)
        if ratio >= threshold:
            print(
                f"[DEDUP L2] Title similarity {ratio:.2f} >= {threshold} — "
                f"matched: {existing_title[:60]!r}"
            )
            return True

    return False


def filter_title_duplicates(
    articles: list[Article],
    supabase: Client,
    threshold: float = 0.75,
) -> tuple[list[Article], list[Article]]:
    """
    Partition articles into unique and title-similar duplicates.

    Fetches recent titles ONCE from Supabase, then runs comparison
    in-memory for efficiency (avoids N DB calls for N articles).

    Args:
        articles:   Layer-1-deduplicated articles.
        supabase:   Initialized Supabase client.
        threshold:  Similarity threshold. Default: 0.75.

    Returns:
        Tuple of (unique_articles, similar_duplicates).
    """
    # Fetch all recent titles ONCE
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        result = (
            supabase.table("articles")
            .select("title")
            .gte("fetched_at", cutoff.isoformat())
            .in_("status", ["POSTED", "PENDING"])
            .execute()
        )
        recent_titles = [
            row["title"] for row in result.data if row.get("title")
        ]
    except Exception as e:
        print(
            f"[WARN] [dedup/similarity] Batch fetch failed: {e}",
            file=sys.stderr,
        )
        # Fail-open: return all articles as unique
        return articles, []

    unique = []
    similar = []

    for article in articles:
        is_dup = False
        for existing_title in recent_titles:
            ratio = _similarity_ratio(article.title, existing_title)
            if ratio >= threshold:
                print(
                    f"[DEDUP L2] {ratio:.2f} similarity — "
                    f"REJECT: {article.title[:50]!r}"
                )
                is_dup = True
                break

        if is_dup:
            similar.append(article)
        else:
            unique.append(article)
            # Add this article's title to recent_titles so that
            # if two candidates in the same batch are similar to each other,
            # the second one is also caught
            recent_titles.append(article.title)

    if similar:
        print(
            f"[DEDUP L2] {len(unique)} unique, "
            f"{len(similar)} title-similar duplicates removed"
        )

    return unique, similar
