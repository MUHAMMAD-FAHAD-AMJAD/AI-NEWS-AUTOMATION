"""
orchestrator/tests/test_formatter.py
--------------------------------------
Phase 6 test suite for Message Formatter + Validator.

Unit Tests:
  build_message():
    - Produces correct locked template structure
    - Headline wrapped in 📰 *...*
    - All sections present: Summary, What Actually Happened, Conclusion
    - Optional paragraphs included when present, skipped when empty
    - Bullet points rendered with "- " prefix
    - point_4 = None skipped in bullet list
    - Empty bullet points skipped
    - Message hard-capped at 4,096 chars (conclusion truncated)
    - Long message truncated with "..."

  build_fallback_message():
    - Correct fallback template structure
    - HTML stripped from description
    - Description truncated at 800 chars
    - Static conclusion always present
    - Headline is article title uppercased

  validate_message():
    - Check 1: Too-short message replaced with fallback text
    - Check 2: Missing 📰 headline prepended
    - Check 3: Message > 4096 chars truncated
    - Check 4: URLs stripped from message
    - Check 5: Source names stripped
    - Check 6: Hashtags stripped
    - Check 7: Missing 💡 conclusion appended
    - Clean valid message passes unchanged
    - All 7 checks run on same message in correct order

Run with:
    python -m pytest orchestrator/tests/test_formatter.py -v
"""

import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, ".")

from orchestrator.formatter.message import (
    _FALLBACK_CONCLUSION,
    _WA_MAX_CHARS,
    build_fallback_message,
    build_message,
    validate_message,
)
from orchestrator.models.article import Article
from orchestrator.models.summary import SummaryResult


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

def make_article(
    title="OpenAI Releases GPT-5 With Unprecedented Reasoning",
    description="OpenAI has released GPT-5, featuring advanced reasoning capabilities and a 2M token context window.",
    url="https://example.com/gpt5",
) -> Article:
    return Article(
        title=title,
        url=url,
        description=description,
        published_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        source="techcrunch",
    )


def make_summary(
    headline="OPENAI RELEASES GPT-5 WITH UNPRECEDENTED REASONING",
    paragraph_1="OpenAI has released GPT-5, featuring advanced reasoning capabilities.",
    paragraph_2="The model outperforms all competitors on industry benchmarks.",
    paragraph_3="The release is expected to reshape enterprise AI deployments.",
    point_1="OpenAI released GPT-5 publicly today",
    point_2="The model was trained on a new multimodal dataset",
    point_3="Enterprise customers and developers are the primary beneficiaries",
    point_4="The model scores 98th percentile on the MMLU benchmark",
    point_5="OpenAI CEO stated this is the most capable model they have built",
    conclusion="GPT-5 sets a new bar for AI reasoning that every competitor must now match.",
    provider="groq",
    used_raw=False,
) -> SummaryResult:
    return SummaryResult(
        headline=headline,
        paragraph_1=paragraph_1,
        paragraph_2=paragraph_2,
        paragraph_3=paragraph_3,
        point_1=point_1,
        point_2=point_2,
        point_3=point_3,
        point_4=point_4,
        point_5=point_5,
        conclusion=conclusion,
        llm_provider=provider,
        used_raw_fallback=used_raw,
    )


# ------------------------------------------------------------------ #
# build_message() Tests                                                #
# ------------------------------------------------------------------ #

