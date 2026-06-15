"""
orchestrator/filter/__init__.py
---------------------------------
Public API for the filter package.

Exposes apply_filters() which runs both recency and keyword filters
in the correct order and returns only passing articles.
"""

from orchestrator.filter.keywords import filter_by_keywords, passes_keyword_filter
from orchestrator.filter.recency import filter_by_recency, is_recent
from orchestrator.models.article import Article


def apply_filters(
    articles: list[Article],
    lookback_hours: int = 24,
) -> list[Article]:
    """
    Apply all filters to the article list in sequence:
      1. Recency filter (cheapest — eliminates most articles first)
      2. Keyword filter

    Args:
        articles:       Raw list of articles from fetchers.
        lookback_hours: Recency window. Default: 24 hours.

    Returns:
        list[Article]: Only articles that passed both filters, in
                       original (newest-first) order.
    """
    # Step 1: Recency
    recent, old = filter_by_recency(articles, lookback_hours)
    if old:
        print(f"[FILTER] Recency: {len(recent)} passed, {len(old)} rejected (older than {lookback_hours}h)")

    # Step 2: Keywords
    passed, off_topic = filter_by_keywords(recent)
    if off_topic:
        print(f"[FILTER] Keywords: {len(passed)} passed, {len(off_topic)} rejected (off-topic)")

    print(f"[FILTER] Total: {len(passed)}/{len(articles)} articles passed all filters")
    return passed


__all__ = [
    "apply_filters",
    "is_recent",
    "passes_keyword_filter",
    "filter_by_recency",
    "filter_by_keywords",
]
