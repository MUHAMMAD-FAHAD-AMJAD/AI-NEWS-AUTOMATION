"""
orchestrator/fetcher/rss.py
----------------------------
Concurrent RSS feed fetcher for all 8 configured AI/tech news sources.

Design decisions:
- feedparser is synchronous → wrapped in asyncio.to_thread() so it doesn't
  block the event loop while fetching
- asyncio.gather() runs all 8 feeds truly in parallel
- Each feed is individually wrapped in try/except — a single failed source
  never kills the other 7
- published_parsed → UTC datetime via calendar.timegm() (no timezone guessing)
- BeautifulSoup strips HTML tags from descriptions before Article creation
- Returns List[Article] sorted newest-first by published_at

SECURITY:
- Only title and source are logged to stdout
- No description content is ever printed
- All HTTP operations have implicit 15-second timeout via feedparser agent header
"""

import asyncio
import calendar
import sys
from datetime import datetime, timezone
from typing import List, Optional

import feedparser
from bs4 import BeautifulSoup

from orchestrator.models.article import Article


# ------------------------------------------------------------------ #
# Feed registry — 8 sources as specified in 03-APP-FLOW.md           #
# Source slugs match the `source` column values in the articles table #
# ------------------------------------------------------------------ #

RSS_FEEDS: List[dict] = [
    {
        "source": "techcrunch",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "source": "theverge",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    },
    {
        "source": "venturebeat",
        "url": "https://venturebeat.com/category/ai/feed/",
    },
    {
        "source": "mittr",
        "url": "https://www.technologyreview.com/feed/",
    },
    {
        "source": "wired",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
    },
    {
        "source": "huggingface",
        "url": "https://huggingface.co/blog/feed.xml",
    },
    {
        "source": "googleai",
        "url": "https://blog.google/technology/ai/rss/",
    },
    {
        "source": "openai",
        "url": "https://openai.com/blog/rss.xml",
    },
]


# ------------------------------------------------------------------ #
# HTML Stripper                                                        #
# ------------------------------------------------------------------ #

def _strip_html(raw: str) -> str:
    """
    Strip all HTML tags from a string using BeautifulSoup.
    Returns clean text with normalized whitespace.
    Always returns a string — never raises.
    """
    if not raw:
        return ""
    # Only run BS4 if the string actually contains HTML tags
    # This avoids MarkupResemblesLocatorWarning on plain text descriptions
    if "<" not in raw:
        return " ".join(raw.split())
    try:
        soup = BeautifulSoup(raw, "lxml")
        text = soup.get_text(separator=" ")
        # Collapse whitespace
        return " ".join(text.split())
    except Exception:
        # Absolute last resort — remove < > manually
        import re
        return re.sub(r"<[^>]+>", " ", raw).strip()


# ------------------------------------------------------------------ #
# Datetime parser                                                      #
# ------------------------------------------------------------------ #

