"""
orchestrator/llm/gemini_provider.py
--------------------------------------
Gemini LLM provider — calls gemini-1.5-flash via google-generativeai library.

Uses google.generativeai directly to handle the non-standard API key format
(key starts with "AQ." rather than the typical "AIza" prefix).

Returns None on any failure — never raises to caller.

SECURITY:
- Never log article title, content, or URL
- Never log API key, partial key, or any key-related info
- Never log LLM response content
- Only log: provider name + failure type
"""

import sys
from typing import Optional

from orchestrator.llm.parser import parse_llm_response
from orchestrator.llm.prompt import SYSTEM_PROMPT, build_user_prompt
from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


_MODEL = "gemini-1.5-flash"
_TEMPERATURE = 0.4
_MAX_TOKENS = 500
_TIMEOUT = 30

PROVIDER_NAME = "gemini"


async def summarize(article: Article, api_key: str) -> Optional[SummaryResult]:
    """
    Summarize an article using Google's Gemini 1.5 Flash.

    Args:
        article: Article to summarize.
        api_key: Gemini API key (from config.gemini_api_key).
                 Handles both AIza... and AQ... key formats.

    Returns:
        SummaryResult on success, None on any failure.
    """
    try:
        import google.generativeai as genai
        import asyncio

        # Configure the library with the API key
        genai.configure(api_key=api_key)

        model = genai.GenerativeModel(
            model_name=_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.types.GenerationConfig(
                temperature=_TEMPERATURE,
                max_output_tokens=_MAX_TOKENS,
            ),
        )

        user_prompt = build_user_prompt(article)

        # google-generativeai is sync — run in thread to avoid blocking event loop
        response = await asyncio.to_thread(
            model.generate_content,
            user_prompt,
            request_options={"timeout": _TIMEOUT},
        )

        response_text = response.text or ""
        if not response_text.strip():
            print(
                f"[LLM] [{PROVIDER_NAME}] Empty response returned",
                file=sys.stderr,
            )
            return None

        result = parse_llm_response(response_text)
        result.llm_provider = PROVIDER_NAME
        return result

    except ValueError as e:
        # parse_llm_response raised — response missing required fields
        print(
            f"[LLM] [{PROVIDER_NAME}] Parse error: {type(e).__name__}",
            file=sys.stderr,
        )
        return None

    except Exception as e:
        # Covers: InvalidArgument (bad key), ResourceExhausted (quota),
        # DeadlineExceeded (timeout), ServiceUnavailable, etc.
        # Log only exception type — never key, content, or URL
        print(
            f"[LLM] [{PROVIDER_NAME}] Failed: {type(e).__name__}",
            file=sys.stderr,
        )
        return None
