"""Unit tests for the dedupe noop detection (unchanged properties)."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.dedupe import _is_unchanged


class TestIsUnchanged:
    """Tests for _is_unchanged helper."""

    def _make_existing(self, **overrides):
        """Build a mock Property-like object with sensible defaults."""
        obj = MagicMock()
        obj.price = overrides.get("price", 5000.0)
        obj.title = overrides.get("title", "Apartamento 2 quartos")
        obj.description = overrides.get("description", "Descrição do imóvel")
        obj.image_urls = overrides.get("image_urls", ["https://img.example.com/1.jpg"])
        return obj

    def _make_candidate(self, **overrides):
        """Build a mock PropertyCandidate-like object with sensible defaults."""
        obj = MagicMock()
        obj.price = overrides.get("price", 5000.0)
        obj.title = overrides.get("title", "Apartamento 2 quartos")
        obj.description = overrides.get("description", "Descrição do imóvel")
        obj.image_urls = overrides.get("image_urls", ["https://img.example.com/1.jpg"])
        obj.listings = overrides.get("listings", [])
        return obj

    def _make_session_with_listings(self, listings=None):
        """Build a mock session that returns empty listings by default."""
        session = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.all.return_value = listings or []
        query_mock.filter.return_value = filter_mock
        session.query.return_value.filter.return_value = filter_mock
        # Make session.query(PropertyListing).filter(...) work
        session.query.return_value = query_mock
        return session

    def test_unchanged_returns_true(self):
        """Identical data → noop."""
        existing = self._make_existing()
        candidate = self._make_candidate()
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is True

    def test_price_changed_returns_false(self):
        """Different price → not noop."""
        existing = self._make_existing(price=5000.0)
        candidate = self._make_candidate(price=6000.0)
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is False

    def test_title_changed_returns_false(self):
        """Different title → not noop."""
        existing = self._make_existing(title="Original")
        candidate = self._make_candidate(title="Changed")
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is False

    def test_description_changed_returns_false(self):
        """Different description → not noop."""
        existing = self._make_existing(description="Old desc")
        candidate = self._make_candidate(description="New desc")
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is False

    def test_images_changed_returns_false(self):
        """Different image URLs → not noop."""
        existing = self._make_existing(image_urls=["https://img.example.com/1.jpg"])
        candidate = self._make_candidate(image_urls=["https://img.example.com/2.jpg"])
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is False

    def test_images_order_independent(self):
        """Same images in different order → noop (compared as sorted lists)."""
        existing = self._make_existing(image_urls=["https://img.example.com/2.jpg", "https://img.example.com/1.jpg"])
        candidate = self._make_candidate(image_urls=["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"])
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is True

    def test_empty_images_match(self):
        """Both empty image lists → noop."""
        existing = self._make_existing(image_urls=[])
        candidate = self._make_candidate(image_urls=[])
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is True

    def test_none_images_treated_as_empty(self):
        """None image_urls treated as empty → noop when candidate also empty."""
        existing = self._make_existing(image_urls=None)
        candidate = self._make_candidate(image_urls=None)
        session = self._make_session_with_listings()

        assert _is_unchanged(session, existing, candidate) is True

    def test_listing_price_changed_returns_false(self):
        """Existing listing with different price → not noop."""
        existing_listing = MagicMock()
        existing_listing.platform = "olx"
        existing_listing.platform_listing_id = "12345"
        existing_listing.listing_type = "rent"
        existing_listing.price = 2000.0

        session = self._make_session_with_listings([existing_listing])
        candidate = self._make_candidate(
            listings=[
                {
                    "platform": "olx",
                    "platform_listing_id": "12345",
                    "listing_type": "rent",
                    "price": 2500.0,  # Changed price
                }
            ]
        )

        assert _is_unchanged(session, self._make_existing(), candidate) is False

    def test_listing_price_unchanged_returns_true(self):
        """Existing listing with same price → noop."""
        existing_listing = MagicMock()
        existing_listing.platform = "olx"
        existing_listing.platform_listing_id = "12345"
        existing_listing.listing_type = "rent"
        existing_listing.price = 2000.0

        session = self._make_session_with_listings([existing_listing])
        candidate = self._make_candidate(
            listings=[
                {
                    "platform": "olx",
                    "platform_listing_id": "12345",
                    "listing_type": "rent",
                    "price": 2000.0,  # Same price
                }
            ]
        )

        assert _is_unchanged(session, self._make_existing(), candidate) is True

    def test_fallback_on_exception_returns_true(self):
        """If PropertyListing query fails, fall back to property-level comparison → noop."""
        session = MagicMock()
        session.query.side_effect = Exception("table not found")

        assert _is_unchanged(session, self._make_existing(), self._make_candidate()) is True
