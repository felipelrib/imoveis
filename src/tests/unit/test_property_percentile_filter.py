"""Cohort price/m2 percentile cap on the Properties list and export (v0.14-s1.7).

The builder is checked as text here; what the SQL selects on real rows is
``tests/integration/test_price_percentile_filter.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.properties import (
    PropertyExportFilters,
    PropertyListFilters,
    _build_list_filters,
    _export_filters_as_list_filters,
)

_ACTIVE_LISTING = (
    "AND EXISTS (SELECT 1 FROM property_listings pl "
    "WHERE pl.property_id = p.id AND pl.active = true "
    "AND pl.listing_type = '{type}'))"
)
RENT = (
    "(ms.price_per_m2_percentile_rent <= :max_price_per_m2_percentile "
    + _ACTIVE_LISTING.format(type="rent")
)
SALE = (
    "(ms.price_per_m2_percentile_sale <= :max_price_per_m2_percentile "
    + _ACTIVE_LISTING.format(type="sale")
)


def _build(**filters):
    where, params, _order = _build_list_filters(PropertyListFilters(**filters), None)
    return where, params


@pytest.mark.unit
class TestPricePercentileFilterBuilder:
    def test_rent_reads_the_rent_column_only(self):
        where, params = _build(listing_type="rent", max_price_per_m2_percentile=0.25)
        assert RENT in where
        assert "price_per_m2_percentile_sale" not in where
        assert params["max_price_per_m2_percentile"] == 0.25

    def test_sale_reads_the_sale_column_only(self):
        where, params = _build(listing_type="sale", max_price_per_m2_percentile=0.25)
        assert SALE in where
        assert "price_per_m2_percentile_rent" not in where
        assert params["max_price_per_m2_percentile"] == 0.25

    @pytest.mark.parametrize("listing_type", [None, "both"])
    def test_both_or_no_type_keeps_a_property_when_either_column_qualifies(
        self, listing_type
    ):
        where, params = _build(
            listing_type=listing_type, max_price_per_m2_percentile=0.5
        )
        assert "(" + RENT + " OR " + SALE + ")" in where
        assert params["max_price_per_m2_percentile"] == 0.5

    def test_pt_listing_type_alias_selects_the_same_column(self):
        where, _params = _build(listing_type="aluguel", max_price_per_m2_percentile=0.25)
        assert RENT in where
        assert "price_per_m2_percentile_sale" not in where

    def test_the_value_is_bound_never_spliced(self):
        where, params = _build(listing_type="rent", max_price_per_m2_percentile=0.37)
        assert "0.37" not in where
        assert params["max_price_per_m2_percentile"] == 0.37

    def test_the_legacy_percentile_rank_is_not_read(self):
        for listing_type in (None, "rent", "sale", "both"):
            where, _params = _build(
                listing_type=listing_type, max_price_per_m2_percentile=0.25
            )
            assert "percentile_rank" not in where

    def test_no_value_adds_no_clause_and_no_param(self):
        where, params = _build(listing_type="rent")
        assert "price_per_m2_percentile" not in where
        assert "max_price_per_m2_percentile" not in params

    def test_the_clause_is_anded_with_the_other_filters(self):
        where, params = _build(
            listing_type="rent", max_price_per_m2_percentile=0.25, min_bedrooms=2
        )
        assert " AND " + RENT in where
        assert "p.bedrooms >= :min_bedrooms" in where
        assert params["min_bedrooms"] == 2

    def test_one_is_the_inclusive_upper_bound(self):
        _where, params = _build(max_price_per_m2_percentile=1)
        assert params["max_price_per_m2_percentile"] == 1

    @pytest.mark.parametrize("value", [0, -0.1, 1.5, "abc"])
    @pytest.mark.parametrize("model", [PropertyListFilters, PropertyExportFilters])
    def test_a_value_outside_the_range_is_rejected(self, model, value):
        with pytest.raises(ValidationError):
            model(max_price_per_m2_percentile=value)

    def test_export_filters_carry_the_value(self):
        list_filters = _export_filters_as_list_filters(
            PropertyExportFilters(listing_type="sale", max_price_per_m2_percentile=0.5)
        )
        assert list_filters.max_price_per_m2_percentile == 0.5
        where, params, _order = _build_list_filters(list_filters, None)
        assert SALE in where
        assert params["max_price_per_m2_percentile"] == 0.5
