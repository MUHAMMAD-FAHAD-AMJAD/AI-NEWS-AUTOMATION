"""
orchestrator/fetcher/hackernews.py
-----------------------------------
Hacker News top AI/tech story fetcher via Algolia Search API.

No API key required. Uses the public HN Algolia API:
  https://hn.algolia.com/api/v1/search?tags=story&query=AI&hitsPerPage=10

Design decisions:
- httpx.AsyncClient with explicit timeout=15s
- Returns empty list on ANY failure — never raises to caller
- Filters out hits with no URL (Ask HN, Show HN without links)
- description falls back to title if story_text is empty

SECURITY:
- Only title and source are logged to stdout
- No description/content is printed
"""

import sys
from datetime import datetime, timezone
from typing import List

import httpx

from orchestrator.models.article import Article


# Algolia HN search endpoint — no API key required
_HN_API_URL = (
    "https://hn.algolia.com/api/v1/search"
    "?tags=story"
    "&query=AI%20machine%20learning%20LLM"
    "&hitsPerPage=10"
)

_TIMEOUT_SECONDS = 15


async def fetch_hackernews() -> List[Article]:
    """
    Fetch top AI-related stories from Hacker News via Algolia API.

    Returns:
        List[Article]: Up to 10 HN stories matching the AI query,
                       sorted by relevance (Algolia default).
                       Returns [] on any network or parse failure.
    """
    articles: List[Article] = []

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "newsbot/1.0"},
        ) as client:
            resp = await client.get(_HN_API_URL)
            resp.raise_for_status()
            data = resp.json()

        hits = data.get("hits", [])
        skipped = 0

        for hit in hits:
            try:
                # HN Ask/Show posts often have no external URL — skip them
                url = hit.get("url", "") or ""
                if not url or not url.startswith("http"):
                    skipped += 1
                    continue

                title = (hit.get("title", "") or "").strip()
                if not title:
                    skipped += 1
                    continue

                # story_text is the HN post body (often empty for link posts)
                # Fall back to title so description is never blank
                description = (
                    hit.get("story_text", "") or hit.get("title", "") or ""
                ).strip()

                # created_at_i is a Unix timestamp (integer, UTC)
                created_at_i = hit.get("created_at_i")
                if created_at_i is None:
                    skipped += 1
                    continue

                published_at = datetime.fromtimestamp(
                    int(created_at_i), tz=timezone.utc
                )

                article = Article(
                    title=title,
                    url=url,
                    description=description,
                    published_at=published_at,
                    source="hackernews",
                )
                articles.append(article)

            except (ValueError, KeyError, TypeError) as e:
                # Invalid entry — log and continue to next hit
                print(
                    f"[WARN] [hackernews] Skipping invalid hit: {e}",
                    file=sys.stderr,
                )
                skipped += 1
                continue

        print(
            f"[HN] Fetched {len(articles)} articles "
            f"({skipped} skipped — no URL or invalid)"
        )

    except httpx.TimeoutException:
        print("[ERROR] [hackernews] Request timed out after 15s", file=sys.stderr)
    except httpx.HTTPStatusError as e:
        print(
            f"[ERROR] [hackernews] HTTP {e.response.status_code}: {e.response.url}",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"[ERROR] [hackernews] Unexpected error: {type(e).__name__}: {e}",
            file=sys.stderr,
        )

    return articles
