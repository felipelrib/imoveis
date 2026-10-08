"""Properties query API — used by the GUI property browser."""

from __future__ import annotations

import threading
from typing import Annotated, Any, Dict, List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import text
from sqlalchemy.exc import DataError, StatementError

from api.auth import verify_api_key_if_configured
from api.property_export import EXPORT_MAX_ROWS, properties_to_csv, properties_to_export_json
from api.property_refs import parse_property_ref
from api.schemas import (
    CityModel,
    NeighborhoodModel,
    PaginatedPropertiesResponse,
    PriceHistoryModel,
    PropertyBatchResponse,
    PropertyDetailModel,
    PropertyExportResponse,
)
from core.listing_type import normalize_listing_type, normalize_price_type
from core.neighbourhood_quality import quality_profile_fields
from core.property_list_filters import (
    ACTIVE_RENT_LISTING_WITH_TOTAL,
    PRICE_PERCENTILE_CAP_BY_LISTING_TYPE,
    PRICE_PERCENTILE_CAP_EITHER,
    PRICE_PERCENTILE_CAP_RENT,
    PRICE_PERCENTILE_CAP_SALE,
    TOTAL_MONTHLY_COST_CAP,
    TOTAL_MONTHLY_COST_INCOMPLETE,
    append_bbox_filter,
    append_city_filters,
    append_neighborhood_filters,
    build_property_where,
    effective_combined_score_expr,
)
from core.property_projection import (
    LIST_SELECT_COLUMNS,
    LISTINGS_JSON_AGG,
    map_property_detail,
    map_property_list_item,
)
from infra.db import SessionLocal
from infra.limiter import limiter
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/properties", tags=["properties"])

_RESP_404 = {404: {"description": "Property not found"}}
# Back-compat aliases for in-module f-strings / detail query
_LISTINGS_JSON_AGG = LISTINGS_JSON_AGG
_LIST_SELECT_COLUMNS = LIST_SELECT_COLUMNS
# Shared FROM/JOIN clause for every properties/metrics_scoring/neighborhoods
# query below (BIN-135) — a single source avoids Sonar duplicated-lines flags
# on the near-identical concatenated SQL across list/get/export helpers.
_PROPERTIES_FROM_JOIN = (
    "FROM properties p "
    "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
    "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
)


def _query_paginated_properties(
    session: Any, where: str, order: str, params: Dict[str, Any]
) -> tuple[int, Any]:
    """Shared paginated-list + count query used by list/export (BIN-135).

    ``where``/``order`` are allow-listed column/enum expressions built by
    ``_build_list_filters`` (never raw user text); ``params`` supplies the
    bound values, including ``limit``/``offset``.
    """
    sql = text(
        "SELECT " + _LIST_SELECT_COLUMNS + " "
        + _PROPERTIES_FROM_JOIN
        + "WHERE " + where + " "
        "ORDER BY " + order + " "
        "LIMIT :limit OFFSET :offset"
    )
    count_sql = text("SELECT COUNT(*) " + _PROPERTIES_FROM_JOIN + "WHERE " + where)
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    total = session.execute(count_sql, count_params).scalar() or 0
    rows = session.execute(sql, params).mappings().fetchall()
    return total, rows


def _coerce_listing_type(value: Any) -> Any:
    """Normalize PT listing_type aliases to EN before pattern validation."""
    if value is None or not isinstance(value, str):
        return value
    canonical = normalize_listing_type(value)
    return canonical if canonical is not None else value


def _coerce_price_type(value: Any) -> Any:
    """Normalize PT price_type aliases to EN before pattern validation."""
    if value is None or not isinstance(value, str):
        return value
    canonical = normalize_price_type(value)
    return canonical if canonical is not None else value


ListingTypeParam = Annotated[Optional[str], BeforeValidator(_coerce_listing_type)]
PriceTypeParam = Annotated[Optional[str], BeforeValidator(_coerce_price_type)]


