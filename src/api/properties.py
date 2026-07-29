"""Properties query API — used by the GUI property browser."""

from __future__ import annotations

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


def _effective_combined_score_expr(listing_type: Optional[str]) -> str:
    """SQL expression for filter-aware combined score (BIN-83)."""
    if listing_type == "rent":
        return "COALESCE(ms.combined_score_rent, ms.combined_score, 0)"
    if listing_type == "sale":
        return "COALESCE(ms.combined_score_sale, ms.combined_score, 0)"
    return "COALESCE(ms.combined_score, 0)"


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
    sort_by: str = Field("combined_score", pattern="^(combined_score|price|first_seen|created_at|area_m2)$")
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
    sort_by: str = Field("combined_score", pattern="^(combined_score|price|first_seen|created_at|area_m2)$")
    sort_dir: str = Field("desc", pattern="^(asc|desc)$")
    bbox: Optional[str] = None
    q: Optional[str] = Field(None, max_length=500)


def _export_filters_as_list_filters(filters_in: PropertyExportFilters) -> PropertyListFilters:
    """Adapt export filters for ``_build_list_filters`` (pagination overridden by caller)."""
    data = filters_in.model_dump(exclude={"format"})
    return PropertyListFilters(page=1, page_size=1, **data)


# Back-compat aliases (tests / callers that imported private helpers)
_parse_property_ref = parse_property_ref


def _embed_query_literal(query_text: str) -> str:
    import asyncio

    from adapters.ai.client import create_ai_client
    from adapters.ai.embeddings import vector_literal
    from core.semantic_query import normalize_semantic_query
    from infra.config import get_config

    cfg = get_config()
    max_chars = cfg.ai.max_description_chars
    embed_input = normalize_semantic_query(query_text)
    if max_chars > 0:
        embed_input = embed_input[:max_chars]
    client = create_ai_client()

    async def _embed_query():
        async with client:
            return await client.embed(embed_input)

    return vector_literal(asyncio.run(_embed_query()))


def _append_neighborhood_filters(
    filters: list[str],
    params: Dict[str, Any],
    neighborhood_name: str,
) -> None:
    names = [n.strip() for n in neighborhood_name.split(",") if n.strip()]
    if not names:
        return
    nbr_filters = []
    for i, name in enumerate(names):
        nbr_filters.append(f"(n.name ILIKE :nbr_{i} OR p.props_json->>'neighborhood' ILIKE :nbr_{i})")
        params[f"nbr_{i}"] = f"%{name}%"
    filters.append(f"({' OR '.join(nbr_filters)})")


def _append_city_filters(
    filters: list[str],
    params: Dict[str, Any],
    city_name: str,
) -> None:
    names = [n.strip() for n in city_name.split(",") if n.strip()]
    if not names:
        return
    city_filters = []
    for i, name in enumerate(names):
        city_filters.append(
            f"(COALESCE(n.city, p.props_json->>'city') ILIKE :city_{i})"
        )
        params[f"city_{i}"] = f"%{name}%"
    filters.append(f"({' OR '.join(city_filters)})")


def _append_bbox_filter(filters: list[str], params: Dict[str, Any], bbox: str) -> None:
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


