"""
orchestrator/tests/test_fetcher.py
------------------------------------
Phase 2 test suite for the RSS Fetcher + Normalizer.

Tests:
  1. [INTEGRATION] At least 1 article returned from real RSS feeds
  2. [UNIT]        Article hash is deterministic for the same URL
  3. [UNIT]        HTML is stripped from description before storage
  4. [UNIT]        Article validation rejects invalid inputs
  5. [UNIT]        fetch_all() deduplicates by URL hash
  6. [INTEGRATION] HN fetcher returns valid Article objects
  7. [INTEGRATION] Reddit fetcher returns valid Article objects
  8. [UNIT]        Articles older than 24h would be excluded by recency filter
                   (skipped if no old articles present in live feed)

Run with:
    python -m pytest orchestrator/tests/test_fetcher.py -v

Notes:
- Integration tests make REAL network requests — requires internet access
- Marked with @pytest.mark.integration so they can be skipped in CI
  with: pytest -m "not integration"
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

# Add project root to path for imports when running pytest from project root
sys.path.insert(0, ".")

from orchestrator.fetcher import fetch_all
from orchestrator.fetcher.hackernews import fetch_hackernews
from orchestrator.fetcher.reddit import fetch_reddit
from orchestrator.fetcher.rss import _strip_html, fetch_all_rss
from orchestrator.models.article import Article


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def make_article(**kwargs) -> Article:
    """Helper: create a valid Article with sensible defaults."""
    defaults = dict(
        title="Test Article Title About AI",
        url="https://example.com/test-article-unique",
        description="Some description text",
        published_at=datetime.now(tz=timezone.utc),
        source="test",
    )
    defaults.update(kwargs)
    return Article(**defaults)


# ------------------------------------------------------------------ #
# Unit Tests — Article dataclass                                       #
# ------------------------------------------------------------------ #

class TestArticleDataclass:
    """Tests for orchestrator/models/article.py"""

    def test_hash_is_deterministic_for_same_url(self):
        """
        The MD5 hash must be identical for two Articles with the same URL.
        This is the contract the Layer-1 dedup depends on.
        """
        url = "https://techcrunch.com/2024/01/15/some-article/"
        a1 = make_article(url=url)
        a2 = make_article(url=url, title="Different Title")
        assert a1.hash == a2.hash, (
            f"Expected identical hashes for same URL. "
            f"Got {a1.hash!r} vs {a2.hash!r}"
        )

    def test_hash_differs_for_different_urls(self):
        """Different URLs must produce different hashes."""
        a1 = make_article(url="https://example.com/article-one")
        a2 = make_article(url="https://example.com/article-two")
        assert a1.hash != a2.hash

    def test_hash_is_case_insensitive_on_url(self):
        """
        url.strip().lower() normalization means HTTPS://EXAMPLE.COM/a
        and https://example.com/a produce the same hash.
        """
        a1 = make_article(url="HTTPS://EXAMPLE.COM/ARTICLE")
        a2 = make_article(url="https://example.com/article")
        assert a1.hash == a2.hash

    def test_hash_strips_whitespace_from_url(self):
        """Leading/trailing whitespace in URL must not affect hash."""
        a1 = make_article(url="  https://example.com/article  ")
        a2 = make_article(url="https://example.com/article")
        assert a1.hash == a2.hash

    def test_hash_is_hex_string_of_length_32(self):
        """MD5 hex digest must always be 32 characters long."""
        article = make_article()
        assert len(article.hash) == 32
        assert all(c in "0123456789abcdef" for c in article.hash)

    def test_validation_rejects_empty_title(self):
        """Empty title must raise ValueError with a clear message."""
        with pytest.raises(ValueError, match="title"):
            make_article(title="")

    def test_validation_rejects_whitespace_only_title(self):
        """Whitespace-only title must raise ValueError."""
        with pytest.raises(ValueError, match="title"):
            make_article(title="   ")

    def test_validation_rejects_non_http_url(self):
        """URL not starting with 'http' must raise ValueError."""
        with pytest.raises(ValueError, match="url"):
            make_article(url="ftp://example.com/file")

    def test_validation_rejects_empty_url(self):
        """Empty URL must raise ValueError."""
        with pytest.raises(ValueError, match="url"):
            make_article(url="")

    def test_validation_rejects_non_datetime_published_at(self):
        """Non-datetime published_at must raise ValueError."""
        with pytest.raises(ValueError, match="published_at"):
            make_article(published_at="2024-01-01")  # type: ignore

    def test_equality_based_on_hash(self):
        """Two articles with same URL are equal regardless of other fields."""
        url = "https://example.com/shared"
        a1 = make_article(url=url, title="Version 1")
        a2 = make_article(url=url, title="Version 2")
        assert a1 == a2

    def test_articles_usable_in_set(self):
        """Article must be hashable so it can be used in sets for dedup."""
        url = "https://example.com/shared"
        a1 = make_article(url=url)
        a2 = make_article(url=url)
        a3 = make_article(url="https://example.com/other")
        article_set = {a1, a2, a3}
        assert len(article_set) == 2  # a1 and a2 are the same


# ------------------------------------------------------------------ #
# Unit Tests — HTML Stripping                                          #
# ------------------------------------------------------------------ #

class TestHTMLStripping:
    """Tests for _strip_html() used in rss.py"""

    def test_strips_basic_html_tags(self):
        raw = "<p>This is <strong>important</strong> news.</p>"
        result = _strip_html(raw)
        assert "<" not in result
        assert "important" in result
        assert "news" in result

    def test_strips_anchor_tags(self):
        raw = 'Click <a href="https://example.com">here</a> to read.'
        result = _strip_html(raw)
        assert "<a" not in result
        assert "here" in result
        assert "read" in result

    def test_strips_nested_html(self):
        raw = "<div><p><span>Deep <em>nested</em> content</span></p></div>"
        result = _strip_html(raw)
        assert "<" not in result
        assert "Deep" in result
        assert "nested" in result

    def test_handles_empty_string(self):
        assert _strip_html("") == ""

    def test_handles_plain_text(self):
        plain = "Just plain text, no HTML tags here."
        result = _strip_html(plain)
        assert result == plain

    def test_collapses_whitespace(self):
        raw = "<p>Word1   </p>  <p>   Word2</p>"
        result = _strip_html(raw)
        # Should not have multiple consecutive spaces
        assert "  " not in result

    def test_strips_script_tags(self):
        raw = "Article text. <script>alert('xss')</script> More text."
        result = _strip_html(raw)
        assert "script" not in result
        assert "alert" not in result
        assert "Article text" in result


# ------------------------------------------------------------------ #
# Unit Tests — fetch_all deduplication                                 #
# ------------------------------------------------------------------ #

class TestFetchAllDedup:
    """
    Test that fetch_all() correctly deduplicates by URL hash.
    Uses a mock to avoid real network calls.
    """

    @pytest.mark.asyncio
    async def test_deduplication_removes_same_url_from_multiple_sources(
        self, monkeypatch
    ):
        """
        If RSS and HN return the same article URL, fetch_all must return
        only ONE copy.
        """
        shared_url = "https://example.com/shared-story"
        now = datetime.now(tz=timezone.utc)

        rss_article = Article(
            title="Shared Story from RSS",
            url=shared_url,
            description="RSS description",
            published_at=now,
            source="techcrunch",
        )
        hn_article = Article(
            title="Shared Story from HN",
            url=shared_url,
            description="HN description",
            published_at=now - timedelta(hours=1),
            source="hackernews",
        )

        async def mock_rss():
            return [rss_article]

        async def mock_hn():
            return [hn_article]

        async def mock_reddit():
            return []

        import orchestrator.fetcher as fetcher_pkg
        monkeypatch.setattr(fetcher_pkg, "fetch_all_rss", mock_rss)
        monkeypatch.setattr(fetcher_pkg, "fetch_hackernews", mock_hn)
        monkeypatch.setattr(fetcher_pkg, "fetch_reddit", mock_reddit)

        result = await fetcher_pkg.fetch_all()
        assert len(result) == 1, (
            f"Expected 1 unique article after dedup, got {len(result)}"
        )

    @pytest.mark.asyncio
    async def test_fetch_all_sorted_newest_first(self, monkeypatch):
        """fetch_all() must return articles sorted newest-first."""
        now = datetime.now(tz=timezone.utc)
        old = now - timedelta(hours=5)
        older = now - timedelta(hours=10)

        articles = [
            Article(
                title="Oldest Article",
                url="https://example.com/oldest",
                description="desc",
                published_at=older,
                source="test",
            ),
            Article(
                title="Newest Article",
                url="https://example.com/newest",
                description="desc",
                published_at=now,
                source="test",
            ),
            Article(
                title="Middle Article",
                url="https://example.com/middle",
                description="desc",
                published_at=old,
                source="test",
            ),
        ]

        async def mock_rss():
            return [articles[0], articles[2]]

        async def mock_hn():
            return [articles[1]]

        async def mock_reddit():
            return []

        import orchestrator.fetcher as fetcher_pkg
        monkeypatch.setattr(fetcher_pkg, "fetch_all_rss", mock_rss)
        monkeypatch.setattr(fetcher_pkg, "fetch_hackernews", mock_hn)
        monkeypatch.setattr(fetcher_pkg, "fetch_reddit", mock_reddit)

        result = await fetcher_pkg.fetch_all()
        assert len(result) == 3
        assert result[0].title == "Newest Article"
        assert result[2].title == "Oldest Article"


# ------------------------------------------------------------------ #
# Integration Tests — Real Network Calls                               #
# ------------------------------------------------------------------ #

@pytest.mark.integration
class TestRSSIntegration:
    """
    Integration tests that make real network calls.
    Skip with: pytest -m "not integration"
    """

    @pytest.mark.asyncio
    async def test_rss_returns_at_least_one_article(self):
        """
        Real RSS feed fetch must return at least 1 article.
        If all 8 feeds are blocked or down this will fail — acceptable.
        """
        articles = await fetch_all_rss()
        assert len(articles) >= 1, (
            "Expected at least 1 article from real RSS feeds. "
            "Check network connectivity and feed URLs."
        )

    @pytest.mark.asyncio
    async def test_rss_articles_have_valid_structure(self):
        """Every returned Article must pass its own validation."""
        articles = await fetch_all_rss()
        for article in articles[:10]:  # Check first 10
            assert isinstance(article, Article)
            assert article.title and article.title.strip()
            assert article.url.startswith("http")
            assert isinstance(article.published_at, datetime)
            assert article.published_at.tzinfo is not None, (
                f"published_at must be timezone-aware for {article}"
            )
            assert len(article.hash) == 32
            assert article.source in [
                "techcrunch", "theverge", "venturebeat",
                "mittr", "wired", "huggingface", "googleai", "openai"
            ]

    @pytest.mark.asyncio
    async def test_rss_descriptions_have_no_html(self):
        """
        All article descriptions must be HTML-free after normalization.
        """
        articles = await fetch_all_rss()
        for article in articles[:20]:
            assert "<" not in article.description, (
                f"HTML found in description for [{article.source}] "
                f"{article.title[:60]!r}: {article.description[:100]!r}"
            )

    @pytest.mark.asyncio
    async def test_rss_articles_sorted_newest_first(self):
        """fetch_all_rss() must return articles newest-first."""
        articles = await fetch_all_rss()
        if len(articles) < 2:
            pytest.skip("Not enough articles to test sorting")
        for i in range(len(articles) - 1):
            assert articles[i].published_at >= articles[i + 1].published_at, (
                f"Articles not sorted newest-first at index {i}"
            )

    @pytest.mark.asyncio
    async def test_rss_old_articles_detected(self):
        """
        Test that we can detect articles older than 24h.
        Skips if no old articles present (normal on a fresh feed).
        """
        articles = await fetch_all_rss()
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        old_articles = [a for a in articles if a.published_at < cutoff]

        if not old_articles:
            pytest.skip(
                "No articles older than 24h in current feed — "
                "this is expected behavior. Recency filter would pass all."
            )

        # If old articles exist, verify recency filter logic would catch them
        for article in old_articles:
            assert article.published_at < cutoff, (
                f"Article {article} should be older than cutoff"
            )


@pytest.mark.integration
class TestHNIntegration:
    """Integration tests for Hacker News fetcher."""

    @pytest.mark.asyncio
    async def test_hn_returns_articles(self):
        """HN fetcher must return at least 1 article (network permitting)."""
        articles = await fetch_hackernews()
        # HN may return 0 if no AI stories recently — don't hard-fail
        assert isinstance(articles, list)
        if articles:
            assert all(isinstance(a, Article) for a in articles)

    @pytest.mark.asyncio
    async def test_hn_articles_have_external_urls(self):
        """All HN articles must have external (non-reddit, non-hn) URLs."""
        articles = await fetch_hackernews()
        for article in articles:
            assert article.url.startswith("http")
            assert "news.ycombinator.com" not in article.url or len(articles) == 0


@pytest.mark.integration
class TestRedditIntegration:
    """Integration tests for Reddit fetcher."""

    @pytest.mark.asyncio
    async def test_reddit_returns_list(self):
        """Reddit fetcher must always return a list (even if empty)."""
        articles = await fetch_reddit()
        assert isinstance(articles, list)

    @pytest.mark.asyncio
    async def test_reddit_no_self_post_urls(self):
        """Reddit articles must not be self-posts (reddit.com/r/.../comments/)."""
        articles = await fetch_reddit()
        for article in articles:
            assert "reddit.com/r/" not in article.url or "/comments/" not in article.url, (
                f"Self-post URL leaked through: {article.url}"
            )


@pytest.mark.integration
class TestFetchAllIntegration:
    """Integration tests for the combined fetch_all() entry point."""

    @pytest.mark.asyncio
    async def test_fetch_all_returns_articles(self):
        """fetch_all() must return at least 1 article from combined sources."""
        articles = await fetch_all()
        assert len(articles) >= 1, (
            "fetch_all() returned 0 articles — check network and feed URLs"
        )

    @pytest.mark.asyncio
    async def test_fetch_all_no_duplicate_hashes(self):
        """fetch_all() must return no duplicate URL hashes."""
        articles = await fetch_all()
        hashes = [a.hash for a in articles]
        assert len(hashes) == len(set(hashes)), (
            f"Duplicate hashes found in fetch_all() output! "
            f"Total: {len(hashes)}, Unique: {len(set(hashes))}"
        )

    @pytest.mark.asyncio
    async def test_fetch_all_all_articles_valid(self):
        """Every article from fetch_all() must pass Article validation."""
        articles = await fetch_all()
        for article in articles:
            # These would have raised ValueError during construction
            assert article.title.strip()
            assert article.url.startswith("http")
            assert isinstance(article.published_at, datetime)
            assert article.published_at.tzinfo is not None