def _effective_sort_price_type(
    price_type: Optional[str],
    listing_type: Optional[str],
) -> Optional[str]:
    """Resolve rent/sale for sort-by-price (BIN-106).

    Explicit ``price_type`` wins; else inherit ``listing_type`` when rent/sale.
    Unlike max_price, omitted type does **not** default to rent — callers keep
    decisioning ``p.price`` for ``both`` / no type filter.
    """
    if price_type in ("rent", "sale"):
        return price_type
    if listing_type in ("rent", "sale"):
        return listing_type
    return None


def _sort_price_expr(filters_in: "PropertyListFilters") -> tuple[str, Optional[str]]:
    """SQL ORDER BY expression for price + optional ``:sort_price_type`` bind."""
    sort_type = _effective_sort_price_type(filters_in.price_type, filters_in.listing_type)
    if sort_type is None:
        return "p.price", None
    expr = (
        "COALESCE("
        "(SELECT MIN(pl.price) FROM property_listings pl "
        "WHERE pl.property_id = p.id AND pl.active = true "
        "AND pl.listing_type = :sort_price_type AND pl.price IS NOT NULL), "
        "p.price)"
    )
    return expr, sort_type


# The membership predicates (cost cap, percentile cap, places, bbox ...) live
# in ``core.property_list_filters`` since v0.14-s1.9: the saved-search matcher
# builds the same ``WHERE``. The private names below stay importable from this
# module (unit tests and in-module callers use them).
_effective_combined_score_expr = effective_combined_score_expr
_ACTIVE_RENT_LISTING_WITH_TOTAL = ACTIVE_RENT_LISTING_WITH_TOTAL
_TOTAL_MONTHLY_COST_CAP = TOTAL_MONTHLY_COST_CAP
_TOTAL_MONTHLY_COST_INCOMPLETE = TOTAL_MONTHLY_COST_INCOMPLETE
_PRICE_PERCENTILE_CAP_RENT = PRICE_PERCENTILE_CAP_RENT
_PRICE_PERCENTILE_CAP_SALE = PRICE_PERCENTILE_CAP_SALE
_PRICE_PERCENTILE_CAP_BY_LISTING_TYPE = PRICE_PERCENTILE_CAP_BY_LISTING_TYPE
_PRICE_PERCENTILE_CAP_EITHER = PRICE_PERCENTILE_CAP_EITHER
_append_neighborhood_filters = append_neighborhood_filters
_append_city_filters = append_city_filters
_append_bbox_filter = append_bbox_filter

# Lowest persisted total among the Property's active rent Listings; NULL when
# none has one (ordered last in both directions by the caller). Same predicate
# as the cap (v0.14-s1.2), so the order and ``deciding_listing_id`` agree.
_SORT_TOTAL_MONTHLY_COST_EXPR = (
    "(SELECT MIN(pl.total_monthly_cost) " + _ACTIVE_RENT_LISTING_WITH_TOTAL + ")"
)


class PropertyListFilters(BaseModel):
    """Query filters for ``GET /properties`` (keeps FastAPI query params under the S107 limit)."""

    page: int = Field(1, ge=1)
    page_size: int = Field(24, ge=1, le=100)
    platform: Optional[str] = None
    min_score: Optional[float] = Field(None, ge=0, le=1)
    max_price: Optional[float] = None
    price_type: PriceTypeParam = Field(None, pattern="^(rent|sale)$")
    min_bedrooms: Optional[int] = None
    min_parking: Optional[int] = None
    neighborhood_name: Optional[str] = None
    city_name: Optional[str] = None
    listing_type: ListingTypeParam = Field(None, pattern="^(rent|sale|both)$")
    property_type: Optional[str] = None
    is_furnished: Optional[bool] = None
    accepts_pets: Optional[bool] = None
    # Total Monthly Cost cap (v0.14-s1.2): reads ``total_monthly_cost`` only.
    max_total_monthly_cost: Optional[float] = Field(None, ge=0)
    include_incomplete_totals: bool = False
    # Cohort price/m2 percentile cap (v0.14-s1.7): 0.25 = "among the 25% cheapest".
    max_price_per_m2_percentile: Optional[float] = Field(None, gt=0, le=1)
    sort_by: str = Field(
        "combined_score",
        pattern="^(combined_score|price|total_monthly_cost|first_seen|created_at|area_m2)$",
    )
    sort_dir: str = Field("desc", pattern="^(asc|desc)$")
    bbox: Optional[str] = None
    q: Optional[str] = Field(None, max_length=500)


