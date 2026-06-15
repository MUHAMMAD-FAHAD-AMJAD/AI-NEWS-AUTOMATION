"""
orchestrator/llm/openrouter_provider.py
-----------------------------------------
OpenRouter LLM provider — tries two free models in sequence:
  1. meta-llama/llama-3.3-70b-instruct:free
  2. mistralai/mistral-small-3.2-24b-instruct:free

Uses openai-compatible client with OpenRouter base URL.
Adds required HTTP-Referer and X-Title headers per OpenRouter spec.

Returns None on any failure — never raises to caller.

SECURITY:
- Never log article title, content, or URL
- Never log API key or partial key
- Never log LLM response content
- Only log: provider name, model slug, failure type
"""

import sys
from typing import Optional

from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError

from orchestrator.llm.parser import parse_llm_response
from orchestrator.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_TEMPERATURE = 0.4
_MAX_TOKENS = 500
_TIMEOUT = 30.0

# Models tried in order — both are free tier on OpenRouter
_MODELS = [
    ("meta-llama/llama-3.3-70b-instruct:free", "openrouter_llama"),
    ("mistralai/mistral-small-3.2-24b-instruct:free", "openrouter_mistral"),
]


async def _try_model(
    client: AsyncOpenAI,
    model: str,
    provider_name: str,
    article: Article,
) -> Optional[SummaryResult]:
    """
    Attempt summarization with a single OpenRouter model.
    Returns None on any failure.
    """
    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(article)},
            ],
        )

        response_text = response.choices[0].message.content or ""
        result = parse_llm_response(response_text)
        result.llm_provider = provider_name
        return result

    except APITimeoutError:
        print(
            f"[LLM] [{provider_name}] Timeout after {_TIMEOUT}s",
            file=sys.stderr,
        )
        return None

    except APIStatusError as e:
        print(
            f"[LLM] [{provider_name}] API error: HTTP {e.status_code}",
            file=sys.stderr,
        )
        return None

    except APIConnectionError:
        print(
            f"[LLM] [{provider_name}] Connection error",
            file=sys.stderr,
        )
        return None

    except ValueError:
        print(
            f"[LLM] [{provider_name}] Parse error: ValueError",
            file=sys.stderr,
        )
        return None

    except Exception as e:
        print(
            f"[LLM] [{provider_name}] Unexpected error: {type(e).__name__}",
            file=sys.stderr,
        )
        return None


async def summarize(article: Article, api_key: str) -> Optional[SummaryResult]:
    """
    Summarize an article using OpenRouter free models.

    Tries models in order: llama-3.3-70b-instruct:free →
    mistral-small-3.2-24b-instruct:free.

    Args:
        article: Article to summarize.
        api_key: OpenRouter API key (from config.openrouter_api_key).

    Returns:
        SummaryResult from first successful model, None if all fail.
    """
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            timeout=_TIMEOUT,
            default_headers={
                "HTTP-Referer": "newsbot/1.0",
                "X-Title": "AI News Bot",
            },
        )
    except Exception as e:
        print(
            f"[LLM] [openrouter] Client init failed: {type(e).__name__}",
            file=sys.stderr,
        )
        return None

    for model_slug, provider_name in _MODELS:
        result = await _try_model(client, model_slug, provider_name, article)
        if result is not None:
            return result
        # Log and try next model — no delay needed within same provider

    return None
