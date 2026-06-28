"""
orchestrator/dedup/hash.py
----------------------------
Layer 1 deduplication — MD5 URL hash lookup against Supabase articles table.

This is the FASTEST and CHEAPEST dedup check:
- Single indexed lookup on the `hash` primary key
- Returns True if the article URL (normalized) was seen before
- O(1) Supabase query, indexed PRIMARY KEY

Per the schema (05-BACKEND-SCHEMA.md):
  SELECT 1 FROM articles WHERE hash = $1 LIMIT 1

The article.hash is pre-computed in Article.__post_init__ as:
  MD5(url.strip().lower())

So this check is: "have we ever seen this URL before?"
"""

import sys

from supabase import Client

from orchestrator.models.article import Article


def is_url_duplicate(article: Article, supabase: Client) -> bool:
    """
    Return True if this article's URL hash already exists in Supabase.

    Performs a single indexed PRIMARY KEY lookup — extremely fast.

    Args:
        article:  Article to check.
        supabase: Initialized Supabase client.

    Returns:
        bool: True if duplicate (seen before), False if new.
    """
    try:
        result = (
            supabase.table("articles")
            .select("hash")
            .eq("hash", article.hash)
            .limit(1)
            .execute()
        )
        return len(result.data) > 0
    except Exception as e:
        # Fail-safe: if DB is unreachable, treat as duplicate.
        # A network glitch must never accidentally post an unverified article.
        print(
            f"[DEDUP L1] DB error for {article.hash[:8]}: "
            f"{type(e).__name__} — treating as duplicate (fail-safe)",
            file=sys.stderr,
        )
        return True


def filter_url_duplicates(
    articles: list[Article],
    supabase: Client,
) -> tuple[list[Article], list[Article]]:
    """
    Partition articles into new (not seen) and URL duplicates.

    Makes one Supabase call per article. For Phase 2 volumes (20-80 articles)
    this is fine. Phase 11 can batch this if needed.

    Args:
        articles: Filtered list of articles to check.
        supabase: Initialized Supabase client.

    Returns:
        Tuple of (new_articles, duplicate_articles).
    """
    new_articles = []
    duplicates = []

    for article in articles:
        if is_url_duplicate(article, supabase):
            duplicates.append(article)
        else:
            new_articles.append(article)

    if duplicates:
        print(
            f"[DEDUP L1] {len(new_articles)} new, "
            f"{len(duplicates)} URL duplicates removed"
        )

    return new_articles, duplicates