class PropertyExportFilters(BaseModel):
    """Same filter surface as the Properties list, without pagination (BIN-50)."""

    format: str = Field("json", pattern="^(csv|json)$")
    platform: Optional[str] = None
    min_score: Optional[float] = Field(None, ge=0, le=1)
    max_price: Optional[float] = None
    price_type: PriceTypeParam = Field(None, pattern="^(rent|sale)$")
    min_bedrooms: Optional[int] = None
    min_parking: Optional[int] = None
    neighborhood_name: Optional[str] = None
    city_name: Optional[str] = None
    listing_type: ListingTypeParam = Field(None, pattern="^(rent|sale|both)$")
    property_type: Optional[str] = None
    is_furnished: Optional[bool] = None
    accepts_pets: Optional[bool] = None
    # Total Monthly Cost cap (v0.14-s1.2): reads ``total_monthly_cost`` only.
    max_total_monthly_cost: Optional[float] = Field(None, ge=0)
    include_incomplete_totals: bool = False
    # Cohort price/m2 percentile cap (v0.14-s1.7): 0.25 = "among the 25% cheapest".
    max_price_per_m2_percentile: Optional[float] = Field(None, gt=0, le=1)
    sort_by: str = Field(
        "combined_score",
        pattern="^(combined_score|price|total_monthly_cost|first_seen|created_at|area_m2)$",
    )
    sort_dir: str = Field("desc", pattern="^(asc|desc)$")
    bbox: Optional[str] = None
    q: Optional[str] = Field(None, max_length=500)


def _export_filters_as_list_filters(filters_in: PropertyExportFilters) -> PropertyListFilters:
    """Adapt export filters for ``_build_list_filters`` (pagination overridden by caller)."""
    data = filters_in.model_dump(exclude={"format"})
    return PropertyListFilters(page=1, page_size=1, **data)


# Back-compat aliases (tests / callers that imported private helpers)
_parse_property_ref = parse_property_ref


# Per-thread AI client cache for semantic-search embeddings (BIN-143).
#
# FastAPI runs sync route handlers in a bounded worker threadpool. aiohttp's
# ClientSession (used by LocalAIClient subclasses) is bound to the event loop that
# created it, so a single process-wide client/session cannot safely be shared across
# worker threads each running their own event loop. Instead we cache one client per
# worker thread — keyed by thread id in a plain dict (not ``threading.local()``) so
# tests can clear the whole cache from any thread via ``_reset_embedding_clients``.
# This still avoids the previous per-*request* cost of constructing a fresh client
# and event loop (and re-opening a fresh TCP connection to Ollama/LM Studio) on
# every semantic-search call.
_embedding_clients: Dict[int, Any] = {}
_embedding_clients_lock = threading.Lock()


def _get_embedding_client() -> Any:
    """Return this worker thread's cached AI client, creating it on first use.

    Routes through the EMBEDDING task class so the query-side embedding backend
    matches the write side (``tasks.embed_property``, v0.13-s1.2). Using the
    bare scalar here would let ``enrichment_routing.embedding`` diverge from the
    stored vectors' backend and silently corrupt semantic-search similarity.
    """
    from adapters.ai.client import create_ai_client
    from core.enrichment import EnrichmentTaskClass

    thread_id = threading.get_ident()
    client = _embedding_clients.get(thread_id)
    if client is None:
        client = create_ai_client(task_class=EnrichmentTaskClass.EMBEDDING)
        with _embedding_clients_lock:
            _embedding_clients[thread_id] = client
    return client


def _reset_embedding_clients() -> None:
    """Test-only hook: clear all cached per-thread embedding clients."""
    with _embedding_clients_lock:
        _embedding_clients.clear()