def _build_list_filters(filters_in: PropertyListFilters, query_vec_literal: Optional[str]) -> tuple[str, Dict[str, Any], str]:
    filters = ["p.active = true"]
    params: Dict[str, Any] = {
        "limit": filters_in.page_size,
        "offset": (filters_in.page - 1) * filters_in.page_size,
    }

    if query_vec_literal is not None:
        filters.append("p.embedding IS NOT NULL")
        params["q_vec"] = query_vec_literal

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
        filters.append(
            "EXISTS ("
            "SELECT 1 FROM property_listings pl "
            "WHERE pl.property_id = p.id "
            "AND pl.active = true "
            "AND pl.listing_type = :price_type "
            "AND pl.price IS NOT NULL "
            "AND pl.price <= :max_price"
            ")"
        )
        params["max_price"] = filters_in.max_price
        params["price_type"] = price_type
    if filters_in.min_bedrooms is not None:
        filters.append("p.bedrooms >= :min_bedrooms")
        params["min_bedrooms"] = filters_in.min_bedrooms
    if filters_in.min_parking is not None:
        filters.append("p.parking >= :min_parking")
        params["min_parking"] = filters_in.min_parking
    if filters_in.neighborhood_name:
        _append_neighborhood_filters(filters, params, filters_in.neighborhood_name)
    if filters_in.city_name:
        _append_city_filters(filters, params, filters_in.city_name)
    if filters_in.min_score is not None:
        score_expr = _effective_combined_score_expr(filters_in.listing_type)
        filters.append(f"{score_expr} >= :min_score")
        params["min_score"] = filters_in.min_score

    if filters_in.listing_type and filters_in.listing_type != "both":
        listing_type_col = {"rent": "available_for_rent", "sale": "available_for_sale"}
        col = listing_type_col.get(filters_in.listing_type)
        if col:
            filters.append(f"(p.props_json->>{col!r})::boolean = true")

    if filters_in.property_type:
        from core.property_type import match_values_for_filter

        type_values = match_values_for_filter(filters_in.property_type)
        placeholders = ", ".join(f":pt{i}" for i in range(len(type_values)))
        filters.append(f"LOWER(p.props_json->>'type') IN ({placeholders})")
        for i, value in enumerate(type_values):
            params[f"pt{i}"] = value

    if filters_in.is_furnished is not None:
        filters.append("(p.props_json->>'isFurnished')::boolean = :is_furnished")
        params["is_furnished"] = filters_in.is_furnished

    if filters_in.accepts_pets is not None:
        # Prefer listing.accepts_pets (OLX + QuintoAndar); keep QA amenity for legacy rows.
        pets_match = (
            "("
            "EXISTS ("
            "SELECT 1 FROM property_listings pl "
            "WHERE pl.property_id = p.id "
            "AND pl.active = true "
            "AND pl.accepts_pets IS TRUE"
            ") "
            "OR p.props_json->'amenities' ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO'"
            ")"
        )
        filters.append(pets_match if filters_in.accepts_pets else f"NOT {pets_match}")

    if filters_in.bbox:
        _append_bbox_filter(filters, params, filters_in.bbox)

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
            "first_seen": "p.first_seen",
            "created_at": "p.first_seen",
            "area_m2": "p.area_m2",
        }
        order = f"{sort_col_map[filters_in.sort_by]} {filters_in.sort_dir.upper()}"
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
        # where/order are built by _build_list_filters from an allow-listed
        # column/enum map (sort_col_map, _effective_combined_score_expr) plus
        # bind params for user values — never raw user text. Assembled here via
        # plain concatenation (not an f-string) per BIN-135.
        sql = text(
            "SELECT " + _LIST_SELECT_COLUMNS + " "
            "FROM properties p "
            "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
            "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
            "WHERE " + where + " "
            "ORDER BY " + order + " "
            "LIMIT :limit OFFSET :offset"
        )

        count_sql = text(
            "SELECT COUNT(*) "
            "FROM properties p "
            "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
            "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
            "WHERE " + where
        )

        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = session.execute(count_sql, count_params).scalar() or 0
        rows = session.execute(sql, params).mappings().fetchall()
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
            "FROM properties p "
            "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
            "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
            "WHERE " + column + " IN (" + placeholders + ")"
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
        # Same allow-listed where/order as list_properties — plain
        # concatenation (not an f-string) per BIN-135.
        sql = text(
            "SELECT " + _LIST_SELECT_COLUMNS + " "
            "FROM properties p "
            "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
            "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
            "WHERE " + where + " "
            "ORDER BY " + order + " "
            "LIMIT :limit OFFSET :offset"
        )
        count_sql = text(
            "SELECT COUNT(*) "
            "FROM properties p "
            "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
            "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
            "WHERE " + where
        )
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = session.execute(count_sql, count_params).scalar() or 0
        rows = session.execute(sql, params).mappings().fetchall()
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
            + " FROM properties p "
            "LEFT JOIN metrics_scoring ms ON ms.property_id = p.id "
            "LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id "
            "WHERE " + where
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
) -> List[Dict[str, Any]]:
    """Return ordered price-history intervals for a property.

    Optionally filter by listing_type (rent/sale) and/or platform.
    ``property_id`` may be sequential ``public_id`` or UUID.
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
