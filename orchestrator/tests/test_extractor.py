"""
orchestrator/tests/test_extractor.py
--------------------------------------
Phase 4 test suite for the OG Image Extractor.

Tests (Unit — all using pytest-mock to mock httpx responses):
  1. Valid og:image tag returned correctly
  2. twitter:image fallback works when og:image absent
  3. twitter:image:src fallback works when both above absent
  4. Returns None on HTTP error (non-200 status)
  5. Returns None on timeout
  6. Returns None when no image meta tag found
  7. Returns None if image URL does not start with http
  8. Returns None on connection error
  9. og:image with non-http URL is skipped (falls through to twitter:image)
 10. Empty content attribute is treated as missing

Integration Tests (marked @pytest.mark.integration):
  - Test against one real TechCrunch URL
  - Confirm a valid https:// image URL is returned

Run with:
    python -m pytest orchestrator/tests/test_extractor.py -v
    python -m pytest orchestrator/tests/test_extractor.py -v -m "not integration"
    python -m pytest orchestrator/tests/test_extractor.py -v -m integration
"""

import sys

import httpx
import pytest
import pytest_mock

sys.path.insert(0, ".")

from orchestrator.extractor.og_image import extract_og_image


# ------------------------------------------------------------------ #
# HTML Fixtures                                                        #
# ------------------------------------------------------------------ #

_HTML_WITH_OG_IMAGE = """
<html>
<head>
  <meta property="og:image" content="https://example.com/images/article.jpg" />
  <meta name="twitter:image" content="https://example.com/images/twitter.jpg" />
  <title>Test Article</title>
</head>
<body><p>Article content here.</p></body>
</html>
"""

_HTML_WITH_TWITTER_ONLY = """
<html>
<head>
  <meta name="twitter:image" content="https://example.com/images/twitter-only.jpg" />
  <title>Test Article</title>
</head>
<body><p>Article content here.</p></body>
</html>
"""

_HTML_WITH_TWITTER_SRC_ONLY = """
<html>
<head>
  <meta name="twitter:image:src" content="https://example.com/images/twitter-src.jpg" />
  <title>Test Article</title>
</head>
<body><p>Article content here.</p></body>
</html>
"""

_HTML_NO_IMAGE = """
<html>
<head>
  <title>Test Article — No Image Tags</title>
</head>
<body><p>Article without any OG or Twitter image tags.</p></body>
</html>
"""

_HTML_RELATIVE_URL = """
<html>
<head>
  <meta property="og:image" content="/images/relative-path.jpg" />
</head>
<body></body>
</html>
"""

_HTML_EMPTY_CONTENT = """
<html>
<head>
  <meta property="og:image" content="" />
  <meta name="twitter:image" content="" />
</head>
<body></body>
</html>
"""

_HTML_OG_NON_HTTP_FALLS_THROUGH = """
<html>
<head>
  <meta property="og:image" content="/relative/image.jpg" />
  <meta name="twitter:image" content="https://example.com/twitter-fallback.jpg" />
</head>
<body></body>
</html>
"""


# ------------------------------------------------------------------ #
# Mock Response Helper                                                 #
# ------------------------------------------------------------------ #

def _make_mock_response(status_code: int = 200, html: str = "") -> httpx.Response:
    """Build a minimal httpx.Response for mocking."""
    return httpx.Response(
        status_code=status_code,
        content=html.encode("utf-8"),
        headers={"content-type": "text/html; charset=utf-8"},
    )


# ------------------------------------------------------------------ #
# Unit Tests                                                           #
# ------------------------------------------------------------------ #

