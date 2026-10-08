"""Characterization lock: the Properties list ``WHERE`` (v0.14-s1.9).

Landed before the list predicates move out of ``api/properties.py``. It pins
the exact ``WHERE`` text, the bound parameters and the ``ORDER BY`` that
``_build_list_filters`` returns today, for filter sets that together exercise
every membership filter. The saved-search matcher of Story 1.9 reuses these
predicates; a moved builder that changes one character fails here.

Not edited after its first commit, with one recorded exception: the pets
predicate (``_PETS``) gained its ``jsonb`` cast in the commit that fixed
``accepts_pets`` on Postgres. The text locked before was a statement Postgres
rejects (``json ? unknown``), so there was no working behaviour to preserve.
"""

from __future__ import annotations

import pytest

from api.properties import PropertyListFilters, _build_list_filters

_ACTIVE_LISTING = (
    "SELECT 1 FROM property_listings pl WHERE pl.property_id = p.id AND pl.active = true"
)
_MAX_PRICE = (
    "EXISTS (" + _ACTIVE_LISTING + " AND pl.listing_type = :price_type "
    "AND pl.price IS NOT NULL AND pl.price <= :max_price)"
)
_RENT_WITH_TOTAL = (
    _ACTIVE_LISTING + " AND pl.listing_type = 'rent' AND pl.total_monthly_cost IS NOT NULL"
)
_TOTAL_CAP = (
    "EXISTS (" + _RENT_WITH_TOTAL + " AND pl.total_monthly_cost <= :max_total_monthly_cost)"
)
_TOTAL_INCOMPLETE = (
    "(EXISTS (" + _ACTIVE_LISTING + " AND pl.listing_type = 'rent') "
    "AND NOT EXISTS (" + _RENT_WITH_TOTAL + "))"
)
_PERCENTILE_RENT = (
    "(ms.price_per_m2_percentile_rent <= :max_price_per_m2_percentile "
    "AND EXISTS (" + _ACTIVE_LISTING + " AND pl.listing_type = 'rent'))"
)
_PERCENTILE_SALE = (
    "(ms.price_per_m2_percentile_sale <= :max_price_per_m2_percentile "
    "AND EXISTS (" + _ACTIVE_LISTING + " AND pl.listing_type = 'sale'))"
)
_PETS = (
    "(EXISTS (" + _ACTIVE_LISTING + " AND pl.accepts_pets IS TRUE) "
    "OR COALESCE((p.props_json->'amenities')::jsonb ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO', false))"
)


def _where(*predicates: str) -> str:
    return " AND ".join(predicates)


def _build(vec=None, **filters):
    return _build_list_filters(PropertyListFilters(**filters), vec)


