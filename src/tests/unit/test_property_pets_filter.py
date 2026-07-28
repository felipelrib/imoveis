"""Regression: pets filter matches listing.accepts_pets (OLX + QuintoAndar) (BIN-110)."""

from __future__ import annotations

import pytest

from api.properties import PropertyListFilters, _build_list_filters


@pytest.mark.unit
class TestPetsFilterListingParity:
    def test_accepts_pets_true_matches_listing_column(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(accepts_pets=True),
            None,
        )
        assert "property_listings" in where
        assert "pl.accepts_pets IS TRUE" in where
        assert "pl.active = true" in where
        assert "PODE_TER_ANIMAIS_DE_ESTIMACAO" in where  # legacy QuintoAndar amenity
        assert "OR" in where

    def test_accepts_pets_false_negates_listing_or_amenity(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(accepts_pets=False),
            None,
        )
        assert where.startswith("p.active = true AND NOT ")
        assert "pl.accepts_pets IS TRUE" in where
        assert "PODE_TER_ANIMAIS_DE_ESTIMACAO" in where

    def test_accepts_pets_omitted_skips_pets_clause(self):
        where, params, _order = _build_list_filters(
            PropertyListFilters(),
            None,
        )
        assert "accepts_pets" not in where
        assert "PODE_TER_ANIMAIS_DE_ESTIMACAO" not in where
