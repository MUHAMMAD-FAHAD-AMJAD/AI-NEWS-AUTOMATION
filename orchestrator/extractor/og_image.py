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

Fixes applied 2026-06-16:
- Rotating User-Agent pool — GitHub Actions IP was being blocked by news
  sites with bot detection (returning 403 or 429 to newsbot/1.0 agent)
- Explicit debug logging of HTTP status and found meta tags
- rss_image_url fallback is handled in main.py (not here)
"""

import re
import random
import sys
from typing import Optional

import httpx
from bs4 import BeautifulSoup


# ------------------------------------------------------------------ #
# Rotating User-Agent pool                                             #
# Real browser user agents to avoid 403/429 from media sites          #
# ------------------------------------------------------------------ #

_USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

_TIMEOUT_SECONDS = 15


def _get_headers() -> dict:
    """Return full browser-like headers with a randomly chosen User-Agent.
    
    Full Sec-Fetch-* headers are required for some sites (e.g. MITTR, VentureBeat)
    that serve different content based on whether the request looks like a real browser.
    """
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "no-cache",
        "Referer": "https://www.google.com/",
    }


async def extract_og_image(url: str) -> Optional[str]:
    """
    Fetch an article page and extract its Open Graph image URL.

    Extraction priority:
      1. <meta property="og:image" content="...">
      2. <meta name="twitter:image" content="...">
      3. <meta name="twitter:image:src" content="...">

    All must return an http(s) URL — otherwise treated as missing.

    Debug logging added (2026-06-16):
    - Logs HTTP status code received
    - Logs which meta tag was found (if any)
    - Logs reason for failure if no image found

    Args:
        url: The article URL to fetch. Domain logged, full URL not.

    Returns:
        str:  A valid https:// image URL if found.
        None: On any failure (timeout, HTTP error, no tag, invalid URL).
              This function NEVER raises.
    """
    # Log domain only for debugging (not full URL — security)
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
    except Exception:
        domain = "[unknown]"

    print(f"[IMAGE] Fetching OG image from: {domain}")

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=_get_headers(),
        ) as client:
            resp = await client.get(url)

        print(f"[IMAGE] HTTP {resp.status_code} from {domain}")

        if resp.status_code == 403:
            print(f"[IMAGE] 403 Forbidden — site is blocking scrapers at {domain}", file=sys.stderr)
            return None

        if resp.status_code == 429:
            print(f"[IMAGE] 429 Rate limited by {domain}", file=sys.stderr)
            return None

        if resp.status_code != 200:
            print(f"[IMAGE] Non-200 ({resp.status_code}) from {domain} — no image", file=sys.stderr)
            return None

        # ------------------------------------------------------------------ #
        # Parse HTML for OG/Twitter image tags                                #
        # Two-pass approach:                                                  #
        #   Pass 1: BeautifulSoup with lxml (fast)                           #
        #   Pass 2: Regex on raw HTML (lxml sometimes strips the non-standard #
        #           `property` attribute from <meta> tags since it is an OGP  #
        #           extension and not part of the HTML5 spec)                 #
        # ------------------------------------------------------------------ #
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        # Log all og:/twitter: meta tags found by BS4 (debugging)
        meta_props = [
            t.get("property") or t.get("name")
            for t in soup.find_all("meta")
            if t.get("property") or t.get("name")
        ]
        og_related = [p for p in meta_props if p and ("og:" in p or "twitter:" in p)]
        if og_related:
            print(f"[IMAGE] BS4 found meta tags: {og_related[:5]}")
        else:
            print(f"[IMAGE] BS4: no og:/twitter: meta tags found at {domain} — trying regex fallback")

        def _extract_via_bs4() -> Optional[str]:
            """BeautifulSoup pass: find og:image / twitter:image."""
            # Priority 1: og:image
            og_tag = soup.find("meta", property="og:image")
            if og_tag:
                u = og_tag.get("content", "").strip()
                if u and u.startswith("http"):
                    return u
            # Priority 2: twitter:image
            tw_tag = soup.find("meta", attrs={"name": "twitter:image"})
            if tw_tag:
                u = tw_tag.get("content", "").strip()
                if u and u.startswith("http"):
                    return u
            # Priority 3: twitter:image:src
            tw_src = soup.find("meta", attrs={"name": "twitter:image:src"})
            if tw_src:
                u = tw_src.get("content", "").strip()
                if u and u.startswith("http"):
                    return u
            return None

        def _extract_via_regex() -> Optional[str]:
            """Regex pass: search raw HTML for og:image / twitter:image.
            
            Handles both attribute orderings:
              <meta property="og:image" content="URL">
              <meta content="URL" property="og:image">
            lxml strips the non-standard `property` attribute in some HTML5
            documents; regex bypasses the parser entirely.
            """
            patterns = [
                # property first, then content
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                # content first, then property
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                # twitter:image (name attr)
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
            ]
            for pat in patterns:
                m = re.search(pat, html, re.IGNORECASE)
                if m:
                    u = m.group(1).strip()
                    if u and u.startswith("http"):
                        return u
            return None

        # Pass 1: BeautifulSoup
        result = _extract_via_bs4()
        if result:
            print(f"[IMAGE] Found og:image via BS4 at {domain}")
            return result

        # Pass 2: Regex fallback (catches lxml property-stripping bug)
        result = _extract_via_regex()
        if result:
            print(f"[IMAGE] Found og:image via regex fallback at {domain}")
            return result

        print(f"[IMAGE] No valid image meta tag found at {domain}")
        return None

    except httpx.TimeoutException:
        print(f"[WARN] [extractor] OG image request timed out", file=sys.stderr)
        return None

    except httpx.TooManyRedirects:
        print(f"[WARN] [extractor] OG image: too many redirects", file=sys.stderr)
        return None

    except httpx.HTTPStatusError:
        return None

    except Exception as e:
        print(
            f"[WARN] [extractor] OG image extraction failed: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None
