"""Properties query API — used by the GUI property browser."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.auth import verify_api_key_if_configured
from api.property_export import EXPORT_MAX_ROWS, properties_to_csv, properties_to_export_json
from api.property_projection import map_property_detail, map_property_list_item
from api.schemas import (
    NeighborhoodModel,
    PaginatedPropertiesResponse,
    PriceHistoryModel,
    PropertyBatchResponse,
    PropertyDetailModel,
    PropertyExportResponse,
)
from infra.db import SessionLocal
from infra.limiter import limiter
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/properties", tags=["properties"])

_RESP_404 = {404: {"description": "Property not found"}}
_LISTINGS_JSON_AGG = """
    (
        SELECT json_agg(
            json_build_object(
                'platform', pl.platform,
                'platform_listing_id', pl.platform_listing_id,
                'listing_type', pl.listing_type,
                'price', pl.price,
                'currency', pl.currency,
                'url', pl.url,
                'is_furnished', pl.is_furnished,
                'accepts_pets', pl.accepts_pets,
                'condo_fee', pl.condo_fee,
                'iptu', pl.iptu
            )
        )
        FROM property_listings pl
        WHERE pl.property_id = p.id
    ) AS listings
"""


class PropertyListFilters(BaseModel):
    """Query filters for ``GET /properties`` (keeps FastAPI query params under the S107 limit)."""

    page: int = Field(1, ge=1)
    page_size: int = Field(24, ge=1, le=100)
    platform: Optional[str] = None
    min_score: Optional[float] = Field(None, ge=0, le=1)
    max_price: Optional[float] = None
    min_bedrooms: Optional[int] = None
    min_parking: Optional[int] = None
    neighborhood_name: Optional[str] = None
    listing_type: Optional[str] = Field(None, pattern="^(rent|sale|both)$")
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
    min_bedrooms: Optional[int] = None
    min_parking: Optional[int] = None
    neighborhood_name: Optional[str] = None
    listing_type: Optional[str] = Field(None, pattern="^(rent|sale|both)$")
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


def _embed_query_literal(query_text: str) -> str:
    import asyncio

    from adapters.ai.client import create_ai_client
    from adapters.ai.embeddings import vector_literal
    from infra.config import get_config

    cfg = get_config()
    max_chars = cfg.ai.max_description_chars
    embed_input = query_text[:max_chars] if max_chars > 0 else query_text
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
        filters.append("p.price <= :max_price")
        params["max_price"] = filters_in.max_price
    if filters_in.min_bedrooms is not None:
        filters.append("p.bedrooms >= :min_bedrooms")
        params["min_bedrooms"] = filters_in.min_bedrooms
    if filters_in.min_parking is not None:
        filters.append("p.parking >= :min_parking")
        params["min_parking"] = filters_in.min_parking
    if filters_in.neighborhood_name:
        _append_neighborhood_filters(filters, params, filters_in.neighborhood_name)
    if filters_in.min_score is not None:
        filters.append("COALESCE(ms.combined_score, 0) >= :min_score")
        params["min_score"] = filters_in.min_score

    if filters_in.listing_type and filters_in.listing_type != "both":
        listing_type_col = {"rent": "available_for_rent", "sale": "available_for_sale"}
        col = listing_type_col.get(filters_in.listing_type)
        if col:
            filters.append(f"(p.props_json->>{col!r})::boolean = true")

    if filters_in.property_type:
        filters.append("p.props_json->>'type' ILIKE :property_type")
        params["property_type"] = f"%{filters_in.property_type}%"

    if filters_in.is_furnished is not None:
        filters.append("(p.props_json->>'isFurnished')::boolean = :is_furnished")
        params["is_furnished"] = filters_in.is_furnished

    if filters_in.accepts_pets is not None:
        amenity = "p.props_json->'amenities' ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO'"
        filters.append(amenity if filters_in.accepts_pets else f"NOT ({amenity})")

    if filters_in.bbox:
        _append_bbox_filter(filters, params, filters_in.bbox)

    where = " AND ".join(filters)
    if query_vec_literal is not None:
        order = "p.embedding <=> CAST(:q_vec AS vector)"
    else:
        sort_col_map = {
            "combined_score": "COALESCE(ms.combined_score, 0)",
            "price": "p.price",
            "first_seen": "p.first_seen",
            "created_at": "p.first_seen",
            "area_m2": "p.area_m2",
        }
        order = f"{sort_col_map[filters_in.sort_by]} {filters_in.sort_dir.upper()}"
    return where, params, order


_LIST_SELECT_COLUMNS = f"""
                p.id,
                p.platform,
                p.platform_id,
                p.title,
                p.price,
                p.area_m2,
                p.bedrooms,
                p.bathrooms,
                p.address,
                p.image_urls,
                p.first_seen,
                ms.stat_score,
                ms.ai_score,
                ms.combined_score,
                ms.percentile_rank,
                ms.z_score,
                ms.price_per_m2,
                ms.neighborhood_mean,
                ms.meta,
                p.neighborhood_id,
                n.name AS neighborhood_name,
                p.parking,
                p.description,
                p.props_json,
                ST_X(p.location::geometry) AS lon,
                ST_Y(p.location::geometry) AS lat,
                {_LISTINGS_JSON_AGG}
