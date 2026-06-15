"""
orchestrator/extractor/og_image.py
------------------------------------
OG Image extractor — fetches an article URL and extracts the Open Graph
image (og:image) for use as a WhatsApp post thumbnail.

Design decisions (per 06-IMPLEMENTATION-PLAN.md §4.1):
- async httpx.AsyncClient with timeout=15s and follow_redirects=True
- Parses og:image first, falls back to twitter:image
- Validates returned URL starts with 'http' before returning
- Returns None on ANY failure — never raises to caller
- Never logs the article URL in error messages (SECURITY)

User-Agent: newsbot/1.0 (identifies the bot to servers)
"""

import sys
from typing import Optional

import httpx
from bs4 import BeautifulSoup


# Browser-like headers to avoid 403s from media sites.
# User-Agent is set to newsbot/1.0 per spec.
_HEADERS = {
    "User-Agent": "newsbot/1.0 (automated AI news aggregator)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "close",
}

_TIMEOUT_SECONDS = 15


async def extract_og_image(url: str) -> Optional[str]:
    """
    Fetch an article page and extract its Open Graph image URL.

    Extraction priority:
      1. <meta property="og:image" content="...">
      2. <meta name="twitter:image" content="...">

    Both must return an http(s) URL — otherwise treated as missing.

    Args:
        url: The article URL to fetch. Not logged in error messages.

    Returns:
        str:  A valid https:// image URL if found.
        None: On any failure (timeout, HTTP error, no tag, invalid URL).
              This function NEVER raises.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(url)

            if resp.status_code != 200:
                # Non-200 → no image, but not an error worth logging
                return None

            html = resp.text

        # Parse HTML for OG/Twitter image tags
        soup = BeautifulSoup(html, "lxml")

        # --- Priority 1: og:image ---
        og_tag = soup.find("meta", property="og:image")
        if og_tag:
            og_url = og_tag.get("content", "").strip()
            if og_url and og_url.startswith("http"):
                return og_url

        # --- Priority 2: twitter:image ---
        tw_tag = soup.find("meta", attrs={"name": "twitter:image"})
        if tw_tag:
            tw_url = tw_tag.get("content", "").strip()
            if tw_url and tw_url.startswith("http"):
                return tw_url

        # Also try twitter:image:src (alternate form)
        tw_src_tag = soup.find("meta", attrs={"name": "twitter:image:src"})
        if tw_src_tag:
            tw_src_url = tw_src_tag.get("content", "").strip()
            if tw_src_url and tw_src_url.startswith("http"):
                return tw_src_url

        # No valid image tag found
        return None

    except httpx.TimeoutException:
        # Timeout is expected for slow sites — log component only, not URL
        print("[WARN] [extractor] OG image request timed out", file=sys.stderr)
        return None

    except httpx.TooManyRedirects:
        print("[WARN] [extractor] OG image: too many redirects", file=sys.stderr)
        return None

    except httpx.HTTPStatusError:
        # raise_for_status() not called — this shouldn't trigger, but guard anyway
        return None

    except Exception as e:
        # Catch-all: never crash the pipeline over a missing thumbnail
        print(
            f"[WARN] [extractor] OG image extraction failed: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None
