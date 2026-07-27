"""Regression: filter-aware combined score sort/min_score (BIN-83)."""

from __future__ import annotations

import pytest

from api.properties import PropertyListFilters, _build_list_filters, _effective_combined_score_expr


@pytest.mark.unit
class TestEffectiveCombinedScoreExpr:
    def test_rent_uses_typed_column_with_fallback(self):
        assert _effective_combined_score_expr("rent") == (
            "COALESCE(ms.combined_score_rent, ms.combined_score, 0)"
        )

    def test_sale_uses_typed_column_with_fallback(self):
        assert _effective_combined_score_expr("sale") == (
            "COALESCE(ms.combined_score_sale, ms.combined_score, 0)"
        )

    def test_both_uses_primary(self):
        assert _effective_combined_score_expr("both") == "COALESCE(ms.combined_score, 0)"
        assert _effective_combined_score_expr(None) == "COALESCE(ms.combined_score, 0)"


@pytest.mark.unit
class TestListScoreFilterAware:
    def test_min_score_uses_sale_combined_when_listing_type_sale(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(min_score=0.5, listing_type="sale"),
            None,
        )
        assert "COALESCE(ms.combined_score_sale, ms.combined_score, 0) >= :min_score" in where
        assert params["min_score"] == 0.5

    def test_min_score_uses_rent_combined_when_listing_type_rent(self):
        where, _params, _order = _build_list_filters(
            PropertyListFilters(min_score=0.6, listing_type="rent"),
            None,
        )
        assert "COALESCE(ms.combined_score_rent, ms.combined_score, 0) >= :min_score" in where

    def test_sort_combined_score_uses_sale_column(self):
        _where, _params, order = _build_list_filters(
            PropertyListFilters(sort_by="combined_score", listing_type="sale", sort_dir="desc"),
            None,
        )
        assert "COALESCE(ms.combined_score_sale, ms.combined_score, 0) DESC" in order

    def test_sort_combined_score_both_uses_primary(self):
        _where, _params, order = _build_list_filters(
            PropertyListFilters(sort_by="combined_score", listing_type="both"),
            None,
        )
        assert "COALESCE(ms.combined_score, 0)" in order
        assert "combined_score_sale" not in order