class TestExtractOgImage:
    """Unit tests for extract_og_image() using mocked httpx."""

    @pytest.mark.asyncio
    async def test_og_image_returned_when_present(self, mocker: pytest_mock.MockerFixture):
        """Valid og:image URL should be returned directly."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_WITH_OG_IMAGE)

        result = await extract_og_image("https://example.com/article")

        assert result == "https://example.com/images/article.jpg"

    @pytest.mark.asyncio
    async def test_twitter_image_fallback_when_og_absent(self, mocker: pytest_mock.MockerFixture):
        """When og:image is missing, twitter:image should be returned."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_WITH_TWITTER_ONLY)

        result = await extract_og_image("https://example.com/article")

        assert result == "https://example.com/images/twitter-only.jpg"

    @pytest.mark.asyncio
    async def test_twitter_image_src_fallback(self, mocker: pytest_mock.MockerFixture):
        """twitter:image:src should be used when og:image and twitter:image are missing."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_WITH_TWITTER_SRC_ONLY)

        result = await extract_og_image("https://example.com/article")

        assert result == "https://example.com/images/twitter-src.jpg"

    @pytest.mark.asyncio
    async def test_og_image_preferred_over_twitter(self, mocker: pytest_mock.MockerFixture):
        """When both og:image and twitter:image present, og:image wins."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_WITH_OG_IMAGE)

        result = await extract_og_image("https://example.com/article")

        # og:image should win — not twitter:image
        assert result == "https://example.com/images/article.jpg"
        assert result != "https://example.com/images/twitter.jpg"

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self, mocker: pytest_mock.MockerFixture):
        """HTTP 404 response should return None without raising."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(404, "")

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_500(self, mocker: pytest_mock.MockerFixture):
        """HTTP 500 response should return None without raising."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(500, "")

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self, mocker: pytest_mock.MockerFixture):
        """TimeoutException should be caught and None returned."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.side_effect = httpx.TimeoutException("Request timed out")

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self, mocker: pytest_mock.MockerFixture):
        """Connection error should be caught and None returned."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_image_tags(self, mocker: pytest_mock.MockerFixture):
        """Page with no og or twitter image tags should return None."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_NO_IMAGE)

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_relative_image_url(self, mocker: pytest_mock.MockerFixture):
        """og:image with relative path (no http) must return None."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_RELATIVE_URL)

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_content_attribute(self, mocker: pytest_mock.MockerFixture):
        """og:image and twitter:image with empty content="" must return None."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_EMPTY_CONTENT)

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_og_non_http_falls_through_to_twitter(self, mocker: pytest_mock.MockerFixture):
        """
        If og:image has a non-http URL (relative), should skip it and
        fall through to twitter:image which has a valid https URL.
        """
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(
            200, _HTML_OG_NON_HTTP_FALLS_THROUGH
        )

        result = await extract_og_image("https://example.com/article")

        assert result == "https://example.com/twitter-fallback.jpg"

    @pytest.mark.asyncio
    async def test_returns_none_on_too_many_redirects(self, mocker: pytest_mock.MockerFixture):
        """TooManyRedirects should be caught and None returned."""
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.side_effect = httpx.TooManyRedirects("Too many redirects")

        result = await extract_og_image("https://example.com/article")

        assert result is None

    @pytest.mark.asyncio
    async def test_result_always_starts_with_http(self, mocker: pytest_mock.MockerFixture):
        """
        Any returned URL must start with 'http' — never a relative path.
        """
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.return_value = _make_mock_response(200, _HTML_WITH_OG_IMAGE)

        result = await extract_og_image("https://example.com/article")

        if result is not None:
            assert result.startswith("http"), (
                f"Returned URL must start with 'http', got: {result!r}"
            )

    @pytest.mark.asyncio
    async def test_never_raises_on_generic_exception(self, mocker: pytest_mock.MockerFixture):
        """
        A completely unexpected exception must be caught — function must
        return None, never raise.
        """
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.side_effect = RuntimeError("Unexpected internal error")

        # This must NOT raise — must return None
        result = await extract_og_image("https://example.com/article")
        assert result is None

    @pytest.mark.asyncio
    async def test_url_not_logged_in_error_output(
        self, mocker: pytest_mock.MockerFixture, capsys
    ):
        """
        The article URL must NOT appear in stderr output (SECURITY requirement).
        Only component name and error type are allowed.
        """
        secret_url = "https://secret-article-url.example.com/private/path"
        mock_get = mocker.patch("httpx.AsyncClient.get")
        mock_get.side_effect = httpx.TimeoutException("timed out")

        await extract_og_image(secret_url)

        captured = capsys.readouterr()
        assert secret_url not in captured.err, (
            f"SECURITY: Article URL was logged to stderr! "
            f"URL: {secret_url!r} found in: {captured.err!r}"
        )
        assert "secret-article-url" not in captured.err


# ------------------------------------------------------------------ #
# Integration Tests — Real Network                                     #
# ------------------------------------------------------------------ #

@pytest.mark.integration
class TestExtractOgImageIntegration:
    """Integration tests making real HTTP requests."""

    @pytest.mark.asyncio
    async def test_techcrunch_returns_og_image(self):
        """
        Fetch a known TechCrunch article page and confirm an og:image
        with an https URL is returned.

        Uses TechCrunch AI section page (not a specific article) as it's
        more stable than a dated article URL.
        """
        # TechCrunch AI section — stable URL that should always have og:image
        test_url = "https://techcrunch.com/category/artificial-intelligence/"

        result = await extract_og_image(test_url)

        # Some pages may not have og:image or may block scrapers
        # We allow None but prefer a valid URL
        if result is not None:
            assert result.startswith("http"), (
                f"Image URL must start with 'http', got: {result!r}"
            )
            assert len(result) > 10, f"Image URL suspiciously short: {result!r}"
            print(f"\n[TEST] TechCrunch og:image: {result[:80]}")
        else:
            # If None, it means TechCrunch blocked or has no og:image
            # This is acceptable — extractor returned None gracefully
            print("\n[TEST] TechCrunch returned None — page may block scrapers")
            pytest.skip(
                "TechCrunch did not return an og:image — "
                "possible bot detection. Extractor returned None correctly."
            )

    @pytest.mark.asyncio
    async def test_fake_url_returns_none(self):
        """
        A completely fake URL must return None without raising.
        """
        result = await extract_og_image("https://this-definitely-does-not-exist-12345.fake/")
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_news_site_returns_none_or_https_url(self):
        """
        Real AI news article from VentureBeat — should return og:image or None,
        never raise an exception.
        """
        # VentureBeat AI section
        result = await extract_og_image("https://venturebeat.com/category/ai/")
        if result is not None:
            assert result.startswith("http")
        # Returning None is also acceptable (VentureBeat may block bots)
