"""
orchestrator/tests/test_llm.py
--------------------------------
Phase 5 test suite for the LLM Fallback Chain.

Unit Tests (no real API calls — all providers mocked):
  Parser:
    - Valid full response parsed correctly into SummaryResult
    - HEADLINE auto-uppercased
    - Missing HEADLINE raises ValueError
    - Missing PARAGRAPH_1 raises ValueError
    - Missing optional fields default to empty string
    - Multi-line field values joined with single space
    - point_4 = "N/A" stored as None
    - point_4 = "Scale not yet disclosed" stored as None
    - point_4 with real value stored as string
    - Whitespace stripped from all parsed values

  Raw Fallback:
    - Always returns SummaryResult (never raises)
    - used_raw_fallback = True
    - llm_provider = 'raw'
    - HTML stripped from description
    - Truncates at 800 chars at last complete sentence
    - Short description returned unchanged
    - Empty description uses article title as paragraph_1
    - Static conclusion always present

  Summarizer:
    - Returns first provider's result on success
    - Skips to next provider when one returns None
    - Reaches raw fallback when all LLMs fail
    - 2-second delay applied between provider switches
    - Never raises even if provider raises unexpectedly

Integration Test (marked @pytest.mark.integration):
    - One real Groq call on a sample article
    - SummaryResult has non-empty headline
    - Headline is uppercase

Run with:
    python -m pytest orchestrator/tests/test_llm.py -v
    python -m pytest orchestrator/tests/test_llm.py -v -m "not integration"
"""

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, ".")

from orchestrator.llm.parser import parse_llm_response
from orchestrator.llm.raw_fallback import (
    _strip_html,
    _truncate_at_sentence,
    summarize as raw_summarize,
)
from orchestrator.llm.summarizer import summarize_with_fallback
from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

def make_article(
    title="Anthropic Releases Claude 4 with Extended Context Window",
    description="Anthropic today announced Claude 4, a new large language model with a 1M token context window. The model outperforms GPT-4 on most benchmarks. It will be available via API starting next week.",
    url="https://example.com/claude-4-release",
    hours_old=2,
) -> Article:
    from datetime import timedelta
    return Article(
        title=title,
        url=url,
        description=description,
        published_at=datetime.now(tz=timezone.utc) - timedelta(hours=hours_old),
        source="test",
    )


VALID_LLM_RESPONSE = """HEADLINE: ANTHROPIC RELEASES CLAUDE 4 WITH EXTENDED CONTEXT WINDOW

PARAGRAPH_1: Anthropic has released Claude 4, a new large language model featuring a one million token context window. The model was announced today and will be available via API starting next week.

PARAGRAPH_2: Claude 4 outperforms GPT-4 on most industry benchmarks, according to Anthropic. Developers building long-document applications stand to benefit most from the expanded context.

PARAGRAPH_3: The release intensifies competition in the foundation model space. Rivals including OpenAI and Google are expected to respond with their own context window expansions in the coming months.

POINT_1: Anthropic released Claude 4 with a 1 million token context window
POINT_2: The model was developed internally and announced via Anthropic's official channels
POINT_3: Developers and enterprises using long-document processing are the primary beneficiaries
POINT_4: The model outperforms GPT-4 on most benchmarks tested by Anthropic
POINT_5: Anthropic CEO stated the release represents a major leap in practical AI utility

CONCLUSION: Claude 4 raises the bar for context length in production AI — every serious AI application will now be measured against a 1M token standard."""

MINIMAL_LLM_RESPONSE = """HEADLINE: AI COMPANY MAKES ANNOUNCEMENT

PARAGRAPH_1: An AI company made an important announcement today affecting many users."""

MISSING_HEADLINE_RESPONSE = """PARAGRAPH_1: Some content here without a headline."""

MISSING_P1_RESPONSE = """HEADLINE: SOME HEADLINE BUT NO PARAGRAPH"""

MULTILINE_RESPONSE = """HEADLINE: MULTILINE FIELD TEST

PARAGRAPH_1: This is the first sentence of paragraph one.
This is the second sentence that continues on a new line.
And this is the third sentence completing the paragraph.

PARAGRAPH_2: Second paragraph is simple.

CONCLUSION: Final conclusion here."""


# ------------------------------------------------------------------ #
# Parser Unit Tests                                                    #
# ------------------------------------------------------------------ #

