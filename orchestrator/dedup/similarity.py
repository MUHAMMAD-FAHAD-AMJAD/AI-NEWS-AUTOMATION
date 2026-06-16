"""
orchestrator/dedup/similarity.py
----------------------------------
Layer 2 deduplication — title similarity + topic keyword clustering.

Two checks run in sequence per article:

  CHECK A — SequenceMatcher (48h window, threshold 0.85):
    Ratio >= 0.85 → DUPLICATE (same story, different wording).
    Raised from 0.75 to 0.85 — was too loose, caught too many false positives.

  CHECK B — Keyword topic clustering (6h window):
    Extract meaningful keywords from each title (stopword-filtered).
    If 2+ keywords match any article posted in the last 6 hours → DUPLICATE.
    Prevents topic flooding: e.g. 5 posts all about "Anthropic vs White House"
    that each passed SequenceMatcher because headlines were worded differently.

Per 05-BACKEND-SCHEMA.md §4.3:
  SELECT title FROM articles
  WHERE fetched_at > NOW() - INTERVAL '48 hours'
  AND status IN ('POSTED', 'PENDING')

SECURITY: Only titles are fetched from DB — no content, no URLs.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from supabase import Client

from orchestrator.models.article import Article


# ------------------------------------------------------------------ #
# Stopwords — common English words that carry no topical meaning       #
# ------------------------------------------------------------------ #

_STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
    'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were',
    'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
    'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can',
    'this', 'that', 'these', 'those', 'it', 'its', 'as', 'up', 'out',
    'about', 'after', 'over', 'than', 'into', 'new', 'more', 'now',
    'how', 'why', 'what', 'who', 'when', 'where', 'which', 'not',
    'just', 'says', 'said', 'say', 'get', 'got', 'use', 'used',
    'all', 'big', 'top', 'one', 'two', 'three', 'has', 'its',
}


# ------------------------------------------------------------------ #
# Similarity helpers                                                    #
# ------------------------------------------------------------------ #

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


def _extract_keywords(title: str) -> set:
    """
    Extract meaningful keywords from a title — no external library needed.

    Steps:
      1. Lowercase and tokenize into words (3+ alphabetic chars only)
      2. Remove stopwords from the result
      3. Return as a set (order irrelevant)

    Args:
        title: Article title string.

    Returns:
        set: Meaningful words of length >= 3, stopwords removed.
    """
    words = re.findall(r'\b[a-z]{3,}\b', title.lower())
    return {w for w in words if w not in _STOPWORDS}


def _is_topic_duplicate(
    candidate_title: str,
    recent_titles: list,
    min_overlap: int = 2,
) -> bool:
    """
    Return True if the candidate shares 2+ keywords with any recent title.

    This catches same-topic stories that SequenceMatcher misses because
    the wording is sufficiently different.

    Example:
      Candidate: "Anthropic Sues White House Over AI Regulation"
      Recent:    "White House Defends Anthropic Policy Restrictions"
      Overlap:   {'anthropic', 'white', 'house'} = 3 keywords → DUPLICATE

    Args:
        candidate_title: Title of the candidate article.
        recent_titles:   Titles of articles posted/pending in last 6 hours.
        min_overlap:     Minimum keyword overlap count to flag as duplicate.

    Returns:
        bool: True if topic duplicate detected.
    """
    candidate_kw = _extract_keywords(candidate_title)
    if len(candidate_kw) < min_overlap:
        # Too few keywords to make a meaningful comparison
        return False

    for recent_title in recent_titles:
        recent_kw = _extract_keywords(recent_title)
        overlap = candidate_kw & recent_kw
        if len(overlap) >= min_overlap:
            top = sorted(overlap)[:3]
            print(
                f"[DEDUP TOPIC] {len(overlap)} shared keywords {top} — "
                f"REJECT: {candidate_title[:50]!r}"
            )
            return True

    return False


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #

def filter_title_duplicates(
    articles: list,
    supabase: Client,
    threshold: float = 0.85,
) -> tuple:
    """
    Partition articles into unique and duplicate via two checks.

    Check A — SequenceMatcher ratio >= threshold against last 48h titles.
    Check B — Keyword topic overlap >= 2 against last 6h titles.

    Fetches recent titles from Supabase once per window (2 DB calls total).

    Args:
        articles:   Layer-1-deduplicated articles to check.
        supabase:   Initialized Supabase client.
        threshold:  SequenceMatcher threshold. Default: 0.85.

    Returns:
        Tuple of (unique_articles, similar_duplicates).
    """
    now = datetime.now(timezone.utc)
    cutoff_48h = now - timedelta(hours=48)
    cutoff_6h  = now - timedelta(hours=6)

    # ── Fetch 48-hour titles for SequenceMatcher ──────────────────────
    try:
        result_48h = (
            supabase.table("articles")
            .select("title")
            .gte("fetched_at", cutoff_48h.isoformat())
            .in_("status", ["POSTED", "PENDING"])
            .execute()
        )
        titles_48h = [r["title"] for r in result_48h.data if r.get("title")]
    except Exception as e:
        print(f"[WARN] [dedup] 48h fetch failed: {e}", file=sys.stderr)
        titles_48h = []

    # ── Fetch 6-hour titles for topic clustering ──────────────────────
    try:
        result_6h = (
            supabase.table("articles")
            .select("title")
            .gte("fetched_at", cutoff_6h.isoformat())
            .in_("status", ["POSTED", "PENDING"])
            .execute()
        )
        titles_6h = [r["title"] for r in result_6h.data if r.get("title")]
    except Exception as e:
        print(f"[WARN] [dedup] 6h fetch failed: {e}", file=sys.stderr)
        titles_6h = []

    unique = []
    similar = []

    for article in articles:
        is_dup = False

        # ── Check A: SequenceMatcher (48h window) ─────────────────────
        for existing_title in titles_48h:
            ratio = _similarity_ratio(article.title, existing_title)
            if ratio >= threshold:
                print(
                    f"[DEDUP L2] {ratio:.2f} similarity — "
                    f"REJECT: {article.title[:50]!r}"
                )
                is_dup = True
                break

        # ── Check B: Topic clustering (6h window) ─────────────────────
        # Only run if article passed Check A — no double-counting
        if not is_dup:
            if _is_topic_duplicate(article.title, titles_6h):
                is_dup = True

        if is_dup:
            similar.append(article)
        else:
            unique.append(article)
            # Add to both in-memory lists so within-batch duplicates are caught
            titles_48h.append(article.title)
            titles_6h.append(article.title)

    if similar:
        print(
            f"[DEDUP L2] {len(unique)} unique, "
            f"{len(similar)} duplicates removed (similarity + topic)"
        )

    return unique, similar


def is_title_duplicate(
    article: Article,
    supabase: Client,
    threshold: float = 0.85,
) -> bool:
    """
    Single-article check — wraps filter_title_duplicates() for convenience.

    Prefer filter_title_duplicates() for batch processing to avoid
    repeated DB queries.

    Args:
        article:    Article to check.
        supabase:   Initialized Supabase client.
        threshold:  Similarity threshold. Default: 0.85.

    Returns:
        bool: True if duplicate.
    """
    unique, _ = filter_title_duplicates([article], supabase, threshold)
    return len(unique) == 0
