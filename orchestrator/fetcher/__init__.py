"""
orchestrator/fetcher/__init__.py
---------------------------------
Public API for the fetcher package.

Exposes a single async entry point: fetch_all()

This function:
1. Calls all 4 fetchers (RSS x8, HN, Reddit) CONCURRENTLY via asyncio.gather
2. Combines all results into a single flat list
3. Deduplicates by URL hash (same article from multiple sources = keep first)
4. Sorts by published_at descending (newest first)
5. Returns final List[Article]

The caller (main.py) uses only this function — it never imports individual
fetchers directly.
"""

import asyncio
from typing import List

from orchestrator.fetcher.hackernews import fetch_hackernews
from orchestrator.fetcher.reddit import fetch_reddit
from orchestrator.fetcher.rss import fetch_all_rss
from orchestrator.models.article import Article


async def fetch_all() -> List[Article]:
    """
    Fetch articles from ALL sources concurrently and return a
    deduplicated, newest-first sorted combined list.

    Sources:
        - 8 RSS feeds (via fetch_all_rss — already internally parallel)
        - Hacker News Algolia API
        - Reddit r/artificial top.json

    Returns:
        List[Article]: Combined, unique, sorted articles.
                       Never raises — individual fetcher failures return [].
    """
    # Run all 3 top-level fetchers concurrently.
    # fetch_all_rss() itself runs 8 sub-fetches concurrently — so this
    # call launches all 10 source fetches as close to simultaneously as possible.
    rss_articles, hn_articles, reddit_articles = await asyncio.gather(
        fetch_all_rss(),
        fetch_hackernews(),
        fetch_reddit(),
        return_exceptions=False,  # Each fetcher handles its own exceptions
    )

    # Combine all sources
    combined: List[Article] = []
    combined.extend(rss_articles)
    combined.extend(hn_articles)
    combined.extend(reddit_articles)

    # Deduplicate by URL hash — first occurrence wins (RSS articles are
    # already sorted newest-first, so we preserve the most-recent version)
    seen_hashes: set = set()
    unique: List[Article] = []
    for article in combined:
        if article.hash not in seen_hashes:
            seen_hashes.add(article.hash)
            unique.append(article)

    # Sort combined list newest-first
    unique.sort(key=lambda a: a.published_at, reverse=True)

    print(
        f"[FETCH] Complete — {len(unique)} unique articles "
        f"(RSS: {len(rss_articles)}, HN: {len(hn_articles)}, "
        f"Reddit: {len(reddit_articles)}, "
        f"Dupes removed: {len(combined) - len(unique)})"
    )

    return unique