class TestParser:

    def test_valid_full_response_parsed_correctly(self):
        result = parse_llm_response(VALID_LLM_RESPONSE)
        assert isinstance(result, SummaryResult)
        assert result.headline
        assert result.paragraph_1
        assert result.paragraph_2
        assert result.paragraph_3
        assert result.point_1
        assert result.conclusion

    def test_headline_is_uppercased(self):
        response = "HEADLINE: claude releases new model\nPARAGRAPH_1: Some content."
        result = parse_llm_response(response)
        assert result.headline == "CLAUDE RELEASES NEW MODEL"

    def test_headline_already_uppercase_unchanged(self):
        result = parse_llm_response(VALID_LLM_RESPONSE)
        assert result.headline == result.headline.upper()

    def test_missing_headline_raises_value_error(self):
        with pytest.raises(ValueError, match="HEADLINE"):
            parse_llm_response(MISSING_HEADLINE_RESPONSE)

    def test_missing_paragraph_1_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_llm_response(MISSING_P1_RESPONSE)

    def test_missing_optional_fields_default_to_empty_string(self):
        result = parse_llm_response(MINIMAL_LLM_RESPONSE)
        assert result.paragraph_2 == ""
        assert result.paragraph_3 == ""
        assert result.point_1 == ""
        assert result.point_2 == ""
        assert result.point_3 == ""
        assert result.point_5 == ""
        assert result.conclusion == ""

    def test_multiline_field_values_joined_with_space(self):
        result = parse_llm_response(MULTILINE_RESPONSE)
        # Multi-line PARAGRAPH_1 should be joined into one string
        assert "first sentence" in result.paragraph_1
        assert "second sentence" in result.paragraph_1
        assert "third sentence" in result.paragraph_1
        # Should be joined with spaces, not newlines
        assert "\n" not in result.paragraph_1

    def test_point_4_na_stored_as_none(self):
        response = (
            "HEADLINE: TEST\nPARAGRAPH_1: Content.\n"
            "POINT_4: N/A\n"
        )
        result = parse_llm_response(response)
        assert result.point_4 is None

    def test_point_4_scale_not_disclosed_stored_as_none(self):
        response = (
            "HEADLINE: TEST\nPARAGRAPH_1: Content.\n"
            "POINT_4: Scale not yet disclosed\n"
        )
        result = parse_llm_response(response)
        assert result.point_4 is None

    def test_point_4_with_real_value_stored_as_string(self):
        response = (
            "HEADLINE: TEST\nPARAGRAPH_1: Content.\n"
            "POINT_4: Revenue grew 40% year-over-year to $2.3 billion\n"
        )
        result = parse_llm_response(response)
        assert result.point_4 == "Revenue grew 40% year-over-year to $2.3 billion"

    def test_whitespace_stripped_from_all_fields(self):
        response = (
            "HEADLINE:   Spaces Around Headline   \n"
            "PARAGRAPH_1:   Content with spaces.   \n"
        )
        result = parse_llm_response(response)
        assert result.headline == "SPACES AROUND HEADLINE"
        assert result.paragraph_1 == "Content with spaces."

    def test_empty_point_4_stored_as_none(self):
        response = (
            "HEADLINE: TEST\nPARAGRAPH_1: Content.\n"
            "POINT_4: \n"
        )
        result = parse_llm_response(response)
        assert result.point_4 is None

    def test_error_message_limited_to_200_chars(self):
        """ValueError must not expose the full LLM response — only 200 chars."""
        long_bad_response = "PARAGRAPH_1: " + ("x" * 1000)
        try:
            parse_llm_response(long_bad_response)
            pytest.fail("Should have raised ValueError")
        except ValueError as e:
            error_msg = str(e)
            # The full 1000-char response should not be in the error
            assert len(error_msg) < 600, (
                f"Error message too long ({len(error_msg)} chars) — "
                f"may be leaking full LLM response"
            )


# ------------------------------------------------------------------ #
# Raw Fallback Unit Tests                                              #
# ------------------------------------------------------------------ #

