"""
orchestrator/llm/raw_fallback.py
----------------------------------
Raw RSS fallback summarizer — used when ALL LLM providers fail.

This function NEVER fails. It always returns a SummaryResult.
It uses the article's existing title and description (already HTML-stripped
by the fetcher) to build a minimal but valid summary.

Per 04-MESSAGE-FORMAT.md §3:
  - Strip HTML from description (already done by fetcher, but guard again)
  - Truncate at 800 chars at last complete sentence
  - Append "..."
  - Static conclusion: "This is a developing story. Stay tuned for full analysis."
  - Sets used_raw_fallback=True, llm_provider='raw'
"""

import re
from typing import Optional

from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


_MAX_DESC_CHARS = 800
_STATIC_CONCLUSION = "This is a developing story. Stay tuned for full analysis."

PROVIDER_NAME = "raw"


def _strip_html(text: str) -> str:
    """Strip HTML tags using regex (no BS4 dependency in this path)."""
    if not text:
        return ""
    if "<" not in text:
        return " ".join(text.split())
    clean = re.sub(r"<[^>]+>", " ", text)
    return " ".join(clean.split())


def _truncate_at_sentence(text: str, max_chars: int = _MAX_DESC_CHARS) -> str:
    """
    Truncate text to max_chars at the last complete sentence boundary.
    A sentence ends with '.', '!', or '?'.
    Appends '...' if truncation occurred.
    """
    if len(text) <= max_chars:
        return text

    # Truncate to max_chars first
    truncated = text[:max_chars]

    # Find the last sentence-ending punctuation
    last_period = max(
        truncated.rfind("."),
        truncated.rfind("!"),
        truncated.rfind("?"),
    )

    if last_period > 0:
        # Cut at last complete sentence
        return truncated[: last_period + 1] + "..."
    else:
        # No sentence boundary found — cut at last word boundary
        last_space = truncated.rfind(" ")
        if last_space > 0:
            return truncated[:last_space] + "..."
        return truncated + "..."


def summarize(article: Article) -> SummaryResult:
    """
    Build a raw RSS summary from article title and description.

    This is the guaranteed last-resort fallback. It NEVER raises.
    Always returns a valid SummaryResult.

    Args:
        article: Article to summarize.

    Returns:
        SummaryResult with used_raw_fallback=True and llm_provider='raw'.
    """
    # Strip HTML from description (guard — fetcher already does this)
    clean_description = _strip_html(article.description or "")

    # Truncate at last complete sentence before 800 chars
    description = _truncate_at_sentence(clean_description, _MAX_DESC_CHARS)

    # Headline: article title in ALL CAPS
    headline = article.title.upper() if article.title else "NEWS UPDATE"

    return SummaryResult(
        headline=headline,
        paragraph_1=description or article.title,
        paragraph_2="",
        paragraph_3="",
        point_1="",
        point_2="",
        point_3="",
        point_4=None,
        point_5="",
        conclusion=_STATIC_CONCLUSION,
        llm_provider=PROVIDER_NAME,
        used_raw_fallback=True,
    )