@pytest.mark.unit
class TestPropertyListWhereLock:
    def test_every_filter_with_rent(self):
        where, params, order = _build(
            page=3,
            page_size=10,
            platform="olx",
            min_score=0.6,
            max_price=4000,
            min_bedrooms=2,
            min_parking=1,
            neighborhood_name="Savassi, Lourdes",
            city_name="Belo Horizonte,Contagem",
            listing_type="rent",
            property_type="apartment",
            is_furnished=True,
            accepts_pets=True,
            max_total_monthly_cost=5000,
            max_price_per_m2_percentile=0.25,
            bbox="-44.1,-20.0,-43.8,-19.8",
        )
        assert where == _where(
            "p.active = true",
            "p.platform = :platform",
            _MAX_PRICE,
            _TOTAL_CAP,
            _PERCENTILE_RENT,
            "p.bedrooms >= :min_bedrooms",
            "p.parking >= :min_parking",
            "((n.name ILIKE :nbr_0 OR p.props_json->>'neighborhood' ILIKE :nbr_0) "
            "OR (n.name ILIKE :nbr_1 OR p.props_json->>'neighborhood' ILIKE :nbr_1))",
            "((COALESCE(n.city, p.props_json->>'city') ILIKE :city_0) "
            "OR (COALESCE(n.city, p.props_json->>'city') ILIKE :city_1))",
            "COALESCE(ms.combined_score_rent, ms.combined_score, 0) >= :min_score",
            "(p.props_json->>'available_for_rent')::boolean = true",
            "LOWER(p.props_json->>'type') IN (:pt0, :pt1, :pt2, :pt3, :pt4)",
            "(p.props_json->>'isFurnished')::boolean = :is_furnished",
            _PETS,
            "ST_Within(p.location, ST_MakeEnvelope("
            ":bbox_min_lon, :bbox_min_lat, :bbox_max_lon, :bbox_max_lat, 4326)) = true",
        )
        assert params == {
            "limit": 10,
            "offset": 20,
            "platform": "olx",
            "max_price": 4000.0,
            "price_type": "rent",
            "max_total_monthly_cost": 5000.0,
            "max_price_per_m2_percentile": 0.25,
            "min_bedrooms": 2,
            "min_parking": 1,
            "nbr_0": "%Savassi%",
            "nbr_1": "%Lourdes%",
            "city_0": "%Belo Horizonte%",
            "city_1": "%Contagem%",
            "min_score": 0.6,
            "pt0": "apartamento",
            "pt1": "apartamentos",
            "pt2": "apartment",
            "pt3": "apt",
            "pt4": "apto",
            "is_furnished": True,
            "bbox_min_lon": -44.1,
            "bbox_min_lat": -20.0,
            "bbox_max_lon": -43.8,
            "bbox_max_lat": -19.8,
        }
        assert order == "COALESCE(ms.combined_score_rent, ms.combined_score, 0) DESC"

    def test_both_types_with_the_widening_and_negated_forms(self):
        where, params, order = _build(
            max_price=900000,
            price_type="sale",
            listing_type="both",
            is_furnished=False,
            accepts_pets=False,
            max_total_monthly_cost=3500,
            include_incomplete_totals=True,
            max_price_per_m2_percentile=0.5,
            min_score=0.4,
        )
        assert where == _where(
            "p.active = true",
            _MAX_PRICE,
            "(" + _TOTAL_CAP + " OR " + _TOTAL_INCOMPLETE + ")",
            "(" + _PERCENTILE_RENT + " OR " + _PERCENTILE_SALE + ")",
            "COALESCE(ms.combined_score, 0) >= :min_score",
            "(p.props_json->>'isFurnished')::boolean = :is_furnished",
            "NOT " + _PETS,
        )
        assert params == {
            "limit": 24,
            "offset": 0,
            "max_price": 900000.0,
            "price_type": "sale",
            "max_total_monthly_cost": 3500.0,
            "max_price_per_m2_percentile": 0.5,
            "min_score": 0.4,
            "is_furnished": False,
        }
        assert order == "COALESCE(ms.combined_score, 0) DESC"

    def test_sale_with_a_query_vector(self):
        where, params, order = _build(
            "[0.1,0.2]",
            listing_type="sale",
            max_price=500000,
            min_score=0.2,
            max_price_per_m2_percentile=0.25,
            q="varanda",
        )
        assert where == _where(
            "p.active = true",
            "p.embedding IS NOT NULL",
            _MAX_PRICE,
            _PERCENTILE_SALE,
            "COALESCE(ms.combined_score_sale, ms.combined_score, 0) >= :min_score",
            "(p.props_json->>'available_for_sale')::boolean = true",
        )
        assert params == {
            "limit": 24,
            "offset": 0,
            "q_vec": "[0.1,0.2]",
            "max_price": 500000.0,
            "price_type": "sale",
            "max_price_per_m2_percentile": 0.25,
            "min_score": 0.2,
        }
        assert order == "p.embedding <=> CAST(:q_vec AS vector)"

    def test_no_filter(self):
        where, params, order = _build()
        assert where == "p.active = true"
        assert params == {"limit": 24, "offset": 0}
        assert order == "COALESCE(ms.combined_score, 0) DESC"

    def test_max_price_without_any_type_caps_rent(self):
        _where_text, params, _order = _build(max_price=2500)
        assert params["price_type"] == "rent"

    def test_incomplete_totals_alone_adds_nothing(self):
        where, params, _order = _build(include_incomplete_totals=True)
        assert where == "p.active = true"
        assert "max_total_monthly_cost" not in params

    def test_a_malformed_bbox_adds_nothing(self):
        where, _params, _order = _build(bbox="1,2,x")
        assert where == "p.active = true"
