"""Regression: max_price filters by rent/sale listing price (BIN-77)."""

from __future__ import annotations

import pytest

from api.properties import PropertyListFilters, _build_list_filters


@pytest.mark.unit
class TestMaxPriceListingTypeFilter:
    def test_max_price_defaults_to_rent_listing_when_price_type_omitted(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(max_price=500_000),
            None,
        )
        assert "property_listings" in where
        assert "pl.listing_type = :price_type" in where
        assert "pl.price <= :max_price" in where
        assert params["max_price"] == 500_000
        assert params["price_type"] == "rent"
        assert "p.price <= :max_price" not in where

    def test_max_price_sale_uses_sale_listing_price(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(max_price=500_000, price_type="sale"),
            None,
        )
        assert params["price_type"] == "sale"
        assert "pl.listing_type = :price_type" in where
        assert params["max_price"] == 500_000

    def test_max_price_inherits_listing_type_when_price_type_omitted(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(max_price=900_000, listing_type="sale"),
            None,
        )
        assert params["price_type"] == "sale"

    def test_explicit_price_type_overrides_listing_type(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(max_price=10_000, listing_type="sale", price_type="rent"),
            None,
        )
        assert params["price_type"] == "rent"

    def test_no_max_price_skips_listing_price_clause(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(price_type="sale"),
            None,
        )
        assert "property_listings" not in where or "pl.price <=" not in where
        assert "max_price" not in params
        assert "price_type" not in params
