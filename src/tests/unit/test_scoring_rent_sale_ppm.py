"""Unit tests for rent/sale price-per-m² primary-type helpers (BIN-84)."""

from adapters.metrics.scoring import primary_listing_type_for_ppm


class TestPrimaryListingTypeForPpm:
    def test_rent_preferred_when_both(self):
        assert primary_listing_type_for_ppm(47.0, 4079.0) == "rent"

    def test_sale_only(self):
        assert primary_listing_type_for_ppm(None, 4000.0) == "sale"

    def test_rent_only(self):
        assert primary_listing_type_for_ppm(50.0, None) == "rent"

    def test_neither(self):
        assert primary_listing_type_for_ppm(None, None) is None
