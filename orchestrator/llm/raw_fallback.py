"""
orchestrator/llm/raw_fallback.py
----------------------------------
Raw RSS fallback summarizer — used when ALL LLM providers fail.

This function NEVER fails. It always returns a SummaryResult.
It uses the article's existing title and description (already HTML-stripped
by the fetcher) to build a minimal but valid intelligence brief.

Raw fallback produces:
  - category:               "BREAKING" (static safe default)
  - update_block:           description truncated at 800 chars at last sentence + "..."
  - strategic_implications: "" (empty — no LLM inference available)
  - used_raw_fallback:      True
  - llm_provider:           'raw'
"""

import re

from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


_MAX_DESC_CHARS = 800
_RAW_CATEGORY   = "BREAKING"

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

    truncated = text[:max_chars]
    last_period = max(
        truncated.rfind("."),
        truncated.rfind("!"),
        truncated.rfind("?"),
    )

    if last_period > 0:
        return truncated[: last_period + 1] + "..."
    else:
        last_space = truncated.rfind(" ")
        if last_space > 0:
            return truncated[:last_space] + "..."
        return truncated + "..."


def summarize(article: Article) -> SummaryResult:
    """
    Build a raw RSS intelligence brief from article title and description.

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
    update_block = _truncate_at_sentence(clean_description, _MAX_DESC_CHARS)

    # If description was empty, fall back to article title as the update block
    if not update_block:
        update_block = article.title

    return SummaryResult(
        category=_RAW_CATEGORY,
        update_block=update_block,
        strategic_implications="",
        llm_provider=PROVIDER_NAME,
        used_raw_fallback=True,
    )