class TestRawFallback:

    def test_always_returns_summary_result(self):
        article = make_article()
        result = raw_summarize(article)
        assert isinstance(result, SummaryResult)

    def test_used_raw_fallback_is_true(self):
        result = raw_summarize(make_article())
        assert result.used_raw_fallback is True

    def test_llm_provider_is_raw(self):
        result = raw_summarize(make_article())
        assert result.llm_provider == "raw"

    def test_headline_is_article_title_uppercased(self):
        article = make_article(title="OpenAI Releases GPT-5 Today")
        result = raw_summarize(article)
        assert result.headline == "OPENAI RELEASES GPT-5 TODAY"

    def test_html_stripped_from_description(self):
        article = make_article(
            description="<p>This is <strong>important</strong> AI news.</p>"
        )
        result = raw_summarize(article)
        assert "<" not in result.paragraph_1
        assert "important" in result.paragraph_1
        assert "AI news" in result.paragraph_1

    def test_short_description_returned_unchanged(self):
        short_desc = "Short description with no truncation needed."
        article = make_article(description=short_desc)
        result = raw_summarize(article)
        assert short_desc in result.paragraph_1

    def test_truncates_at_800_chars(self):
        long_desc = ("This is a complete sentence. " * 40)  # ~1160 chars
        article = make_article(description=long_desc)
        result = raw_summarize(article)
        # paragraph_1 should be shorter than original after truncation
        assert len(result.paragraph_1) <= 804  # 800 + "..." = 803

    def test_truncation_ends_at_sentence_boundary(self):
        # Build exactly 900 chars with clear sentence boundaries
        desc = "First sentence ends here. " * 35  # ~910 chars
        article = make_article(description=desc)
        result = raw_summarize(article)
        # Should end with a period (sentence boundary) + "..."
        assert result.paragraph_1.endswith("..."), (
            f"Expected truncated text to end with '...', got: "
            f"{result.paragraph_1[-20:]!r}"
        )

    def test_empty_description_uses_title_as_paragraph(self):
        article = make_article(description="", title="Claude 4 Released")
        result = raw_summarize(article)
        # paragraph_1 should fall back to title
        assert result.paragraph_1  # Not empty
        assert len(result.paragraph_1) > 0

    def test_static_conclusion_always_present(self):
        result = raw_summarize(make_article())
        assert "developing story" in result.conclusion
        assert "Stay tuned" in result.conclusion

    def test_never_raises_on_edge_cases(self):
        """Raw fallback must handle any input without raising."""
        edge_cases = [
            # Empty description only — title is still valid (Article requires non-empty title)
            make_article(title="AI News Update", description=""),
            # HTML script tags in description
            make_article(description="<script>alert('xss')</script>"),
            # Very long description
            make_article(description="A" * 5000),
        ]
        for article in edge_cases:
            try:
                result = raw_summarize(article)
                assert isinstance(result, SummaryResult)
            except Exception as e:
                pytest.fail(
                    f"raw_summarize raised {type(e).__name__} "
                    f"on edge case: {e}"
                )

    def test_strip_html_helper(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"
        assert _strip_html("No HTML here") == "No HTML here"
        assert _strip_html("") == ""

    def test_truncate_at_sentence_helper(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _truncate_at_sentence(text, max_chars=20)
        assert result.endswith("...")
        assert len(result) <= 23  # 20 + "..."

    def test_truncate_short_text_unchanged(self):
        text = "Short text."
        result = _truncate_at_sentence(text, max_chars=800)
        assert result == text


# ------------------------------------------------------------------ #
# Summarizer Unit Tests (all providers mocked)                        #
# ------------------------------------------------------------------ #

class TestSummarizer:

    def _make_summary(self, provider: str = "groq") -> SummaryResult:
        return SummaryResult(
            headline="TEST HEADLINE",
            paragraph_1="Test paragraph one content.",
            paragraph_2="",
            paragraph_3="",
            point_1="",
            point_2="",
            point_3="",
            point_4=None,
            point_5="",
            conclusion="Test conclusion.",
            llm_provider=provider,
        )

    @pytest.mark.asyncio
    async def test_returns_first_provider_result_on_success(self):
        """Groq succeeds → its result is returned, no other provider called."""
        groq_result = self._make_summary("groq")

        with (
            patch("orchestrator.llm.summarizer.groq_provider.summarize",
                  new=AsyncMock(return_value=groq_result)) as mock_groq,
            patch("orchestrator.llm.summarizer.mistral_provider.summarize",
                  new=AsyncMock(return_value=None)) as mock_mistral,
        ):
            result = await summarize_with_fallback(
                make_article(), "gk", "mk", "ork", "gek"
            )

        assert result.llm_provider == "groq"
        mock_groq.assert_called_once()
        mock_mistral.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_to_next_provider_when_returns_none(self):
        """Groq returns None → Mistral is tried next."""
        mistral_result = self._make_summary("mistral")

        with (
            patch("orchestrator.llm.summarizer.groq_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.mistral_provider.summarize",
                  new=AsyncMock(return_value=mistral_result)),
            patch("orchestrator.llm.summarizer.asyncio.sleep",
                  new=AsyncMock()),
        ):
            result = await summarize_with_fallback(
                make_article(), "gk", "mk", "ork", "gek"
            )

        assert result.llm_provider == "mistral"

    @pytest.mark.asyncio
    async def test_reaches_raw_fallback_when_all_llms_fail(self):
        """All 4 LLM providers return None → raw fallback used."""
        with (
            patch("orchestrator.llm.summarizer.groq_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.mistral_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.openrouter_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.gemini_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.asyncio.sleep",
                  new=AsyncMock()),
        ):
            result = await summarize_with_fallback(
                make_article(), "gk", "mk", "ork", "gek"
            )

        assert result.used_raw_fallback is True
        assert result.llm_provider == "raw"

    @pytest.mark.asyncio
    async def test_2_second_delay_between_provider_switches(self):
        """asyncio.sleep(2.0) is called between each failed provider."""
        mock_sleep = AsyncMock()

        with (
            patch("orchestrator.llm.summarizer.groq_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.mistral_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.openrouter_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.gemini_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.asyncio.sleep", new=mock_sleep),
        ):
            await summarize_with_fallback(
                make_article(), "gk", "mk", "ork", "gek"
            )

        # 4 LLM providers, 3 gaps between them (not after last)
        assert mock_sleep.call_count == 3
        # Each call should be for 2.0 seconds
        for call in mock_sleep.call_args_list:
            assert call.args[0] == 2.0

    @pytest.mark.asyncio
    async def test_never_raises_if_provider_raises_unexpectedly(self):
        """Even if a provider raises instead of returning None, chain continues."""
        mistral_result = self._make_summary("mistral")

        with (
            patch("orchestrator.llm.summarizer.groq_provider.summarize",
                  new=AsyncMock(side_effect=RuntimeError("Unexpected crash"))),
            patch("orchestrator.llm.summarizer.mistral_provider.summarize",
                  new=AsyncMock(return_value=mistral_result)),
            patch("orchestrator.llm.summarizer.asyncio.sleep",
                  new=AsyncMock()),
        ):
            # Must NOT raise — should fall through to mistral
            result = await summarize_with_fallback(
                make_article(), "gk", "mk", "ork", "gek"
            )

        assert result is not None
        assert result.llm_provider == "mistral"

    @pytest.mark.asyncio
    async def test_openrouter_used_before_gemini(self):
        """OpenRouter (position 3) is tried before Gemini (position 4)."""
        openrouter_result = self._make_summary("openrouter_llama")

        with (
            patch("orchestrator.llm.summarizer.groq_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.mistral_provider.summarize",
                  new=AsyncMock(return_value=None)),
            patch("orchestrator.llm.summarizer.openrouter_provider.summarize",
                  new=AsyncMock(return_value=openrouter_result)),
            patch("orchestrator.llm.summarizer.gemini_provider.summarize",
                  new=AsyncMock(return_value=None)) as mock_gemini,
            patch("orchestrator.llm.summarizer.asyncio.sleep",
                  new=AsyncMock()),
        ):
            result = await summarize_with_fallback(
                make_article(), "gk", "mk", "ork", "gek"
            )

        assert result.llm_provider == "openrouter_llama"
        mock_gemini.assert_not_called()


# ------------------------------------------------------------------ #
# Integration Tests — Real Groq API Call                              #
# ------------------------------------------------------------------ #

@pytest.mark.integration
class TestLLMIntegration:
    """Integration tests requiring real API keys in environment."""

    @pytest.mark.asyncio
    async def test_groq_real_api_call(self):
        """
        Make one real Groq API call and verify SummaryResult structure.
        Requires GROQ_API_KEY in environment.
        """
        import os
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            pytest.skip("GROQ_API_KEY not set — skipping real API test")

        from orchestrator.llm.groq_provider import summarize as groq_summarize

        article = make_article(
            title="Anthropic Releases Claude 4 with 1 Million Token Context",
            description=(
                "Anthropic today announced Claude 4, a new large language model "
                "with an unprecedented 1 million token context window. The model "
                "outperforms GPT-4 on most benchmarks and will be available via "
                "API starting next week. The release is expected to accelerate "
                "enterprise adoption of AI for long-document tasks. Anthropic CEO "
                "described it as the most significant advancement in practical AI."
            ),
        )

        result = await groq_summarize(article, api_key)

        assert result is not None, (
            "Groq API returned None — check API key and quota"
        )
        assert isinstance(result, SummaryResult)
        assert result.headline, "Headline must not be empty"
        assert result.headline == result.headline.upper(), (
            f"Headline must be uppercase, got: {result.headline!r}"
        )
        assert result.paragraph_1, "paragraph_1 must not be empty"
        assert result.llm_provider == "groq"
        assert result.used_raw_fallback is False

        print(f"\n[TEST] Groq result: {result}")
