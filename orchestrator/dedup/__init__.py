"""
orchestrator/dedup/__init__.py
--------------------------------
Public API for the dedup package.

Exposes run_deduplication() which applies both layers in sequence:
  Layer 1: URL hash vs Supabase (exact match)
  Layer 2: Title similarity vs last 48h (SequenceMatcher >= 0.75)
"""

from supabase import Client

from orchestrator.dedup.hash import filter_url_duplicates
from orchestrator.dedup.similarity import filter_title_duplicates
from orchestrator.models.article import Article


def run_deduplication(
    articles: list[Article],
    supabase: Client,
    similarity_threshold: float = 0.75,
) -> list[Article]:
    """
    Run both deduplication layers and return only truly new articles.

    Layer 1 (URL hash): Fast Supabase PRIMARY KEY lookup per article.
    Layer 2 (title sim): Single Supabase fetch + in-memory SequenceMatcher.

    Args:
        articles:             Keyword+recency filtered articles.
        supabase:             Initialized Supabase client.
        similarity_threshold: SequenceMatcher ratio threshold. Default: 0.75.

    Returns:
        list[Article]: Unique articles that passed both dedup layers.
    """
    if not articles:
        return []

    # Layer 1: URL hash
    after_l1, url_dupes = filter_url_duplicates(articles, supabase)

    if not after_l1:
        print("[DEDUP] All articles were URL duplicates — nothing new this run.")
        return []

    # Layer 2: Title similarity
    after_l2, title_dupes = filter_title_duplicates(
        after_l1, supabase, similarity_threshold
    )

    total_removed = len(url_dupes) + len(title_dupes)
    print(
        f"[DEDUP] Complete — {len(after_l2)} unique articles "
        f"(removed: {len(url_dupes)} URL dupes, {len(title_dupes)} title dupes)"
    )

    return after_l2


__all__ = [
    "run_deduplication",
    "filter_url_duplicates",
    "filter_title_duplicates",
]