def _embed_query_literal(query_text: str) -> str:
    from adapters.ai.embeddings import vector_literal
    from adapters.queue.async_bridge import run_coro
    from core.semantic_query import normalize_semantic_query
    from infra.config import get_config

    cfg = get_config()
    max_chars = cfg.ai.max_description_chars
    embed_input = normalize_semantic_query(query_text)
    if max_chars > 0:
        embed_input = embed_input[:max_chars]

    client = _get_embedding_client()
    embedding = run_coro(client.embed(embed_input))
    return vector_literal(embedding)


def _build_list_filters(filters_in: PropertyListFilters, query_vec_literal: Optional[str]) -> tuple[str, Dict[str, Any], str]:
    filters, where_params = build_property_where(
        filters_in, require_embedding=query_vec_literal is not None
    )
    params: Dict[str, Any] = {
        "limit": filters_in.page_size,
        "offset": (filters_in.page - 1) * filters_in.page_size,
    }
    if query_vec_literal is not None:
        params["q_vec"] = query_vec_literal
    params.update(where_params)

    where = " AND ".join(filters)
    if query_vec_literal is not None:
        order = "p.embedding <=> CAST(:q_vec AS vector)"
    else:
        score_expr = _effective_combined_score_expr(filters_in.listing_type)
        price_expr, sort_price_type = _sort_price_expr(filters_in)
        if sort_price_type is not None and filters_in.sort_by == "price":
            params["sort_price_type"] = sort_price_type
        sort_col_map = {
            "combined_score": score_expr,
            "price": price_expr,
            "total_monthly_cost": _SORT_TOTAL_MONTHLY_COST_EXPR,
            "first_seen": "p.first_seen",
            "created_at": "p.first_seen",
            "area_m2": "p.area_m2",
        }
        order = f"{sort_col_map[filters_in.sort_by]} {filters_in.sort_dir.upper()}"
        if filters_in.sort_by == "total_monthly_cost":
            # Properties without a total sort last in both directions (Postgres
            # would put NULLs first on DESC). ``p.id`` breaks ties - every
            # Property without a total ties - so LIMIT/OFFSET pages are stable.
            order += " NULLS LAST, p.id"
    return where, params, order


@router.get("", response_model=PaginatedPropertiesResponse)
@limiter.limit("60/minute")
def list_properties(
    request: Request,
    filters_in: Annotated[PropertyListFilters, Query()],
) -> Dict[str, Any]:
    """Return paginated, filtered, scored properties for the GUI grid.

    When ``q`` is provided, results are ordered by cosine distance to the
    query embedding (semantic search) and only rows with embeddings are returned.
    """
    query_text = (filters_in.q or "").strip()
    query_vec_literal = _embed_query_literal(query_text) if query_text else None
    where, params, order = _build_list_filters(filters_in, query_vec_literal)

    with SessionLocal() as session:
        total, rows = _query_paginated_properties(session, where, order, params)
        page_size = filters_in.page_size
        return {
            "total": total,
            "page": filters_in.page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
            "properties": [map_property_list_item(row) for row in rows],
        }


def _neighborhood_row_dict(row: Any) -> Dict[str, Any]:
    """Map a neighbourhood list/detail SQL row to the NeighborhoodModel payload."""
    # Row layout: name, count, city, id, amenity, transit, access, safety,
    # risk_flags, quality_meta, quality_notes
    profile = quality_profile_fields(
        {
            "id": row[3],
            "amenity_score": row[4],
            "transit_score": row[5],
            "access_score": row[6],
            "safety_score": row[7],
            "risk_flags": row[8],
            "quality_meta": row[9],
            "quality_notes": row[10],
        }
    )
    return {
        "name": row[0],
        "count": int(row[1] or 0),
        "city": row[2],
        **profile,
    }