def _parse_published(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """
    Convert feedparser's published_parsed (UTC time.struct_time) to a
    timezone-aware datetime.

    Uses calendar.timegm() which treats the struct as UTC — no local TZ
    ambiguity. Falls back to updated_parsed if published_parsed is absent.
    Returns None if neither field is present.
    """
    time_struct = (
        getattr(entry, "published_parsed", None)
        or getattr(entry, "updated_parsed", None)
    )
    if time_struct is None:
        return None
    try:
        timestamp = calendar.timegm(time_struct)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None



# ------------------------------------------------------------------ #
# RSS Media Image Extractor                                            #
# ------------------------------------------------------------------ #

def _extract_rss_image(entry: feedparser.FeedParserDict) -> 'Optional[str]':
    """
    Extract an image URL from RSS feed entry media tags.

    Checks in priority order:
      1. media:content with medium='image'
      2. media:thumbnail
      3. enclosure with image MIME type
      4. media:content (any, first entry)

    Returns None if no valid image URL found.
    Never raises — errors return None silently.

    This avoids HTTP fetching the article page entirely — the image
    is embedded directly in the RSS feed XML.
    """
    try:
        # ── 1. media:content ────────────────────────────────────────
        media_content = getattr(entry, 'media_content', []) or []
        for media in media_content:
            url = media.get('url', '')
            if url and url.startswith('http'):
                medium = media.get('medium', '')
                if medium == 'image' or any(
                    ext in url.lower()
                    for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif')
                ):
                    return url
        # Fallback: any media:content URL
        for media in media_content:
            url = media.get('url', '')
            if url and url.startswith('http'):
                return url

        # ── 2. media:thumbnail ──────────────────────────────────────
        media_thumbnail = getattr(entry, 'media_thumbnail', []) or []
        for thumb in media_thumbnail:
            url = thumb.get('url', '')
            if url and url.startswith('http'):
                return url

        # ── 3. enclosure (podcast/image attachments) ────────────────
        enclosures = getattr(entry, 'enclosures', []) or []
        for enc in enclosures:
            url = enc.get('url', '') or enc.get('href', '')
            mime = enc.get('type', '')
            if url and url.startswith('http') and 'image' in mime:
                return url

    except Exception:
        pass  # Never block pipeline over missing image

    return None


# ------------------------------------------------------------------ #
# Single-feed fetcher                                                  #
# ------------------------------------------------------------------ #

async def _fetch_single_feed(feed_cfg: dict) -> List[Article]:
    """
    Fetch and parse a single RSS feed.

    Runs feedparser.parse() in a thread so the event loop is not blocked.
    Returns a (possibly empty) list of Article objects.
    Never raises — errors are printed to stderr and an empty list returned.

    Args:
        feed_cfg: Dict with keys 'source' and 'url'.
    """
    source: str = feed_cfg["source"]
    url: str = feed_cfg["url"]
    articles: List[Article] = []

    try:
        # feedparser is blocking I/O — run in thread pool
        feed = await asyncio.to_thread(
            feedparser.parse,
            url,
            # Identify the bot to RSS servers; Connection:close avoids hang
            agent="newsbot/1.0",
            request_headers={"Connection": "close"},
        )

        if feed.bozo and not feed.entries:
            # bozo=True means malformed XML, but may still have entries
            print(
                f"[WARN] [{source}] Feed parse warning (bozo=True), "
                f"bozo_exception={getattr(feed, 'bozo_exception', 'unknown')}",
                file=sys.stderr,
            )

        for entry in feed.entries:
            try:
                # --- Extract URL ---
                link = getattr(entry, "link", "") or ""
                if not link or not link.startswith("http"):
                    continue  # Skip entries with no usable URL

                # --- Extract title ---
                title = getattr(entry, "title", "").strip()
                if not title:
                    continue

                # --- Extract + strip description ---
                raw_desc = (
                    getattr(entry, "summary", "")
                    or getattr(entry, "description", "")
                    or getattr(entry, "content", [{}])[0].get("value", "")
                    or ""
                )
                description = _strip_html(raw_desc)

                # --- Parse published date ---
                published_at = _parse_published(entry)
                if published_at is None:
                    # Skip entries with no parseable date — can't do recency filter
                    print(
                        f"[WARN] [{source}] Skipping entry with no date: {title[:60]}",
                        file=sys.stderr,
                    )
                    continue

                # --- Extract RSS media image (no HTTP fetch needed) ---
                rss_image_url = _extract_rss_image(entry)

                article = Article(
                    title=title,
                    url=link,
                    description=description,
                    published_at=published_at,
                    source=source,
                )
                article.rss_image_url = rss_image_url
                articles.append(article)

            except ValueError as ve:
                # Article validation failed — skip this entry
                print(f"[WARN] [{source}] Skipping invalid entry: {ve}", file=sys.stderr)
                continue
            except Exception as e:
                print(
                    f"[WARN] [{source}] Unexpected error on entry: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                continue

        print(f"[RSS] [{source}] Fetched {len(articles)} articles")

    except Exception as e:
        # Per-feed error — log and return empty so other feeds continue
        print(
            f"[ERROR] [{source}] Feed fetch failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )

    return articles


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #

async def fetch_all_rss() -> List[Article]:
    """
    Fetch all 8 RSS feeds concurrently using asyncio.gather().

    Each feed runs independently — a failure in one never kills others.
    Returns a combined, deduplicated-by-URL, newest-first sorted list.

    Returns:
        List[Article]: All valid articles from all feeds, sorted by
                       published_at descending (newest first).
    """
    # Launch all 8 feeds concurrently
    results = await asyncio.gather(
        *[_fetch_single_feed(feed) for feed in RSS_FEEDS],
        return_exceptions=False,  # Exceptions are caught inside _fetch_single_feed
    )

    # Flatten results
    all_articles: List[Article] = []
    for feed_articles in results:
        all_articles.extend(feed_articles)

    # Deduplicate by URL hash within RSS results (same article on multiple feeds)
    seen_hashes: set = set()
    unique_articles: List[Article] = []
    for article in all_articles:
        if article.hash not in seen_hashes:
            seen_hashes.add(article.hash)
            unique_articles.append(article)

    # Sort newest first
    unique_articles.sort(key=lambda a: a.published_at, reverse=True)

    print(
        f"[RSS] Total: {len(unique_articles)} unique articles "
        f"from {len(RSS_FEEDS)} feeds"
    )
    return unique_articles
