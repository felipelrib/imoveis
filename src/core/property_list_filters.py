"""Which Properties a filter set selects: the one ``WHERE`` of the product.

``GET /properties`` (and the export) and the saved-search matcher of Story 1.9
build their predicates here, so a saved search cannot mean one thing in the
grid and another in an alert. Order / sort, pagination and the semantic query
stay in the API; this module only says which rows are members.

Every fragment is static text over the aliases ``p`` (``properties``), ``ms``
(``metrics_scoring``) and ``n`` (``neighborhoods``); every value is a bound
parameter (BIN-135). The parameter names with an index (``nbr_0``, ``city_0``,
``pt0``) are generated from a counter, never from user text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.property_type import match_values_for_filter


def effective_combined_score_expr(listing_type: Optional[str]) -> str:
    """SQL expression for filter-aware combined score (BIN-83)."""
    if listing_type == "rent":
        return "COALESCE(ms.combined_score_rent, ms.combined_score, 0)"
    if listing_type == "sale":
        return "COALESCE(ms.combined_score_sale, ms.combined_score, 0)"
    return "COALESCE(ms.combined_score, 0)"


# Total Monthly Cost sort / cap (v0.14-s1.2, FR-31, AD-12). Static SQL: the
# only cost column referenced is ``total_monthly_cost`` and the only value is a
# bound parameter (BIN-135). The predicate - active, rent, total not null - is
# the one ``core.property_projection.select_deciding_listing`` applies, so the
# list order and ``deciding_listing_id`` cannot disagree. ``listing_type =
# 'rent'`` is a literal on purpose: totals exist for rent Listings only (AD-3).
ACTIVE_RENT_LISTING_WITH_TOTAL = (
    "FROM property_listings pl "
    "WHERE pl.property_id = p.id AND pl.active = true "
    "AND pl.listing_type = 'rent' AND pl.total_monthly_cost IS NOT NULL"
)

TOTAL_MONTHLY_COST_CAP = (
    "EXISTS (SELECT 1 "
    + ACTIVE_RENT_LISTING_WITH_TOTAL
    + " AND pl.total_monthly_cost <= :max_total_monthly_cost)"
)

# "Incomplete" = has an active rent Listing, none of them with a total. A
# sale-only Property is not incomplete: a monthly-cost cap has no meaning for it.
TOTAL_MONTHLY_COST_INCOMPLETE = (
    "(EXISTS (SELECT 1 FROM property_listings pl "
    "WHERE pl.property_id = p.id AND pl.active = true "
    "AND pl.listing_type = 'rent') "
    "AND NOT EXISTS (SELECT 1 " + ACTIVE_RENT_LISTING_WITH_TOTAL + "))"
)


# Cohort price/m2 percentile cap (v0.14-s1.7, FR-30). Static SQL over the
# stored ``metrics_scoring`` columns of Story 1.6; the only value is a bound
# parameter and the listing types are literals (BIN-135). A NULL percentile
# (suppressed cohort, not a member, no scoring row) makes the comparison NULL,
# so it never matches. With a listing type only that type's column is read (no
# cross-type leakage, BIN-77); with ``both`` or none, a Property qualifies when
# either of its price lines does. A column only counts while the Property has
# an active Listing of that type: the stored value outlives a deactivated
# Listing until the next scoring run, and the card has no price line (so no
# badge) for a type without one. The legacy ``percentile_rank*`` columns are
# never read here.
PRICE_PERCENTILE_CAP_RENT = (
    "(ms.price_per_m2_percentile_rent <= :max_price_per_m2_percentile "
    "AND EXISTS (SELECT 1 FROM property_listings pl "
    "WHERE pl.property_id = p.id AND pl.active = true "
    "AND pl.listing_type = 'rent'))"
)
PRICE_PERCENTILE_CAP_SALE = (
    "(ms.price_per_m2_percentile_sale <= :max_price_per_m2_percentile "
    "AND EXISTS (SELECT 1 FROM property_listings pl "
    "WHERE pl.property_id = p.id AND pl.active = true "
    "AND pl.listing_type = 'sale'))"
)
PRICE_PERCENTILE_CAP_BY_LISTING_TYPE = {
    "rent": PRICE_PERCENTILE_CAP_RENT,
    "sale": PRICE_PERCENTILE_CAP_SALE,
}
PRICE_PERCENTILE_CAP_EITHER = (
    "(" + PRICE_PERCENTILE_CAP_RENT + " OR " + PRICE_PERCENTILE_CAP_SALE + ")"
)

_MAX_PRICE_CAP = (
    "EXISTS ("
    "SELECT 1 FROM property_listings pl "
    "WHERE pl.property_id = p.id "
    "AND pl.active = true "
    "AND pl.listing_type = :price_type "
    "AND pl.price IS NOT NULL "
    "AND pl.price <= :max_price"
    ")"
)

# Prefer listing.accepts_pets (OLX + QuintoAndar); keep QA amenity for legacy rows.
# ``props_json`` is ``json`` and the ``?`` operator exists for ``jsonb`` only,
# hence the cast (without it Postgres rejects the statement). ``COALESCE``
# makes a Property without an ``amenities`` key plainly "not known to accept
# pets", so the negated form keeps it instead of losing it to a NULL.
_PETS_MATCH = (
    "("
    "EXISTS ("
    "SELECT 1 FROM property_listings pl "
    "WHERE pl.property_id = p.id "
    "AND pl.active = true "
    "AND pl.accepts_pets IS TRUE"
    ") "
    "OR COALESCE((p.props_json->'amenities')::jsonb ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO', false)"
    ")"
)

_LISTING_TYPE_AVAILABLE = {
    "rent": "(p.props_json->>'available_for_rent')::boolean = true",
    "sale": "(p.props_json->>'available_for_sale')::boolean = true",
}


@dataclass(frozen=True)
class PropertyMatchFilters:
    """The membership filters of the Properties list, and nothing else.

    Same names, types and defaults as ``api.properties.PropertyListFilters``
    minus pagination, sort and ``q``. A unit test fails when the API model
    gains a field that is in neither set.
    """

    platform: Optional[str] = None
    min_score: Optional[float] = None
    max_price: Optional[float] = None
    price_type: Optional[str] = None
    min_bedrooms: Optional[int] = None
    min_parking: Optional[int] = None
    neighborhood_name: Optional[str] = None
    city_name: Optional[str] = None
    listing_type: Optional[str] = None
    property_type: Optional[str] = None
    is_furnished: Optional[bool] = None
    accepts_pets: Optional[bool] = None
    max_total_monthly_cost: Optional[float] = None
    include_incomplete_totals: bool = False
    max_price_per_m2_percentile: Optional[float] = None
    bbox: Optional[str] = None


def append_neighborhood_filters(
    filters: list[str],
    params: Dict[str, Any],
    neighborhood_name: str,
) -> None:
    names = [n.strip() for n in neighborhood_name.split(",") if n.strip()]
    if not names:
        return
    nbr_filters = []
    for i, name in enumerate(names):
        key = "nbr_" + str(i)
        nbr_filters.append(
            "(n.name ILIKE :" + key + " OR p.props_json->>'neighborhood' ILIKE :" + key + ")"
        )
        params[key] = "%" + name + "%"
    filters.append("(" + " OR ".join(nbr_filters) + ")")


def append_city_filters(
    filters: list[str],
    params: Dict[str, Any],
    city_name: str,
) -> None:
    names = [n.strip() for n in city_name.split(",") if n.strip()]
    if not names:
        return
    city_filters = []
    for i, name in enumerate(names):
        key = "city_" + str(i)
        city_filters.append("(COALESCE(n.city, p.props_json->>'city') ILIKE :" + key + ")")
        params[key] = "%" + name + "%"
    filters.append("(" + " OR ".join(city_filters) + ")")


def append_bbox_filter(filters: list[str], params: Dict[str, Any], bbox: str) -> None:
    try:
        parts = [float(x.strip()) for x in bbox.split(",")]
    except ValueError:
        return
    if len(parts) != 4:
        return
    min_lon, min_lat, max_lon, max_lat = parts
    filters.append(
        "ST_Within(p.location, ST_MakeEnvelope("
        ":bbox_min_lon, :bbox_min_lat, :bbox_max_lon, :bbox_max_lat, 4326)) = true"
    )
    params["bbox_min_lon"] = min_lon
    params["bbox_min_lat"] = min_lat
    params["bbox_max_lon"] = max_lon
    params["bbox_max_lat"] = max_lat


def build_property_where(
    filters_in: Any, *, require_embedding: bool = False
) -> tuple[list[str], Dict[str, Any]]:
    """Return the predicates (to be joined with ``AND``) and their bound values.

    ``filters_in`` is any object with the attributes of
    ``PropertyMatchFilters``: the dataclass itself or the API's pydantic model.
    The first predicate is always ``p.active = true``. ``limit`` / ``offset`` /
    ``q_vec`` are not parameters of membership and are never returned.
    """
    filters = ["p.active = true"]
    params: Dict[str, Any] = {}

    if require_embedding:
        filters.append("p.embedding IS NOT NULL")

    if filters_in.platform:
        filters.append("p.platform = :platform")
        params["platform"] = filters_in.platform
    if filters_in.max_price is not None:
        # Decisioning ``p.price`` is the lowest listing (rent preferred). Cap against
        # the chosen rent/sale listing instead so sale budgets are not matched on rent.
        price_type = filters_in.price_type
        if price_type is None and filters_in.listing_type in ("rent", "sale"):
            price_type = filters_in.listing_type
        if price_type is None:
            price_type = "rent"
        filters.append(_MAX_PRICE_CAP)
        params["max_price"] = filters_in.max_price
        params["price_type"] = price_type
    if filters_in.max_total_monthly_cost is not None:
        # ``include_incomplete_totals`` only widens a cap; alone it is a no-op.
        if filters_in.include_incomplete_totals:
            filters.append(
                "(" + TOTAL_MONTHLY_COST_CAP + " OR " + TOTAL_MONTHLY_COST_INCOMPLETE + ")"
            )
        else:
            filters.append(TOTAL_MONTHLY_COST_CAP)
        params["max_total_monthly_cost"] = filters_in.max_total_monthly_cost
    if filters_in.max_price_per_m2_percentile is not None:
        filters.append(
            PRICE_PERCENTILE_CAP_BY_LISTING_TYPE.get(
                filters_in.listing_type or "", PRICE_PERCENTILE_CAP_EITHER
            )
        )
        params["max_price_per_m2_percentile"] = filters_in.max_price_per_m2_percentile
    if filters_in.min_bedrooms is not None:
        filters.append("p.bedrooms >= :min_bedrooms")
        params["min_bedrooms"] = filters_in.min_bedrooms
    if filters_in.min_parking is not None:
        filters.append("p.parking >= :min_parking")
        params["min_parking"] = filters_in.min_parking
    if filters_in.neighborhood_name:
        append_neighborhood_filters(filters, params, filters_in.neighborhood_name)
    if filters_in.city_name:
        append_city_filters(filters, params, filters_in.city_name)
    if filters_in.min_score is not None:
        filters.append(
            effective_combined_score_expr(filters_in.listing_type) + " >= :min_score"
        )
        params["min_score"] = filters_in.min_score

    available = _LISTING_TYPE_AVAILABLE.get(filters_in.listing_type or "")
    if available:
        filters.append(available)

    if filters_in.property_type:
        type_values = match_values_for_filter(filters_in.property_type)
        placeholders = ", ".join(":pt" + str(i) for i in range(len(type_values)))
        filters.append("LOWER(p.props_json->>'type') IN (" + placeholders + ")")
        for i, value in enumerate(type_values):
            params["pt" + str(i)] = value

    if filters_in.is_furnished is not None:
        filters.append("(p.props_json->>'isFurnished')::boolean = :is_furnished")
        params["is_furnished"] = filters_in.is_furnished

    if filters_in.accepts_pets is not None:
        filters.append(_PETS_MATCH if filters_in.accepts_pets else "NOT " + _PETS_MATCH)

    if filters_in.bbox:
        append_bbox_filter(filters, params, filters_in.bbox)

    return filters, params
