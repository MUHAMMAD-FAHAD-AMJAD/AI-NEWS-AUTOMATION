"""
orchestrator/formatter/message.py
-----------------------------------
WhatsApp message builder and validator — enterprise intelligence brief format.

Implements the two-block premium layout:
    _*METRIC BRIEF // [CATEGORY]*_
    ━━━━━━━━━━━━━━━━━━━━━━━━━
    *THE UPDATE*
    [update_block]

    *STRATEGIC IMPLICATIONS*
    [strategic_implications]

Functions:
    build_message(summary)          → Formatted LLM-based WhatsApp brief
    build_fallback_message(article) → Formatted raw RSS WhatsApp brief
    validate_message(message)       → Quality checks; fixes or logs issues

WhatsApp hard limit: 4,096 characters per caption.

SECURITY:
- No URLs are ever included in any message (spec requirement)
- No source names are ever included
- No hashtags, no emojis in content
"""

import re
import sys
from typing import Optional

from bs4 import BeautifulSoup

from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


# WhatsApp character limit for image captions
_WA_MAX_CHARS = 4096

# Divider line used in the premium layout
_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━"

# Static category for raw fallback posts
_FALLBACK_CATEGORY = "BREAKING"


# ------------------------------------------------------------------ #
# Primary Message Builder (LLM path)                                  #
# ------------------------------------------------------------------ #

def build_message(summary: SummaryResult) -> str:
    """
    Assemble the enterprise intelligence brief WhatsApp message.

    Layout:
        _*METRIC BRIEF // {category}*_
        ━━━━━━━━━━━━━━━━━━━━━━━━━
        *THE UPDATE*
        {update_block}

        *STRATEGIC IMPLICATIONS*
        {strategic_implications}

    Hard-capped at 4,096 chars — truncates strategic_implications first,
    then update_block if necessary.

    Args:
        summary: Populated SummaryResult from LLM or raw fallback.

    Returns:
        str: Formatted WhatsApp message string.
    """
    parts = [
        f"_*METRIC BRIEF // {summary.category}*_",
        _DIVIDER,
        "*THE UPDATE*",
        summary.update_block,
    ]

    if summary.strategic_implications and summary.strategic_implications.strip():
        parts.append("")
        parts.append("*STRATEGIC IMPLICATIONS*")
        parts.append(summary.strategic_implications)

    message = "\n".join(parts)

    # Hard cap at 4,096 chars
    if len(message) > _WA_MAX_CHARS:
        message = _truncate_to_limit(message, _WA_MAX_CHARS)

    return message


# ------------------------------------------------------------------ #
# Fallback Message Builder (Raw RSS path)                             #
# ------------------------------------------------------------------ #

def build_fallback_message(article: Article) -> str:
    """
    Build a raw RSS fallback brief when all LLMs fail.

    Uses article title as category label, stripped description as update block.
    Strategic implications section is omitted when empty.

    Args:
        article: The Article to build a fallback post for.

    Returns:
        str: Formatted WhatsApp fallback message string.
    """
    # Strip HTML from description
    raw_desc = article.description or ""
    if "<" in raw_desc:
        try:
            clean_desc = BeautifulSoup(raw_desc, "lxml").get_text(separator=" ")
        except Exception:
            clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
    else:
        clean_desc = raw_desc

    clean_desc = " ".join(clean_desc.split())

    # Truncate at 800 chars at last complete sentence
    if len(clean_desc) > 800:
        truncated = clean_desc[:800]
        last_period = max(
            truncated.rfind("."),
            truncated.rfind("!"),
            truncated.rfind("?"),
        )
        if last_period > 0:
            clean_desc = truncated[: last_period + 1] + "..."
        else:
            last_space = truncated.rfind(" ")
            clean_desc = truncated[:last_space] + "..." if last_space > 0 else truncated + "..."

    # Use article title words as a category hint — uppercase, max 4 words
    title_words = article.title.upper().split()
    category = " ".join(title_words[:4]) if title_words else _FALLBACK_CATEGORY

    return (
        f"_*METRIC BRIEF // {category}*_\n"
        f"{_DIVIDER}\n"
        f"*THE UPDATE*\n"
        f"{clean_desc}"
    )


