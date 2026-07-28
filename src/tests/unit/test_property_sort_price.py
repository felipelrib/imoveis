"""Regression: listing-type-aware sort-by-price (BIN-106)."""

from __future__ import annotations

import pytest

from api.properties import (
    PropertyListFilters,
    _build_list_filters,
    _effective_sort_price_type,
)


@pytest.mark.unit
class TestEffectiveSortPriceType:
    def test_explicit_price_type_wins(self):
        assert _effective_sort_price_type("sale", "rent") == "sale"
        assert _effective_sort_price_type("rent", "sale") == "rent"

    def test_inherits_listing_type_when_price_type_omitted(self):
        assert _effective_sort_price_type(None, "sale") == "sale"
        assert _effective_sort_price_type(None, "rent") == "rent"

    def test_both_or_omitted_returns_none(self):
        assert _effective_sort_price_type(None, "both") is None
        assert _effective_sort_price_type(None, None) is None


@pytest.mark.unit
class TestSortByPriceListingTypeAware:
    def test_listing_type_sale_orders_by_sale_listing_price(self):
        _where, params, order = _build_list_filters(
            PropertyListFilters(sort_by="price", listing_type="sale", sort_dir="asc"),
            None,
        )
        assert "property_listings" in order
        assert ":sort_price_type" in order
        assert "COALESCE" in order
        assert params["sort_price_type"] == "sale"
        assert order.startswith("COALESCE") or "ASC" in order

    def test_listing_type_rent_orders_by_rent_listing_price(self):
        _where, params, order = _build_list_filters(
            PropertyListFilters(sort_by="price", listing_type="rent", sort_dir="asc"),
            None,
        )
        assert params["sort_price_type"] == "rent"
        assert ":sort_price_type" in order

    def test_listing_type_both_keeps_decisioning_p_price(self):
        _where, params, order = _build_list_filters(
            PropertyListFilters(sort_by="price", listing_type="both", sort_dir="asc"),
            None,
        )
        assert order == "p.price ASC"
        assert "sort_price_type" not in params

    def test_omitted_listing_type_keeps_decisioning_p_price(self):
        _where, params, order = _build_list_filters(
            PropertyListFilters(sort_by="price", sort_dir="desc"),
            None,
        )
        assert order == "p.price DESC"
        assert "sort_price_type" not in params

    def test_price_type_sale_with_both_uses_typed_sale(self):
        _where, params, order = _build_list_filters(
            PropertyListFilters(
                sort_by="price",
                listing_type="both",
                price_type="sale",
                sort_dir="asc",
            ),
            None,
        )
        assert params["sort_price_type"] == "sale"
        assert ":sort_price_type" in order

    def test_price_type_overrides_conflicting_listing_type(self):
        _where, params, order = _build_list_filters(
            PropertyListFilters(
                sort_by="price",
                listing_type="sale",
                price_type="rent",
                sort_dir="asc",
            ),
            None,
        )
        assert params["sort_price_type"] == "rent"
        assert ":sort_price_type" in order
