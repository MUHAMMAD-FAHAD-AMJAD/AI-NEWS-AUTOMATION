"""
orchestrator/fetcher/reddit.py
-------------------------------
Reddit r/artificial top posts fetcher via Reddit's public JSON API.

No API key required. Uses the unofficial Reddit JSON endpoint:
  https://www.reddit.com/r/artificial/top.json?limit=10&t=day

Design decisions:
- User-Agent: newsbot/1.0 (Reddit requires a non-browser UA or returns 429)
- httpx.AsyncClient with explicit timeout=15s
- Returns empty list on ANY failure — never raises to caller
- Filters out self-posts with no external URL (reddit.com/r/... links)
- Uses post's 'selftext' as description for self-posts that do have content

SECURITY:
- Only title and source are logged to stdout
- Subreddit content (selftext) is stored but never printed
"""

import sys
from datetime import datetime, timezone
from typing import List

import httpx

from orchestrator.models.article import Article


_REDDIT_URL = (
    "https://www.reddit.com/r/artificial/top.json"
    "?limit=10"
    "&t=day"
)

# Reddit requires a descriptive User-Agent or returns 429/403
_HEADERS = {
    "User-Agent": "newsbot/1.0 (automated AI news aggregator)",
    "Accept": "application/json",
}

_TIMEOUT_SECONDS = 15


async def fetch_reddit() -> List[Article]:
    """
    Fetch top posts from r/artificial (past 24 hours) via Reddit JSON API.

    Returns:
        List[Article]: Up to 10 Reddit posts with external links.
                       Returns [] on any network or parse failure.
    """
    articles: List[Article] = []

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(_REDDIT_URL)
            resp.raise_for_status()
            data = resp.json()

        children = data.get("data", {}).get("children", [])
        skipped = 0

        for child in children:
            try:
                post = child.get("data", {})

                # --- URL ---
                # Reddit posts have both a permalink and an external url
                # 'url' is the external link for link posts
                # For self-posts, 'url' is the reddit.com permalink
                url = post.get("url", "") or ""

                # Skip pure self-posts (url points back to reddit.com)
                if not url or not url.startswith("http"):
                    skipped += 1
                    continue

                # If this is a self-post (url = reddit.com/r/...) skip it —
                # the post IS on reddit, not an external article
                if "reddit.com/r/" in url and "/comments/" in url:
                    skipped += 1
                    continue

                # --- Title ---
                title = (post.get("title", "") or "").strip()
                if not title:
                    skipped += 1
                    continue

                # --- Description ---
                # Use selftext for self-posts; for link posts it's usually empty
                selftext = (post.get("selftext", "") or "").strip()
                description = selftext if selftext else title

                # --- Date ---
                # 'created_utc' is a Unix timestamp (float, UTC)
                created_utc = post.get("created_utc")
                if created_utc is None:
                    skipped += 1
                    continue

                published_at = datetime.fromtimestamp(
                    float(created_utc), tz=timezone.utc
                )

                article = Article(
                    title=title,
                    url=url,
                    description=description,
                    published_at=published_at,
                    source="reddit",
                )
                articles.append(article)

            except (ValueError, KeyError, TypeError) as e:
                print(
                    f"[WARN] [reddit] Skipping invalid post: {e}",
                    file=sys.stderr,
                )
                skipped += 1
                continue

        print(
            f"[Reddit] Fetched {len(articles)} articles "
            f"({skipped} skipped — self-posts or invalid)"
        )

    except httpx.TimeoutException:
        print("[ERROR] [reddit] Request timed out after 15s", file=sys.stderr)
    except httpx.HTTPStatusError as e:
        print(
            f"[ERROR] [reddit] HTTP {e.response.status_code}: {e.response.url}",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"[ERROR] [reddit] Unexpected error: {type(e).__name__}: {e}",
            file=sys.stderr,
        )

    return articles
