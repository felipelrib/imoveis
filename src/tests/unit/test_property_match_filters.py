"""The shared list ``WHERE`` (v0.14-s1.9): one builder for the API and the matcher."""

from __future__ import annotations

import dataclasses

import pytest

from api.properties import PropertyExportFilters, PropertyListFilters, _build_list_filters
from core.property_list_filters import PropertyMatchFilters, build_property_where

# Fields of the list model that do not decide membership.
_NOT_MEMBERSHIP = {"page", "page_size", "sort_by", "sort_dir", "q"}

_SAMPLE = dict(
    platform="olx",
    min_score=0.6,
    max_price=4000.0,
    min_bedrooms=2,
    min_parking=1,
    neighborhood_name="Savassi, Lourdes",
    city_name="Belo Horizonte",
    listing_type="rent",
    property_type="apartment",
    is_furnished=True,
    accepts_pets=True,
    max_total_monthly_cost=5000.0,
    include_incomplete_totals=True,
    max_price_per_m2_percentile=0.25,
    bbox="-44.1,-20.0,-43.8,-19.8",
)


@pytest.mark.unit
class TestPropertyMatchFilters:
    def test_every_list_filter_is_membership_or_declared_otherwise(self):
        """A new list filter must reach the matcher or be listed as not membership."""
        match_fields = {f.name for f in dataclasses.fields(PropertyMatchFilters)}
        list_fields = set(PropertyListFilters.model_fields)
        assert list_fields - _NOT_MEMBERSHIP == match_fields
        assert _NOT_MEMBERSHIP <= list_fields

    def test_export_filters_carry_the_same_membership_fields(self):
        match_fields = {f.name for f in dataclasses.fields(PropertyMatchFilters)}
        assert match_fields <= set(PropertyExportFilters.model_fields)

    def test_defaults_match_the_api_model(self):
        api_defaults = PropertyListFilters()
        for field in dataclasses.fields(PropertyMatchFilters):
            assert field.default == getattr(api_defaults, field.name), field.name

    def test_the_dataclass_and_the_api_model_build_the_same_where(self):
        predicates, params = build_property_where(PropertyMatchFilters(**_SAMPLE))
        where, api_params, _order = _build_list_filters(PropertyListFilters(**_SAMPLE), None)
        assert " AND ".join(predicates) == where
        assert params == {k: v for k, v in api_params.items() if k not in ("limit", "offset")}

    def test_membership_has_no_pagination_or_vector_parameter(self):
        predicates, params = build_property_where(
            PropertyMatchFilters(**_SAMPLE), require_embedding=True
        )
        assert predicates[:2] == ["p.active = true", "p.embedding IS NOT NULL"]
        assert not {"limit", "offset", "q_vec"} & set(params)

    def test_no_filter_is_the_active_predicate_alone(self):
        assert build_property_where(PropertyMatchFilters()) == (["p.active = true"], {})
