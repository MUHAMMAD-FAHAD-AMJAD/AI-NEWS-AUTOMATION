"""
orchestrator/formatter/message.py
-----------------------------------
WhatsApp message builder and validator.

Implements the EXACT template from 04-MESSAGE-FORMAT.md §7.
Validates against all 7 quality checks from §8.

Functions:
    build_message(summary)          → Formatted LLM-based WhatsApp post
    build_fallback_message(article) → Formatted raw RSS WhatsApp post
    validate_message(message)       → Runs all 7 quality checks; fixes or logs issues

WhatsApp hard limit: 4,096 characters per caption.
Target length:       ~2,200 characters (leaves comfortable headroom).

SECURITY:
- No URLs are ever included in any message (spec requirement)
- No source names are ever included
- No hashtags
"""

import re
import sys
from typing import Optional

from bs4 import BeautifulSoup

from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


# WhatsApp character limit for image captions
_WA_MAX_CHARS = 4096
# Static fallback conclusion per 04-MESSAGE-FORMAT.md §3
_FALLBACK_CONCLUSION = "This is a developing story. Stay tuned for full analysis."


# ------------------------------------------------------------------ #
# Primary Message Builder (LLM path)                                  #
# ------------------------------------------------------------------ #

def build_message(summary: SummaryResult) -> str:
    """
    Assemble the locked WhatsApp message template from a SummaryResult.

    Uses the EXACT template from 04-MESSAGE-FORMAT.md §7.
    Hard-capped at 4,096 chars — truncates conclusion if needed.

    Args:
        summary: Populated SummaryResult from LLM or raw fallback.

    Returns:
        str: Formatted WhatsApp message string.
    """
    parts = []

    # Headline
    parts.append(f"📰 *{summary.headline}*")
    parts.append("")

    # Summary section
    parts.append("📋 *Summary:*")
    parts.append(summary.paragraph_1)
    parts.append("")

    if summary.paragraph_2:
        parts.append(summary.paragraph_2)
        parts.append("")

    if summary.paragraph_3:
        parts.append(summary.paragraph_3)
        parts.append("")

    # Bullet points — only include non-empty, non-null points
    parts.append("*🔑 What Actually Happened:*")
    for point in [
        summary.point_1,
        summary.point_2,
        summary.point_3,
        summary.point_4,
        summary.point_5,
    ]:
        if point and point not in ("N/A", "None", ""):
            parts.append(f"- {point}")
    parts.append("")

    # Conclusion
    parts.append("*💡 Conclusion:*")
    parts.append(summary.conclusion or _FALLBACK_CONCLUSION)

    message = "\n".join(parts)

    # Hard cap at 4,096 chars — truncate conclusion to fit
    if len(message) > _WA_MAX_CHARS:
        overhead = len(message) - _WA_MAX_CHARS
        conclusion = summary.conclusion or _FALLBACK_CONCLUSION
        if len(conclusion) > overhead + 3:
            truncated_conclusion = conclusion[: len(conclusion) - overhead - 3] + "..."
        else:
            truncated_conclusion = "..."
        parts[-1] = truncated_conclusion
        message = "\n".join(parts)

    return message


# ------------------------------------------------------------------ #
# Fallback Message Builder (Raw RSS path)                             #
# ------------------------------------------------------------------ #