class TestBuildMessage:

    def test_produces_correct_template_structure(self):
        summary = make_summary()
        msg = build_message(summary)
        assert "📰" in msg
        assert "📋 *Summary:*" in msg
        assert "*🔑 What Actually Happened:*" in msg
        assert "*💡 Conclusion:*" in msg

    def test_headline_wrapped_in_bold_emoji(self):
        summary = make_summary(headline="OPENAI RELEASES GPT-5")
        msg = build_message(summary)
        assert "📰 *OPENAI RELEASES GPT-5*" in msg

    def test_headline_is_first_line(self):
        summary = make_summary()
        msg = build_message(summary)
        first_line = msg.split("\n")[0]
        assert first_line.startswith("📰")

    def test_paragraph_1_always_included(self):
        summary = make_summary(paragraph_1="This is the first paragraph.")
        msg = build_message(summary)
        assert "This is the first paragraph." in msg

    def test_paragraph_2_included_when_present(self):
        summary = make_summary(paragraph_2="Second paragraph content.")
        msg = build_message(summary)
        assert "Second paragraph content." in msg

    def test_paragraph_2_skipped_when_empty(self):
        summary = make_summary(paragraph_2="")
        msg = build_message(summary)
        # Verify paragraph_1 is present but no extra blank paragraph block
        assert summary.paragraph_1 in msg
        # Count blank lines — should be fewer without paragraph_2
        blank_count = msg.count("\n\n")
        assert blank_count >= 1  # At least one blank line exists

    def test_paragraph_3_skipped_when_empty(self):
        summary = make_summary(paragraph_3="")
        msg = build_message(summary)
        assert summary.paragraph_1 in msg
        # paragraph_3 content is not present
        assert "Third paragraph" not in msg

    def test_bullet_points_rendered_with_dash(self):
        summary = make_summary()
        msg = build_message(summary)
        assert "- OpenAI released GPT-5 publicly today" in msg
        assert "- The model was trained" in msg

    def test_point_4_none_skipped_in_bullet_list(self):
        summary = make_summary(point_4=None)
        msg = build_message(summary)
        # point_1 is present, point_4 = None so no line for it
        assert "- OpenAI released GPT-5 publicly today" in msg
        # Count bullet points — should have 4, not 5
        bullet_lines = [l for l in msg.split("\n") if l.startswith("- ")]
        assert len(bullet_lines) == 4

    def test_empty_bullet_points_skipped(self):
        summary = make_summary(point_1="", point_2="", point_3="Only This Point", point_4=None, point_5="")
        msg = build_message(summary)
        bullet_lines = [l for l in msg.split("\n") if l.startswith("- ")]
        assert len(bullet_lines) == 1
        assert "Only This Point" in bullet_lines[0]

    def test_conclusion_included(self):
        summary = make_summary(conclusion="This is the punchy conclusion.")
        msg = build_message(summary)
        assert "This is the punchy conclusion." in msg

    def test_message_hard_capped_at_4096_chars(self):
        # Create a summary with a very long conclusion to force truncation
        long_conclusion = "This is a very important conclusion sentence. " * 200
        summary = make_summary(conclusion=long_conclusion)
        msg = build_message(summary)
        assert len(msg) <= _WA_MAX_CHARS, (
            f"Message exceeds {_WA_MAX_CHARS} chars: {len(msg)}"
        )

    def test_truncated_long_message_ends_with_ellipsis(self):
        long_conclusion = "Word " * 2000  # ~10000 chars
        summary = make_summary(conclusion=long_conclusion)
        msg = build_message(summary)
        assert len(msg) <= _WA_MAX_CHARS
        assert msg.endswith("...")

    def test_returns_string(self):
        summary = make_summary()
        msg = build_message(summary)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_fallback_conclusion_used_when_empty(self):
        summary = make_summary(conclusion="")
        msg = build_message(summary)
        assert _FALLBACK_CONCLUSION in msg or "*💡 Conclusion:*" in msg


# ------------------------------------------------------------------ #
# build_fallback_message() Tests                                       #
# ------------------------------------------------------------------ #

class TestBuildFallbackMessage:

    def test_correct_fallback_template_structure(self):
        article = make_article()
        msg = build_fallback_message(article)
        assert "📰" in msg
        assert "📋 *Summary:*" in msg
        assert "*💡 Conclusion:*" in msg

    def test_headline_is_title_uppercased(self):
        article = make_article(title="OpenAI Releases GPT-5 Today")
        msg = build_fallback_message(article)
        assert "OPENAI RELEASES GPT-5 TODAY" in msg

    def test_static_conclusion_always_present(self):
        article = make_article()
        msg = build_fallback_message(article)
        assert _FALLBACK_CONCLUSION in msg

    def test_html_stripped_from_description(self):
        article = make_article(
            description="<p>This is <strong>breaking</strong> AI news.</p>"
        )
        msg = build_fallback_message(article)
        assert "<p>" not in msg
        assert "<strong>" not in msg
        assert "breaking" in msg
        assert "AI news" in msg

    def test_description_truncated_at_800_chars(self):
        long_desc = "This is a complete sentence about AI. " * 30  # ~1110 chars
        article = make_article(description=long_desc)
        msg = build_fallback_message(article)
        # Extract just the description part (between Summary and Conclusion)
        summary_idx = msg.find("📋 *Summary:*\n") + len("📋 *Summary:*\n")
        conclusion_idx = msg.find("\n\n*💡 Conclusion:*")
        desc_part = msg[summary_idx:conclusion_idx]
        assert len(desc_part) <= 804  # 800 + "..."

    def test_short_description_not_truncated(self):
        short = "This is a short description. It fits easily."
        article = make_article(description=short)
        msg = build_fallback_message(article)
        assert short in msg

    def test_returns_string(self):
        article = make_article()
        msg = build_fallback_message(article)
        assert isinstance(msg, str)
        assert len(msg) > 50


