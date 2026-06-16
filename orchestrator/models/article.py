"""
orchestrator/models/article.py
-------------------------------
Article dataclass — the single, canonical data model for every news item
processed by the pipeline.

All fetchers (RSS, HN, Reddit) must produce Article objects. Every downstream
component (filter, dedup, LLM, formatter) reads from this model only.

SECURITY: Never log `.description` or full `.url` contents to console.
          Log only `.source` and `.title[:60]` for safe output.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Article:
    """
    Canonical news article model used throughout the pipeline.

    Fields set by caller:
        title       — original article headline (non-empty string, required)
        url         — canonical article link (must start with 'http', required)
        description — raw RSS description or API summary; HTML stripped
                      before storage
        published_at — UTC-aware datetime of publication (required)
        source      — string identifier for the news source, e.g. 'techcrunch'

    Fields auto-generated:
        hash        — MD5 hex digest of url.strip().lower() (set in __post_init__)
                      used as the Layer-1 deduplication key in Supabase

    Optional fields (set downstream):
        og_image_url — HTTPS URL of the article's OG image, set by extractor
    """

    title: str
    url: str
    description: str
    published_at: datetime
    source: str

    # Auto-computed — not passed on construction
    hash: str = field(init=False)

    # Set downstream by og_image extractor (Phase 4)
    og_image_url: Optional[str] = None

    # Set during RSS fetch from media:content or enclosure tags
    # Used as fallback if HTTP OG extraction fails (many sites block bots)
    rss_image_url: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def __post_init__(self) -> None:
        """
        Validate all required fields and compute the URL hash.

        Raises:
            ValueError: If any field fails validation.
        """
        # --- title validation ---
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError(
                f"Article.title must be a non-empty string, "
                f"got: {type(self.title).__name__!r} = {self.title!r}"
            )

        # --- url validation ---
        # Use .lower() so HTTPS:// and https:// both pass (hash also uses .lower())
        if not isinstance(self.url, str) or not self.url.strip().lower().startswith("http"):
            raise ValueError(
                f"Article.url must start with 'http' (case-insensitive), "
                f"got: {self.url!r}"
            )

        # --- published_at validation ---
        if not isinstance(self.published_at, datetime):
            raise ValueError(
                f"Article.published_at must be a datetime object, "
                f"got: {type(self.published_at).__name__!r}"
            )

        # --- source validation ---
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError(
                f"Article.source must be a non-empty string, "
                f"got: {self.source!r}"
            )

        # --- Compute hash AFTER validation ---
        self.hash = hashlib.md5(
            self.url.strip().lower().encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------------ #
    # Representation                                                       #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        """
        Safe repr — never exposes description content.
        Title is truncated to 60 chars for safe console logging.
        """
        return (
            f"Article("
            f"source={self.source!r}, "
            f"title={self.title[:60]!r}, "
            f"hash={self.hash[:8]}..., "
            f"published_at={self.published_at.isoformat()}"
            f")"
        )

    def __eq__(self, other: object) -> bool:
        """Two articles are equal if they have the same hash (same URL)."""
        if not isinstance(other, Article):
            return NotImplemented
        return self.hash == other.hash

    def __hash__(self) -> int:  # type: ignore[override]
        """Make Article usable in sets and as dict keys (by URL hash)."""
        return hash(self.hash)