"""


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
        sql = text(f"""
            SELECT {_LIST_SELECT_COLUMNS}
            FROM properties p
            LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE {where}
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
        """)

        count_sql = text(f"""
            SELECT COUNT(*)
            FROM properties p
            LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE {where}
        """)

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


@router.get("/neighborhoods", response_model=List[NeighborhoodModel])
def list_neighborhoods() -> List[Dict[str, Any]]:
    """Return distinct neighborhoods with property counts for dynamic filter options."""
    with SessionLocal() as session:
        rows = session.execute(text("""
            SELECT COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown') AS name,
                   COUNT(p.id) AS property_count
            FROM properties p
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.active = true
            GROUP BY COALESCE(n.name, p.props_json->>'neighborhood', 'Unknown')
            ORDER BY name
        """)).fetchall()
        return [{"name": r[0], "count": r[1]} for r in rows if r[0]]


@router.get("/by-ids", response_model=PropertyBatchResponse)
@limiter.limit("60/minute")
def get_properties_by_ids(
    request: Request,
    ids: Annotated[str, Query(description="Comma-separated property UUIDs (1–4)")],
) -> Dict[str, Any]:
    """Return 1–4 properties by id in request order (AD-12 projection for compare)."""
    raw_ids = [part.strip() for part in ids.split(",") if part.strip()]
    if not raw_ids or len(raw_ids) > 4:
        raise HTTPException(
            status_code=400,
            detail="Provide between 1 and 4 property ids via the ids query parameter",
        )
    # Preserve first-seen order; drop duplicates
    ordered_ids: List[str] = list(dict.fromkeys(raw_ids))
    for pid in ordered_ids:
        try:
            uuid.UUID(pid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid property id: {pid}") from exc

    placeholders = ", ".join(f":id_{i}" for i in range(len(ordered_ids)))
    params = {f"id_{i}": pid for i, pid in enumerate(ordered_ids)}

    with SessionLocal() as session:
        sql = text(f"""
            SELECT {_LIST_SELECT_COLUMNS}
            FROM properties p
            LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.id IN ({placeholders})
        """)
        rows = session.execute(sql, params).mappings().fetchall()
        by_id = {str(row["id"]): map_property_list_item(row) for row in rows}
        return {
            "properties": [by_id[pid] for pid in ordered_ids if pid in by_id],
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
        sql = text(f"""
            SELECT {_LIST_SELECT_COLUMNS}
            FROM properties p
            LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE {where}
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
        """)
        count_sql = text(f"""
            SELECT COUNT(*)
            FROM properties p
            LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE {where}
        """)
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
    """Return a single property with full scoring details."""
    with SessionLocal() as session:
        sql = text(f"""
            SELECT
                p.id, p.platform, p.platform_id, p.title, p.description,
                p.price, p.area_m2, p.bedrooms, p.bathrooms, p.parking,
                p.address, p.image_urls, p.first_seen, p.props_json,
                ms.stat_score, ms.ai_score, ms.combined_score,
                ms.percentile_rank, ms.z_score, ms.price_per_m2,
                ms.neighborhood_mean, ms.neighborhood_median, ms.meta,
                p.neighborhood_id,
                n.name AS neighborhood_name,
                ST_X(p.location::geometry) AS lon, ST_Y(p.location::geometry) AS lat,
                {_LISTINGS_JSON_AGG}
            FROM properties p
            LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.id = :id
        """)
        row = session.execute(sql, {"id": property_id}).mappings().fetchone()
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
    """
    with SessionLocal() as session:
        check = session.execute(
            text("SELECT id FROM properties WHERE id = :id"),
            {"id": property_id},
        ).fetchone()
        if check is None:
            raise HTTPException(status_code=404, detail="Property not found")

        filters = ["property_id = :pid"]
        params: Dict[str, Any] = {"pid": property_id}
        if listing_type:
            filters.append("listing_type = :lt")
            params["lt"] = listing_type
        if platform:
            filters.append("platform = :platform")
            params["platform"] = platform

        where = " AND ".join(filters)
        rows = session.execute(
            text(
                "SELECT id, price, start_ts, end_ts, listing_type, platform, property_listing_id "
                "FROM price_history "
                f"WHERE {where} "
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
