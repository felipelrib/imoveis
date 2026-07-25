"""Unit tests for property list city / neighborhood filter builders (BIN-70)."""

from __future__ import annotations

import pytest

from api.properties import (
    PropertyListFilters,
    _append_city_filters,
    _append_neighborhood_filters,
    _build_list_filters,
)


@pytest.mark.unit
class TestCityNeighborhoodFilterBuilders:
    def test_city_filter_comma_or(self):
        filters: list[str] = []
        params: dict = {}
        _append_city_filters(filters, params, "Belo Horizonte,São Paulo")
        assert len(filters) == 1
        assert "OR" in filters[0]
        assert params["city_0"] == "%Belo Horizonte%"
        assert params["city_1"] == "%São Paulo%"

    def test_city_filter_empty_noop(self):
        filters: list[str] = []
        params: dict = {}
        _append_city_filters(filters, params, "  ,  ")
        assert filters == []
        assert params == {}

    def test_neighborhood_filter_still_works(self):
        filters: list[str] = []
        params: dict = {}
        _append_neighborhood_filters(filters, params, "Savassi")
        assert len(filters) == 1
        assert params["nbr_0"] == "%Savassi%"


@pytest.mark.unit
class TestPropertyTypeFilter:
    def test_property_type_matches_canonical_and_legacy(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(property_type="apartment"),
            None,
        )
        assert "LOWER(p.props_json->>'type') IN" in where
        bound = {v for k, v in params.items() if k.startswith("pt")}
        assert "apartment" in bound
        assert "apartamento" in bound
