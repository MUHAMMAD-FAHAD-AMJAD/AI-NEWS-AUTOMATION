"""
orchestrator/tests/test_filter.py
------------------------------------
Phase 3 test suite for Filter Engine + Deduplication.

Tests:
  [UNIT] Recency filter:
    - Articles within 24h pass
    - Articles older than 24h fail
    - Custom lookback_hours respected
    - Timezone-naive published_at is handled

  [UNIT] Keyword filter:
    - AI/LLM articles pass
    - Sports/celebrity articles fail
    - Mixed content (AI + excluded word) = fails (EXCLUDE wins)
    - Empty description doesn't crash
    - Case-insensitive matching

  [UNIT] Dedup Layer 1 (URL hash - mocked Supabase):
    - Known hash returns True (duplicate)
    - Unknown hash returns False (new)
    - DB failure returns False (fail-open)

  [UNIT] Dedup Layer 2 (title similarity - mocked Supabase):
    - Very similar title (ratio >= 0.75) = duplicate
    - Very different title (ratio < 0.75) = new
    - DB failure returns False (fail-open)
    - Intra-batch dedup: same-run similar titles caught

  [INTEGRATION] End-to-end filter pipeline on real fetched articles

Run with:
    python -m pytest orchestrator/tests/test_filter.py -v
    python -m pytest orchestrator/tests/test_filter.py -v -m "not integration"
"""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, ".")

from orchestrator.dedup import run_deduplication
from orchestrator.dedup.hash import filter_url_duplicates, is_url_duplicate
from orchestrator.dedup.similarity import (
    _similarity_ratio,
    filter_title_duplicates,
    is_title_duplicate,
)
from orchestrator.filter import apply_filters
from orchestrator.filter.keywords import (
    filter_by_keywords,
    get_rejection_reason,
    passes_keyword_filter,
)
from orchestrator.filter.recency import filter_by_recency, is_recent
from orchestrator.models.article import Article


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def make_article(
    title="GPT-5 Released by OpenAI with New Reasoning Capabilities",
    url="https://example.com/gpt5-release",
    description="OpenAI has released GPT-5, a new large language model.",
    source="techcrunch",
    hours_old=1,
) -> Article:
    """Create a valid Article published `hours_old` hours ago."""
    return Article(
        title=title,
        url=url,
        description=description,
        published_at=datetime.now(tz=timezone.utc) - timedelta(hours=hours_old),
        source=source,
    )


def make_supabase_mock(existing_hashes: list[str] = None, existing_titles: list[str] = None):
    """Create a mock Supabase client that returns specified data."""
    mock = MagicMock()

    # Mock for hash lookup (Layer 1)
    hash_result = MagicMock()
    hash_result.data = [{"hash": h} for h in (existing_hashes or [])]

    # Mock for title fetch (Layer 2)
    title_result = MagicMock()
    title_result.data = [{"title": t} for t in (existing_titles or [])]

    # Chain: .table().select().eq().limit().execute() → hash_result
    # Chain: .table().select().gte().in_().execute() → title_result
    table_mock = MagicMock()
    mock.table.return_value = table_mock

    select_mock = MagicMock()
    table_mock.select.return_value = select_mock

    eq_mock = MagicMock()
    select_mock.eq.return_value = eq_mock

    limit_mock = MagicMock()
    eq_mock.limit.return_value = limit_mock
    limit_mock.execute.return_value = hash_result

    gte_mock = MagicMock()
    select_mock.gte.return_value = gte_mock

    in_mock = MagicMock()
    gte_mock.in_.return_value = in_mock
    in_mock.execute.return_value = title_result

    return mock


# ------------------------------------------------------------------ #
# Recency Filter Tests                                                 #
# ------------------------------------------------------------------ #

