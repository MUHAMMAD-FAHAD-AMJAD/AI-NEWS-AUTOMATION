"""
orchestrator/llm/mistral_provider.py
--------------------------------------
Mistral LLM provider — calls mistral-small-latest via Mistral AI SDK.

Returns None on any failure — never raises to caller.

SECURITY:
- Never log article title, content, or URL
- Never log API key or partial key
- Never log LLM response content
- Only log: provider name + failure type
"""

import sys
from typing import Optional

from orchestrator.llm.parser import parse_llm_response
from orchestrator.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


_MODEL = "mistral-small-latest"
_TEMPERATURE = 0.4
_MAX_TOKENS = 500
_TIMEOUT = 30

PROVIDER_NAME = "mistral"


async def summarize(article: Article, api_key: str) -> Optional[SummaryResult]:
    """
    Summarize an article using Mistral's mistral-small-latest.

    Args:
        article: Article to summarize.
        api_key: Mistral API key (from config.mistral_api_key).

    Returns:
        SummaryResult on success, None on any failure.
    """
    try:
        from mistralai import Mistral
        from mistralai.models import SDKError

        client = Mistral(api_key=api_key, timeout_ms=_TIMEOUT * 1000)

        response = await client.chat.complete_async(
            model=_MODEL,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(article)},
            ],
        )

        response_text = response.choices[0].message.content or ""
        result = parse_llm_response(response_text)
        result.llm_provider = PROVIDER_NAME
        return result

    except ValueError as e:
        # parse_llm_response raised — response didn't have required fields
        print(
            f"[LLM] [{PROVIDER_NAME}] Parse error: {type(e).__name__}",
            file=sys.stderr,
        )
        return None

    except Exception as e:
        # Covers: SDKError, timeout, connection error, rate limit (429), etc.
        # Log only type — never content or key
        status = getattr(e, "status_code", getattr(e, "code", ""))
        status_str = f" HTTP {status}" if status else ""
        print(
            f"[LLM] [{PROVIDER_NAME}] Failed{status_str}: {type(e).__name__}",
            file=sys.stderr,
        )
        return None