@router.get("/neighborhoods", response_model=List[NeighborhoodModel])
def list_neighborhoods() -> List[Dict[str, Any]]:
    """Return distinct neighborhoods with property counts + optional quality profile."""
    with SessionLocal() as session:
        rows = session.execute(text("""
            SELECT COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown') AS name,
                   COUNT(p.id) AS property_count,
                   COALESCE(n.city, p.props_json->>'city') AS city,
                   (array_agg(n.id) FILTER (WHERE n.id IS NOT NULL))[1] AS id,
                   MAX(n.amenity_score) AS amenity_score,
                   MAX(n.transit_score) AS transit_score,
                   MAX(n.access_score) AS access_score,
                   MAX(n.safety_score) AS safety_score,
                   (array_agg(n.risk_flags) FILTER (WHERE n.id IS NOT NULL))[1] AS risk_flags,
                   (array_agg(n.quality_meta) FILTER (WHERE n.id IS NOT NULL))[1] AS quality_meta,
                   (array_agg(n.quality_notes) FILTER (WHERE n.id IS NOT NULL))[1] AS quality_notes
            FROM properties p
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.active = true
            GROUP BY COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown'),
                     COALESCE(n.city, p.props_json->>'city')
            ORDER BY city NULLS LAST, name
        """)).fetchall()
        return [_neighborhood_row_dict(r) for r in rows if r[0]]


@router.get(
    "/neighborhoods/{neighborhood_id}",
    response_model=NeighborhoodModel,
    responses=_RESP_404,
)
def get_neighborhood(neighborhood_id: str) -> Dict[str, Any]:
    """Return one neighbourhood row with quality profile and active property count."""
    try:
        UUID(str(neighborhood_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Neighborhood not found") from exc

    with SessionLocal() as session:
        try:
            row = session.execute(
                text("""
                    SELECT n.name,
                           COUNT(p.id) FILTER (WHERE p.active = true) AS property_count,
                           n.city,
                           n.id,
                           n.amenity_score,
                           n.transit_score,
                           n.access_score,
                           n.safety_score,
                           n.risk_flags,
                           n.quality_meta,
                           n.quality_notes
                    FROM neighborhoods n
                    LEFT JOIN properties p ON p.neighborhood_id = n.id
                    WHERE n.id = CAST(:nid AS uuid)
                    GROUP BY n.id, n.name, n.city, n.amenity_score, n.transit_score,
                             n.access_score, n.safety_score, n.risk_flags,
                             n.quality_meta, n.quality_notes
                """),
                {"nid": neighborhood_id},
            ).fetchone()
        except (DataError, StatementError) as exc:
            raise HTTPException(status_code=404, detail="Neighborhood not found") from exc
        if row is None:
            raise HTTPException(status_code=404, detail="Neighborhood not found")
        return _neighborhood_row_dict(row)


@router.get("/cities", response_model=List[CityModel])
def list_cities() -> List[Dict[str, Any]]:
    """Return distinct cities with property counts for the city filter."""
    with SessionLocal() as session:
        rows = session.execute(text("""
            SELECT COALESCE(n.city, p.props_json->>'city', 'Unknown') AS name,
                   COUNT(p.id) AS property_count
            FROM properties p
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.active = true
            GROUP BY COALESCE(n.city, p.props_json->>'city', 'Unknown')
            ORDER BY name
        """)).fetchall()
        return [{"name": r[0], "count": r[1]} for r in rows if r[0]]


@router.get("/by-ids", response_model=PropertyBatchResponse)
@limiter.limit("60/minute")
def get_properties_by_ids(
    request: Request,
    ids: Annotated[
        str,
        Query(
            description=(
                "Comma-separated property refs (1–4): sequential public_id "
                "and/or UUID primary keys"
            ),
        ),
    ],
) -> Dict[str, Any]:
    """Return 1–4 properties by public_id or UUID in request order (AD-12 projection)."""
    raw_ids = [part.strip() for part in ids.split(",") if part.strip()]
    if not raw_ids or len(raw_ids) > 4:
        raise HTTPException(
            status_code=400,
            detail="Provide between 1 and 4 property ids via the ids query parameter",
        )
    # Preserve first-seen order; drop duplicates
    ordered_refs: List[str] = list(dict.fromkeys(raw_ids))
    parsed = [_parse_property_ref(ref) for ref in ordered_refs]
    key_kinds = {kind for kind, _ in parsed}
    if len(key_kinds) > 1:
        raise HTTPException(
            status_code=400,
            detail="Mix of public_id and UUID is not supported in one by-ids request",
        )
    key_kind = next(iter(key_kinds))
    values = [value for _, value in parsed]
    placeholders = ", ".join(f":id_{i}" for i in range(len(values)))
    params = {f"id_{i}": value for i, value in enumerate(values)}
    column = "p.public_id" if key_kind == "public_id" else "p.id"

    with SessionLocal() as session:
        # column is a hardcoded literal ("p.public_id" or "p.id") chosen above,
        # never user-supplied text. Plain concatenation per BIN-135.
        sql = text(
            "SELECT " + _LIST_SELECT_COLUMNS + " "
            + _PROPERTIES_FROM_JOIN
            + "WHERE " + column + " IN (" + placeholders + ")"
        )
        rows = session.execute(sql, params).mappings().fetchall()
        if key_kind == "public_id":
            by_key = {int(row["public_id"]): map_property_list_item(row) for row in rows}
            return {
                "properties": [by_key[pid] for pid in values if pid in by_key],
            }
        by_key = {str(row["id"]): map_property_list_item(row) for row in rows}
        return {
            "properties": [by_key[pid] for pid in values if pid in by_key],
        }


@router.get(
    "/export",
    response_model=None,
    responses={
        200: {
            "description": "Filtered property export (JSON or CSV)",
            "content": {
                "application/json": {"schema": PropertyExportResponse.model_json_schema()},
                "text/csv": {"schema": {"type": "string"}},
            },
        },
    },
    dependencies=[Depends(verify_api_key_if_configured)],
)
@limiter.limit("60/minute")
def export_properties(
    request: Request,
    filters_in: Annotated[PropertyExportFilters, Query()],
) -> Union[Dict[str, Any], Response]:
    """Export the filtered property set as CSV or JSON (AD-12 projection, AD-8).

    Uses the same filters as ``GET /properties``. Caps at ``EXPORT_MAX_ROWS``;
    JSON reports ``truncated`` when more rows match. Auth follows Epic 2 edge
    rules when ``auth.api_key`` is configured.
    """
    query_text = (filters_in.q or "").strip()
    query_vec_literal = _embed_query_literal(query_text) if query_text else None
    list_filters = _export_filters_as_list_filters(filters_in)
    where, params, order = _build_list_filters(list_filters, query_vec_literal)
    params["limit"] = EXPORT_MAX_ROWS
    params["offset"] = 0

    with SessionLocal() as session:
        total, rows = _query_paginated_properties(session, where, order, params)
        items = [map_property_list_item(row) for row in rows]

    if filters_in.format == "csv":
        body = properties_to_csv(items)
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="properties-export.csv"',
                "X-Export-Total": str(total),
                "X-Export-Truncated": "true" if total > len(items) else "false",
            },
        )

    return properties_to_export_json(items, total)


