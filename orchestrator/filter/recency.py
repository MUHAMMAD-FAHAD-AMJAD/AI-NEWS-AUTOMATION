"""
orchestrator/filter/recency.py
--------------------------------
Recency filter — only articles published within the lookback window pass.

Per the spec (03-APP-FLOW.md Step 5):
  - Default lookback: 24 hours
  - Articles with no published_at → rejected
  - All datetime comparisons are UTC-aware

This is always the FIRST filter applied — cheapest check, eliminates the most.
"""

from datetime import datetime, timedelta, timezone

from orchestrator.models.article import Article


def is_recent(article: Article, lookback_hours: int = 24) -> bool:
    """
    Return True if the article was published within the lookback window.

    Args:
        article:        The article to check.
        lookback_hours: How many hours back to look. Default: 24.

    Returns:
        bool: True if article.published_at > (now - lookback_hours), else False.
    """
    if not article.published_at:
        return False

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    return article.published_at > cutoff


def filter_by_recency(
    articles: list[Article],
    lookback_hours: int = 24,
) -> tuple[list[Article], list[Article]]:
    """
    Partition articles into recent and old.

    Args:
        articles:       List of articles to filter.
        lookback_hours: Lookback window in hours.

    Returns:
        Tuple of (recent_articles, rejected_articles).
        Both lists preserve input order.
    """
    recent = []
    rejected = []
    for article in articles:
        if is_recent(article, lookback_hours):
            recent.append(article)
        else:
            rejected.append(article)

    return recent, rejected
