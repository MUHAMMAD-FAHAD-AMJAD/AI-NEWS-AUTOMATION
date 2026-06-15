"""
orchestrator/filter/keywords.py
---------------------------------
Keyword filter — ensures only AI/tech-relevant articles pass through.

Logic (per 03-APP-FLOW.md Step 5 and 06-IMPLEMENTATION-PLAN.md §3.2):
  1. Check title + description (lowercased) against EXCLUDE list first
     → Any EXCLUDE match = immediate reject (unrelated content)
  2. Check against INCLUDE list
     → Any INCLUDE match = pass (relevant AI/tech content)
  3. Neither INCLUDE nor EXCLUDE matched = reject (not clearly AI/tech)

Both lists are exact substring matches — no regex, no stemming.
This is intentional: fast, predictable, auditable.
"""

from orchestrator.models.article import Article


# ------------------------------------------------------------------ #
# Keyword Lists — locked per 06-IMPLEMENTATION-PLAN.md §3.2          #
# ------------------------------------------------------------------ #

INCLUDE: list[str] = [
    "ai",
    "llm",
    "gpt",
    "claude",
    "gemini",
    "model",
    "agent",
    "startup",
    "funding",
    "open source",
    "anthropic",
    "openai",
    "deepmind",
    "mistral",
    "hugging face",
    "machine learning",
    "neural",
    "transformer",
    "generative",
    "chatbot",
    "copilot",
    "nvidia",
    "inference",
    "fine-tun",           # matches fine-tuning, fine-tuned
    "foundation model",
    "large language",
    "multimodal",
    "diffusion",
    "reinforcement",
    "robotics",
    "autonomous",
]

EXCLUDE: list[str] = [
    "celebrity",
    "sports",
    "nfl",
    "nba",
    "fifa",
    "soccer",
    "entertainment",
    "music video",
    "box office",
    "election",
    "vote",
    "political party",
    "congress bill",
    "senate",
    "gossip",
    "dating",
    "romance",
]


# ------------------------------------------------------------------ #
# Filter functions                                                     #
# ------------------------------------------------------------------ #

def passes_keyword_filter(article: Article) -> bool:
    """
    Return True if the article is relevant AI/tech content.

    Checks: (title + " " + description).lower() against EXCLUDE then INCLUDE.

    Args:
        article: Article to evaluate.

    Returns:
        bool: True if article passes (is AI/tech relevant), False otherwise.
    """
    text = (article.title + " " + article.description).lower()

    # EXCLUDE check first — fastest rejection
    if any(kw in text for kw in EXCLUDE):
        return False

    # INCLUDE check — must match at least one keyword
    if any(kw in text for kw in INCLUDE):
        return True

    # No match either way → reject (not clearly AI/tech)
    return False


def filter_by_keywords(
    articles: list[Article],
) -> tuple[list[Article], list[Article]]:
    """
    Partition articles into keyword-relevant and rejected.

    Args:
        articles: List of articles to filter.

    Returns:
        Tuple of (passed_articles, rejected_articles).
        Both lists preserve input order.
    """
    passed = []
    rejected = []
    for article in articles:
        if passes_keyword_filter(article):
            passed.append(article)
        else:
            rejected.append(article)

    return passed, rejected


def get_rejection_reason(article: Article) -> str:
    """
    Explain why an article was rejected — useful for debugging.

    Returns:
        str: Human-readable reason for rejection.
    """
    text = (article.title + " " + article.description).lower()

    for kw in EXCLUDE:
        if kw in text:
            return f"EXCLUDE keyword matched: '{kw}'"

    if not any(kw in text for kw in INCLUDE):
        return "No INCLUDE keyword found in title or description"

    return "PASSED"
