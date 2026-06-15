"""
orchestrator/llm/groq_provider.py
-----------------------------------
Groq LLM provider — calls llama-3.3-70b-versatile via Groq API.

Uses the openai-compatible client with Groq's base URL.
Returns None on any failure — never raises to caller.

SECURITY:
- Never log article title, content, or URL
- Never log API key or partial key
- Never log LLM response content
- Only log: provider name + failure type
"""

import sys
from typing import Optional

from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError

from orchestrator.llm.parser import parse_llm_response
from orchestrator.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_MODEL = "llama-3.3-70b-versatile"
_TEMPERATURE = 0.4
_MAX_TOKENS = 500
_TIMEOUT = 30.0

PROVIDER_NAME = "groq"


async def summarize(article: Article, api_key: str) -> Optional[SummaryResult]:
    """
    Summarize an article using Groq's llama-3.3-70b-versatile.

    Args:
        article: Article to summarize.
        api_key: Groq API key (from config.groq_api_key).

    Returns:
        SummaryResult on success, None on any failure.
    """
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=_GROQ_BASE_URL,
            timeout=_TIMEOUT,
        )

        response = await client.chat.completions.create(
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

    except APITimeoutError:
        print(f"[LLM] [{PROVIDER_NAME}] Timeout after {_TIMEOUT}s", file=sys.stderr)
        return None

    except APIStatusError as e:
        # 429 = rate limit, 401 = bad key, 503 = overload — all treated same
        print(
            f"[LLM] [{PROVIDER_NAME}] API error: HTTP {e.status_code} "
            f"{type(e).__name__}",
            file=sys.stderr,
        )
        return None

    except APIConnectionError as e:
        print(
            f"[LLM] [{PROVIDER_NAME}] Connection error: {type(e).__name__}",
            file=sys.stderr,
        )
        return None

    except ValueError as e:
        # parse_llm_response raised — response didn't have required fields
        print(
            f"[LLM] [{PROVIDER_NAME}] Parse error: {type(e).__name__}",
            file=sys.stderr,
        )
        return None

    except Exception as e:
        print(
            f"[LLM] [{PROVIDER_NAME}] Unexpected error: {type(e).__name__}",
            file=sys.stderr,
        )
        return None