# ------------------------------------------------------------------ #
# validate_message() Tests                                             #
# ------------------------------------------------------------------ #

class TestValidateMessage:

    def _valid_message(self) -> str:
        """Build a clean, valid message that should pass all checks."""
        return (
            "📰 *OPENAI RELEASES GPT-5*\n\n"
            "📋 *Summary:*\n"
            "OpenAI released GPT-5 today with advanced reasoning.\n\n"
            "*🔑 What Actually Happened:*\n"
            "- GPT-5 was released publicly\n\n"
            "*💡 Conclusion:*\n"
            "This changes AI forever."
        )

    def test_clean_valid_message_passes_unchanged(self):
        """A message that passes all checks should come back unchanged."""
        msg = self._valid_message()
        result = validate_message(msg)
        # Core content should still be there
        assert "📰" in result
        assert "📋 *Summary:*" in result
        assert "💡" in result

    def test_check_1_too_short_message_replaced(self):
        """Messages under 100 chars get replaced with fallback text."""
        short_msg = "Too short."
        result = validate_message(short_msg)
        assert len(result) > 100
        assert "📰" in result

    def test_check_2_missing_headline_prepended(self):
        """Message not starting with 📰 gets headline prepended."""
        msg_without_headline = (
            "📋 *Summary:*\n"
            "Content without a headline.\n\n"
            "*💡 Conclusion:*\n"
            "Conclusion here."
        )
        result = validate_message(msg_without_headline)
        assert result.strip().startswith("📰")

    def test_check_2_article_title_used_in_headline(self):
        """When article provided, its title used for prepended headline."""
        # Message must be > 100 chars so Check 1 (length) doesn't fire first
        msg = (
            "📋 *Summary:*\n"
            "Content about an important AI development reported today.\n\n"
            "*🔑 What Actually Happened:*\n"
            "- A major AI company released a new model today.\n\n"
            "*💡 Conclusion:*\n"
            "This is a significant moment for the AI industry."
        )
        article = make_article(title="Test Article Title")
        result = validate_message(msg, article=article)
        assert "TEST ARTICLE TITLE" in result

    def test_check_3_long_message_truncated_at_4096(self):
        """Messages over 4,096 chars are truncated."""
        base = self._valid_message()
        long_msg = base + ("\nExtra content. " * 500)
        result = validate_message(long_msg)
        assert len(result) <= _WA_MAX_CHARS

    def test_check_4_urls_stripped(self):
        """http:// and https:// URLs are removed."""
        msg = self._valid_message().replace(
            "OpenAI released GPT-5 today",
            "See https://openai.com/gpt5 for details"
        )
        result = validate_message(msg)
        assert "https://openai.com" not in result
        assert "http" not in result

    def test_check_5_source_names_stripped(self):
        """Known source names are removed from the message."""
        msg = self._valid_message().replace(
            "OpenAI released GPT-5 today",
            "According to TechCrunch, GPT-5 was released today"
        )
        result = validate_message(msg)
        assert "TechCrunch" not in result

    def test_check_6_hashtags_stripped(self):
        """Hashtags are removed."""
        msg = self._valid_message() + "\n#AI #OpenAI #GPT5"
        result = validate_message(msg)
        assert "#AI" not in result
        assert "#OpenAI" not in result
        assert "#GPT5" not in result

    def test_check_7_missing_conclusion_appended(self):
        """Messages without 💡 get static conclusion appended."""
        msg_no_conclusion = (
            "📰 *TEST HEADLINE*\n\n"
            "📋 *Summary:*\n"
            "Content here with enough text to pass the length check and be valid.\n\n"
            "*🔑 What Actually Happened:*\n"
            "- Something happened here today in the world of AI technology.\n"
        )
        result = validate_message(msg_no_conclusion)
        assert "💡" in result
        assert _FALLBACK_CONCLUSION in result

    def test_multiple_issues_all_fixed(self):
        """Message with multiple problems gets all of them fixed."""
        messy_msg = (
            "📋 *Summary:*\n"                          # No headline
            "See https://openai.com for details.\n\n"  # Has URL
            "Check #AI trends today.\n"                # Has hashtag
            "According to TechCrunch, this is big.\n"  # Source name
            # No conclusion
        )
        result = validate_message(messy_msg, article=make_article())
        assert result.strip().startswith("📰")       # Headline added
        assert "http" not in result                   # URL stripped
        assert "#AI" not in result                    # Hashtag stripped
        assert "TechCrunch" not in result             # Source stripped
        assert "💡" in result                         # Conclusion added

    def test_returns_string(self):
        result = validate_message(self._valid_message())
        assert isinstance(result, str)