def build_fallback_message(article: Article) -> str:
    """
    Build a raw RSS fallback post when all LLMs fail.

    Per 04-MESSAGE-FORMAT.md §3:
    - Strip HTML from description
    - Truncate at 800 chars at last complete sentence + "..."
    - Static conclusion

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

    clean_desc = " ".join(clean_desc.split())  # Normalize whitespace

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

    headline = article.title.upper()

    return (
        f"📰 *{headline}*\n\n"
        f"📋 *Summary:*\n"
        f"{clean_desc}\n\n"
        f"*💡 Conclusion:*\n"
        f"{_FALLBACK_CONCLUSION}"
    )


# ------------------------------------------------------------------ #
# Message Validator — 7 quality checks from §8                       #
# ------------------------------------------------------------------ #

def validate_message(message: str, article: Optional[Article] = None) -> str:
    """
    Run all 7 quality checks from 04-MESSAGE-FORMAT.md §8.

    Checks and their fix actions:
      1. Not empty (len > 100)         → Use fallback static text if too short
      2. Headline present (starts 📰)  → Re-prepend headline from article title
      3. Within 4,096 char limit        → Truncate at last sentence
      4. No URLs (no 'http')            → Strip all http URLs
      5. No source names                → Strip known source names
      6. No hashtags (no '#')           → Strip all # words
      7. Has conclusion (💡 present)   → Append static conclusion

    Args:
        message: The formatted message string to validate.
        article: Optional article — used for fallback headline if needed.

    Returns:
        str: Validated and cleaned message string.
    """
    # Check 1: Not empty
    if len(message.strip()) < 100:
        print("[FORMATTER] WARN: Message too short — using static fallback", file=sys.stderr)
        fallback = (
            "📰 *AI NEWS UPDATE*\n\n"
            "📋 *Summary:*\n"
            "An important AI development was reported today.\n\n"
            "*💡 Conclusion:*\n"
            f"{_FALLBACK_CONCLUSION}"
        )
        message = fallback

    # Check 4: No URLs — strip any http links that snuck in
    if "http" in message:
        # Remove bare URLs (http://... or https://...)
        message = re.sub(r"https?://\S+", "", message)
        # Clean up resulting double spaces
        message = re.sub(r"  +", " ", message)
        print("[FORMATTER] WARN: URLs stripped from message", file=sys.stderr)

    # Check 6: No hashtags
    if "#" in message:
        message = re.sub(r"#\w+", "", message)
        message = re.sub(r"  +", " ", message)
        print("[FORMATTER] WARN: Hashtags stripped from message", file=sys.stderr)

    # Check 5: No known source names (per 04-MESSAGE-FORMAT.md §4.3)
    _BANNED_SOURCES = [
        "TechCrunch", "The Verge", "Wired", "Ars Technica",
        "VentureBeat", "MIT Technology Review", "Bloomberg",
        "Reuters", "BBC", "CNN", "Forbes", "Business Insider",
        "Hacker News", "Reddit", "hackernews",
    ]
    for source in _BANNED_SOURCES:
        if source.lower() in message.lower():
            # Case-insensitive removal of the source name
            message = re.sub(re.escape(source), "", message, flags=re.IGNORECASE)
            print(
                f"[FORMATTER] WARN: Source name '{source}' removed from message",
                file=sys.stderr,
            )

    # Check 2: Headline present (starts with 📰)
    if not message.strip().startswith("📰"):
        headline = ""
        if article:
            headline = f"📰 *{article.title.upper()}*\n\n"
        else:
            headline = "📰 *AI NEWS UPDATE*\n\n"
        message = headline + message
        print("[FORMATTER] WARN: Missing headline — prepended from article", file=sys.stderr)

    # Check 7: Has conclusion (💡 present)
    if "💡" not in message:
        message = message.rstrip() + f"\n\n*💡 Conclusion:*\n{_FALLBACK_CONCLUSION}"
        print("[FORMATTER] WARN: Missing conclusion — static conclusion appended", file=sys.stderr)

    # Check 3: Within 4,096 char limit (must be last — after all modifications)
    if len(message) > _WA_MAX_CHARS:
        # Find last sentence boundary before the limit
        truncated = message[:_WA_MAX_CHARS - 3]
        last_period = max(
            truncated.rfind("."),
            truncated.rfind("!"),
            truncated.rfind("?"),
        )
        if last_period > _WA_MAX_CHARS // 2:
            message = truncated[:last_period + 1] + "..."
        else:
            message = truncated + "..."
        print(
            f"[FORMATTER] WARN: Message exceeded {_WA_MAX_CHARS} chars — truncated",
            file=sys.stderr,
        )

    return message