@router.get("/{property_id}", response_model=PropertyDetailModel, responses=_RESP_404)
def get_property(property_id: str) -> Dict[str, Any]:
    """Return a single property with full scoring details.

    ``property_id`` may be the sequential ``public_id`` (digits) or the UUID PK.
    """
    key_kind, key_value = _parse_property_ref(property_id)
    where = "p.public_id = :id" if key_kind == "public_id" else "p.id = :id"
    with SessionLocal() as session:
        # where is one of two hardcoded literals chosen above by key_kind,
        # never user-supplied text. Plain concatenation per BIN-135.
        sql = text(
            "SELECT "
            "p.id, p.public_id, p.platform, p.platform_id, p.title, p.description, "
            "p.price, p.area_m2, p.bedrooms, p.bathrooms, p.parking, "
            "p.address, p.image_urls, p.first_seen, p.props_json, "
            "ms.stat_score, ms.ai_score, ms.combined_score, "
            "ms.percentile_rank, ms.z_score, ms.price_per_m2, "
            "ms.neighborhood_mean, ms.neighborhood_median, "
            "ms.price_per_m2_rent, ms.price_per_m2_sale, "
            "ms.neighborhood_mean_rent, ms.neighborhood_mean_sale, "
            "ms.neighborhood_median_rent, ms.neighborhood_median_sale, "
            "ms.stat_score_rent, ms.stat_score_sale, "
            "ms.z_score_rent, ms.z_score_sale, "
            "ms.percentile_rank_rent, ms.percentile_rank_sale, "
            "ms.combined_score_rent, ms.combined_score_sale, "
            "ms.price_per_m2_percentile_rent, ms.price_per_m2_percentile_sale, "
            "ms.meta, "
            "p.neighborhood_id, "
            "n.name AS neighborhood_name, "
            "COALESCE(n.city, p.props_json->>'city') AS city, "
            "n.amenity_score, "
            "n.transit_score, "
            "n.access_score, "
            "n.safety_score, "
            "n.risk_flags, "
            "n.quality_meta, "
            "n.quality_notes, "
            "ST_X(p.location::geometry) AS lon, ST_Y(p.location::geometry) AS lat, "
            + _LISTINGS_JSON_AGG
            + " "
            + _PROPERTIES_FROM_JOIN
            + "WHERE " + where
        )
        row = session.execute(sql, {"id": key_value}).mappings().fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Property not found")
        return map_property_detail(row)