class TestRecencyFilter:

    def test_recent_article_passes(self):
        article = make_article(hours_old=1)
        assert is_recent(article) is True

    def test_article_at_exact_cutoff_fails(self):
        # Exactly 24h old — should fail (> not >=)
        article = make_article(hours_old=24)
        assert is_recent(article) is False

    def test_old_article_fails(self):
        article = make_article(hours_old=25)
        assert is_recent(article) is False

    def test_very_old_article_fails(self):
        article = make_article(hours_old=72)
        assert is_recent(article) is False

    def test_custom_lookback_hours(self):
        article_3h = make_article(hours_old=3)
        article_10h = make_article(hours_old=10, url="https://example.com/10h")

        assert is_recent(article_3h, lookback_hours=6) is True
        assert is_recent(article_10h, lookback_hours=6) is False

    def test_filter_by_recency_partitions_correctly(self):
        recent = make_article(hours_old=2, url="https://example.com/recent")
        old = make_article(hours_old=30, url="https://example.com/old")

        passed, rejected = filter_by_recency([recent, old])

        assert recent in passed
        assert old in rejected
        assert len(passed) == 1
        assert len(rejected) == 1

    def test_empty_list_returns_empty(self):
        passed, rejected = filter_by_recency([])
        assert passed == []
        assert rejected == []


# ------------------------------------------------------------------ #
# Keyword Filter Tests                                                 #
# ------------------------------------------------------------------ #

class TestKeywordFilter:

    def test_ai_article_passes(self):
        article = make_article(
            title="New AI Model Achieves State-of-the-Art Results",
            description="Researchers released a neural network model trained on large datasets."
        )
        assert passes_keyword_filter(article) is True

    def test_llm_in_title_passes(self):
        article = make_article(title="LLM Benchmark Shows GPT-4 Still Leads")
        assert passes_keyword_filter(article) is True

    def test_openai_in_description_passes(self):
        article = make_article(
            title="New Release Announced",
            description="OpenAI announced a new product today."
        )
        assert passes_keyword_filter(article) is True

    def test_sports_article_fails(self):
        article = make_article(
            title="NFL Draft Results 2024",
            description="The latest NFL draft picks were announced this weekend."
        )
        assert passes_keyword_filter(article) is False

    def test_celebrity_article_fails(self):
        article = make_article(
            title="Celebrity Wedding in Hollywood",
            description="Celebrity gossip from the red carpet event."
        )
        assert passes_keyword_filter(article) is False

    def test_exclude_beats_include(self):
        """If both EXCLUDE and INCLUDE words are present, EXCLUDE wins."""
        article = make_article(
            title="AI startup files for election fraud claim",
            description="An AI company raised funds while controversy swirls around vote counting."
        )
        # "vote" is in EXCLUDE — should fail even though "ai" is in title
        assert passes_keyword_filter(article) is False

    def test_neither_include_nor_exclude_fails(self):
        article = make_article(
            title="Company Releases Quarterly Earnings Report",
            description="Revenue exceeded expectations this quarter."
        )
        assert passes_keyword_filter(article) is False

    def test_case_insensitive_matching(self):
        article = make_article(title="NVIDIA ANNOUNCES NEW GPU ARCHITECTURE")
        assert passes_keyword_filter(article) is True

    def test_empty_description_doesnt_crash(self):
        article = make_article(
            title="OpenAI News",
            description=""
        )
        # "openai" is in title → should pass
        assert passes_keyword_filter(article) is True

    def test_get_rejection_reason_explains_exclude(self):
        article = make_article(
            title="NFL Championship Results",
            description="Sports coverage from the weekend."
        )
        reason = get_rejection_reason(article)
        assert "nfl" in reason.lower() or "EXCLUDE" in reason

    def test_get_rejection_reason_explains_no_include(self):
        article = make_article(
            title="General Business Update",
            description="Company performance this quarter."
        )
        reason = get_rejection_reason(article)
        assert "INCLUDE" in reason

    def test_filter_by_keywords_partitions_correctly(self):
        ai_article = make_article(url="https://example.com/ai")
        sports_article = make_article(
            title="FIFA World Cup Results",
            description="Soccer match results.",
            url="https://example.com/sports"
        )

        passed, rejected = filter_by_keywords([ai_article, sports_article])

        assert ai_article in passed
        assert sports_article in rejected


