"""
orchestrator/llm/summarizer.py
--------------------------------
LLM fallback chain orchestrator — the single entry point for summarization.

Provider order:
  1. Mistral  (mistral-small-latest)          ← PRIMARY
  2. Groq     (llama-3.3-70b-versatile)       ← SECONDARY
  3. OpenRouter (llama-3.3-70b-instruct:free → mistral-small-3.2-24b:free)
  4. Gemini   (gemini-1.5-flash)
  5. Raw      (always succeeds — no LLM)

Behaviour:
  - Each provider returns SummaryResult or None
  - None → log failure, wait 2s, try next provider
  - First non-None result is returned immediately
  - Raw fallback is the guaranteed final return

SECURITY:
  - Never log article title, content, or URL
  - Never log LLM response content
  - Only log provider name and success/failure status
"""

import asyncio
import sys
from typing import Optional

from orchestrator.llm import (
    gemini_provider,
    groq_provider,
    mistral_provider,
    openrouter_provider,
)
from orchestrator.llm.raw_fallback import summarize as raw_summarize
from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


# Seconds to wait between provider failures before trying the next
_INTER_PROVIDER_DELAY = 2.0


async def summarize_with_fallback(
    article: Article,
    groq_api_key: str,
    mistral_api_key: str,
    openrouter_api_key: str,
    gemini_api_key: str,
) -> SummaryResult:
    """
    Summarize an article using LLM providers in fallback order.

    Tries each provider in sequence. On None response, waits 2 seconds
    then tries the next. If all LLM providers fail, returns raw fallback.
    This function ALWAYS returns a SummaryResult — never None, never raises.

    Args:
        article:            Article to summarize.
        groq_api_key:       Groq API key.
        mistral_api_key:    Mistral API key.
        openrouter_api_key: OpenRouter API key.
        gemini_api_key:     Gemini API key.

    Returns:
        SummaryResult from first successful provider, or raw fallback.
    """

    # Provider chain: list of (coroutine_factory, provider_display_name)
    # Each entry is a callable that returns a coroutine when called
    providers = [
        (
            lambda: mistral_provider.summarize(article, mistral_api_key),
            "mistral",
        ),
        (
            lambda: groq_provider.summarize(article, groq_api_key),
            "groq",
        ),
        (
            lambda: openrouter_provider.summarize(article, openrouter_api_key),
            "openrouter",
        ),
        (
            lambda: gemini_provider.summarize(article, gemini_api_key),
            "gemini",
        ),
    ]

    for i, (provider_fn, provider_name) in enumerate(providers):
        try:
            result: Optional[SummaryResult] = await provider_fn()
        except Exception as e:
            # Belt-and-suspenders: providers should return None not raise,
            # but catch here anyway so the chain is never broken
            print(
                f"[LLM] [{provider_name}] Unexpected raise: {type(e).__name__}",
                file=sys.stderr,
            )
            result = None

        if result is not None:
            print(f"[LLM] Success via {provider_name}")
            return result

        # Provider failed — log and apply delay before next
        print(f"[LLM] {provider_name} failed — trying next provider")

        # 2-second delay between provider switches (not after last failure)
        if i < len(providers) - 1:
            await asyncio.sleep(_INTER_PROVIDER_DELAY)

    # All LLM providers exhausted — use guaranteed raw fallback
    print("[LLM] All providers failed. Using raw fallback.")
    return raw_summarize(article)