@router.get(
    "/{property_id}/price-history",
    response_model=List[PriceHistoryModel],
    responses=_RESP_404,
)
def get_price_history(
    property_id: str,
    listing_type: Annotated[Optional[str], Query(pattern="^(rent|sale)$")] = None,
    platform: Optional[str] = None,
    property_listing_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return ordered price-history intervals for a property.

    Optionally filter by listing_type (rent/sale), platform, and/or
    property_listing_id. ``property_id`` may be sequential ``public_id`` or
    UUID.

    Note: a property can have multiple distinct listings (ads) sharing the
    same platform + listing_type (two brokers re-listing the same unit, or a
    relisted ad under a new platform id) — see BIN-145. Without a
    property_listing_id filter, this endpoint returns the merged history of
    every listing under the given property/listing_type/platform scope,
    which can look like a single corrupted timeline when in fact it is
    multiple listings' independent intervals interleaved. Callers that need
    one listing's own timeline should pass property_listing_id explicitly.
    """
    key_kind, key_value = _parse_property_ref(property_id)
    with SessionLocal() as session:
        if key_kind == "public_id":
            check = session.execute(
                text("SELECT id FROM properties WHERE public_id = :id"),
                {"id": key_value},
            ).fetchone()
        else:
            check = session.execute(
                text("SELECT id FROM properties WHERE id = :id"),
                {"id": key_value},
            ).fetchone()
        if check is None:
            raise HTTPException(status_code=404, detail="Property not found")
        resolved_uuid = str(check[0])

        filters = ["property_id = :pid"]
        params: Dict[str, Any] = {"pid": resolved_uuid}
        if listing_type:
            filters.append("listing_type = :lt")
            params["lt"] = listing_type
        if platform:
            filters.append("platform = :platform")
            params["platform"] = platform
        if property_listing_id:
            filters.append("property_listing_id = :plid")
            params["plid"] = property_listing_id

        where = " AND ".join(filters)
        # filters entries are hardcoded literals ("property_id = :pid", etc.)
        # with bound values — never raw user text. Plain concatenation
        # (not an f-string) per BIN-135.
        rows = session.execute(
            text(
                "SELECT id, price, start_ts, end_ts, listing_type, platform, property_listing_id "
                "FROM price_history "
                "WHERE " + where + " "
                "ORDER BY start_ts DESC"
            ),
            params,
        ).fetchall()

        return [
            {
                "id": str(r[0]),
                "price": float(r[1]),
                "start_ts": r[2].isoformat() if r[2] else None,
                "end_ts": r[3].isoformat() if r[3] else None,
                "listing_type": r[4],
                "platform": r[5],
                "property_listing_id": str(r[6]) if r[6] else None,
            }
            for r in rows
        ]