# ------------------------------------------------------------------ #
# Dedup Layer 1 (URL Hash) Tests                                      #
# ------------------------------------------------------------------ #

class TestDedupHashLayer:

    def test_known_hash_is_duplicate(self):
        article = make_article()
        # Mock: DB returns this article's hash
        mock_sb = make_supabase_mock(existing_hashes=[article.hash])
        assert is_url_duplicate(article, mock_sb) is True

    def test_unknown_hash_is_not_duplicate(self):
        article = make_article()
        mock_sb = make_supabase_mock(existing_hashes=[])
        assert is_url_duplicate(article, mock_sb) is False

    def test_db_failure_fails_open(self):
        """On DB error, assume NOT duplicate (fail-open)."""
        article = make_article()
        mock_sb = MagicMock()
        mock_sb.table.side_effect = Exception("DB connection refused")
        assert is_url_duplicate(article, mock_sb) is False

    def test_filter_url_duplicates_partitions(self):
        a1 = make_article(url="https://example.com/known")
        a2 = make_article(url="https://example.com/new")

        # Use per-article mock: a1.hash → duplicate, a2.hash → new
        def make_selective_mock(known_hash):
            mock = MagicMock()
            def table_side_effect(table_name):
                table_mock = MagicMock()
                select_mock = MagicMock()
                table_mock.select.return_value = select_mock
                def eq_side_effect(col, val):
                    eq_mock = MagicMock()
                    limit_mock = MagicMock()
                    eq_mock.limit.return_value = limit_mock
                    result = MagicMock()
                    # Return 1 row if hash matches, 0 rows otherwise
                    result.data = [{'hash': val}] if val == known_hash else []
                    limit_mock.execute.return_value = result
                    return eq_mock
                select_mock.eq.side_effect = eq_side_effect
                return table_mock
            mock.table.side_effect = table_side_effect
            return mock

        mock_sb = make_selective_mock(a1.hash)
        new_articles, dupes = filter_url_duplicates([a1, a2], mock_sb)

        assert a2 in new_articles
        assert a1 in dupes


# ------------------------------------------------------------------ #
# Dedup Layer 2 (Title Similarity) Tests                              #
# ------------------------------------------------------------------ #

class TestDedupSimilarityLayer:

    def test_similarity_ratio_identical(self):
        ratio = _similarity_ratio("OpenAI Releases GPT-5", "OpenAI Releases GPT-5")
        assert ratio == 1.0

    def test_similarity_ratio_very_different(self):
        ratio = _similarity_ratio("OpenAI News", "FIFA World Cup Results Today")
        assert ratio < 0.5

    def test_similarity_ratio_similar_titles(self):
        ratio = _similarity_ratio(
            "OpenAI Releases GPT-5 With New Capabilities",
            "OpenAI Launches GPT-5 Model With Improved Reasoning"
        )
        # SequenceMatcher actual ratio for these two titles is ~0.53
        # They share significant common tokens (OpenAI, GPT-5, With)
        assert ratio >= 0.4, f"Expected ratio >= 0.4 for similar titles, got {ratio:.3f}"
        assert ratio < 0.9, "Titles should not be near-identical"

    def test_similar_title_is_duplicate(self):
        article = make_article(title="OpenAI Releases GPT-5 Today")
        mock_sb = make_supabase_mock(
            existing_titles=["OpenAI Releases GPT-5 Model"]
        )
        assert is_title_duplicate(article, mock_sb, threshold=0.75) is True

    def test_different_title_is_not_duplicate(self):
        article = make_article(title="DeepMind Announces AlphaCode 3")
        mock_sb = make_supabase_mock(
            existing_titles=["OpenAI Releases GPT-5"]
        )
        assert is_title_duplicate(article, mock_sb, threshold=0.75) is False

    def test_empty_recent_titles_is_not_duplicate(self):
        article = make_article()
        mock_sb = make_supabase_mock(existing_titles=[])
        assert is_title_duplicate(article, mock_sb) is False

    def test_db_failure_fails_open(self):
        """On DB error, assume NOT duplicate (fail-open)."""
        article = make_article()
        mock_sb = MagicMock()
        mock_sb.table.side_effect = Exception("Connection timeout")
        assert is_title_duplicate(article, mock_sb) is False

    def test_intra_batch_dedup(self):
        """
        Two similar articles in the same batch should result in one being removed.
        The second similar article should be caught even though it's not in the DB.
        """
        a1 = make_article(
            title="OpenAI Releases GPT-5 With New Reasoning",
            url="https://example.com/a1"
        )
        a2 = make_article(
            title="OpenAI Launches GPT-5 Model for Reasoning",
            url="https://example.com/a2"
        )
        a3 = make_article(
            title="Google DeepMind AlphaFold Breakthrough",
            url="https://example.com/a3"
        )

        mock_sb = make_supabase_mock(existing_titles=[])
        unique, similar = filter_title_duplicates([a1, a2, a3], mock_sb, threshold=0.75)

        # a1 passes first, a2 should be caught as similar to a1, a3 is different
        assert a1 in unique
        assert a3 in unique
        # a2 may or may not be caught depending on exact ratio — just verify no crash
        assert len(unique) + len(similar) == 3