# ------------------------------------------------------------------ #
# Truncation helper                                                    #
# ------------------------------------------------------------------ #

def _truncate_to_limit(message: str, limit: int) -> str:
    """
    Truncate message to limit chars at the last sentence boundary.
    Appends '...' if truncation occurs.
    """
    truncated = message[: limit - 3]
    last_period = max(
        truncated.rfind("."),
        truncated.rfind("!"),
        truncated.rfind("?"),
    )
    if last_period > limit // 2:
        return truncated[:last_period + 1] + "..."
    return truncated + "..."


# ------------------------------------------------------------------ #
# Message Validator                                                    #
# ------------------------------------------------------------------ #

def validate_message(message: str, article: Optional[Article] = None) -> str:
    """
    Run quality checks and auto-correct the formatted message.

    Checks:
      1. Not empty (len > 50)               → Replace with static fallback
      2. Has METRIC BRIEF header             → Re-prepend if missing
      3. Within 4,096 char limit             → Truncate at last sentence
      4. No URLs (no 'http')                 → Strip all http URLs
      5. No source names                     → Strip known publication names
      6. No hashtags (no '#')               → Strip all # words

    Args:
        message: The formatted message string to validate.
        article: Optional article — used for fallback header if needed.

    Returns:
        str: Validated and cleaned message string.
    """
    # Check 1: Not empty
    if len(message.strip()) < 50:
        print("[FORMATTER] WARN: Message too short — using static fallback", file=sys.stderr)
        category = _FALLBACK_CATEGORY
        if article:
            words = article.title.upper().split()
            category = " ".join(words[:4]) if words else _FALLBACK_CATEGORY
        message = (
            f"_*METRIC BRIEF // {category}*_\n"
            f"{_DIVIDER}\n"
            f"*THE UPDATE*\n"
            f"An AI development was reported. Full briefing unavailable."
        )

    # Check 4: No URLs
    if "http" in message:
        message = re.sub(r"https?://\S+", "", message)
        message = re.sub(r"  +", " ", message)
        print("[FORMATTER] WARN: URLs stripped from message", file=sys.stderr)

    # Check 6: No hashtags
    if "#" in message:
        message = re.sub(r"#\w+", "", message)
        message = re.sub(r"  +", " ", message)
        print("[FORMATTER] WARN: Hashtags stripped from message", file=sys.stderr)

    # Check 5: No known source names
    _BANNED_SOURCES = [
        "TechCrunch", "The Verge", "Wired", "Ars Technica",
        "VentureBeat", "MIT Technology Review", "Bloomberg",
        "Reuters", "BBC", "CNN", "Forbes", "Business Insider",
        "Hacker News", "Reddit", "hackernews",
    ]
    for source in _BANNED_SOURCES:
        if source.lower() in message.lower():
            message = re.sub(re.escape(source), "", message, flags=re.IGNORECASE)
            print(
                f"[FORMATTER] WARN: Source name '{source}' removed from message",
                file=sys.stderr,
            )

    # Check 2: Has METRIC BRIEF header
    if "_*METRIC BRIEF" not in message:
        category = _FALLBACK_CATEGORY
        if article:
            words = article.title.upper().split()
            category = " ".join(words[:4]) if words else _FALLBACK_CATEGORY
        header = f"_*METRIC BRIEF // {category}*_\n{_DIVIDER}\n"
        message = header + message
        print("[FORMATTER] WARN: Missing METRIC BRIEF header — prepended", file=sys.stderr)

    # Check 3: Within 4,096 char limit (must be last — after all modifications)
    if len(message) > _WA_MAX_CHARS:
        message = _truncate_to_limit(message, _WA_MAX_CHARS)
        print(
            f"[FORMATTER] WARN: Message exceeded {_WA_MAX_CHARS} chars — truncated",
            file=sys.stderr,
        )

    return message