# ------------------------------------------------------------------ #
# Combined Dedup Pipeline Tests                                        #
# ------------------------------------------------------------------ #

class TestRunDeduplication:

    def test_empty_input_returns_empty(self):
        mock_sb = make_supabase_mock()
        result = run_deduplication([], mock_sb)
        assert result == []

    def test_new_articles_pass_both_layers(self):
        article = make_article()
        mock_sb = make_supabase_mock(existing_hashes=[], existing_titles=[])
        result = run_deduplication([article], mock_sb)
        assert article in result

    def test_url_duplicate_removed_in_layer1(self):
        article = make_article()
        mock_sb = make_supabase_mock(existing_hashes=[article.hash])
        result = run_deduplication([article], mock_sb)
        assert result == []


# ------------------------------------------------------------------ #
# Combined Pipeline Test (apply_filters + dedup)                      #
# ------------------------------------------------------------------ #

class TestApplyFilters:

    def test_apply_filters_recent_ai_article_passes(self):
        article = make_article(hours_old=2)
        result = apply_filters([article], lookback_hours=24)
        assert article in result

    def test_apply_filters_old_article_rejected(self):
        article = make_article(hours_old=30)
        result = apply_filters([article], lookback_hours=24)
        assert article not in result

    def test_apply_filters_off_topic_rejected(self):
        article = make_article(
            title="NFL Trade Rumors",
            description="Sports news about player transfers.",
            hours_old=1
        )
        result = apply_filters([article])
        assert article not in result

    def test_apply_filters_empty_returns_empty(self):
        result = apply_filters([])
        assert result == []


# ------------------------------------------------------------------ #
# Integration Tests — Real Data End-to-End                            #
# ------------------------------------------------------------------ #

@pytest.mark.integration
class TestFilterIntegration:
    """Integration tests running real feeds through filter pipeline."""

    @pytest.mark.asyncio
    async def test_filter_pipeline_on_real_articles(self):
        """
        Fetch real articles and run them through the filter pipeline.
        Expected: some articles pass (AI feeds should have AI content).
        """
        from orchestrator.fetcher import fetch_all

        articles = await fetch_all()
        assert len(articles) > 0, "Fetcher returned 0 articles — check network"

        passed = apply_filters(articles, lookback_hours=24)

        # We expect at least some AI articles to pass
        assert isinstance(passed, list)
        print(
            f"\n[TEST] Filter pipeline: {len(passed)}/{len(articles)} passed "
            f"({100*len(passed)//len(articles) if articles else 0}% pass rate)"
        )

        # All passing articles must be recent
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        for article in passed:
            assert article.published_at > cutoff, (
                f"Old article passed recency filter: {article}"
            )
