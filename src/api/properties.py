"""Properties query API — used by the GUI property browser."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from sqlalchemy import text

from api.schemas import NeighborhoodModel, PaginatedPropertiesResponse, PriceHistoryModel, PropertyDetailModel
from infra.db import SessionLocal
from infra.limiter import limiter
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/properties", tags=["properties"])


@router.get("", response_model=PaginatedPropertiesResponse)
@limiter.limit("60/minute")
def list_properties(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    platform: Optional[str] = None,
    min_score: Optional[float] = Query(None, ge=0, le=1),
    max_price: Optional[float] = None,
    min_bedrooms: Optional[int] = None,
    min_parking: Optional[int] = None,
    neighborhood_name: Optional[str] = None,
    listing_type: Optional[str] = Query(None, pattern="^(rent|sale|both)$"),
    property_type: Optional[str] = None,
    is_furnished: Optional[bool] = None,
    accepts_pets: Optional[bool] = None,
    sort_by: str = Query("combined_score", pattern="^(combined_score|price|first_seen|created_at|area_m2)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    bbox: Optional[str] = None,
    q: Optional[str] = Query(None, max_length=500),
) -> Dict[str, Any]:
    """Return paginated, filtered, scored properties for the GUI grid.

    When ``q`` is provided, results are ordered by cosine distance to the
    query embedding (semantic search) and only rows with embeddings are returned.
    """
    import asyncio

    from adapters.ai.client import create_ai_client
    from adapters.ai.embeddings import vector_literal
    from infra.config import get_config

    query_text = (q or "").strip()
    query_vec_literal: Optional[str] = None
    if query_text:
        cfg = get_config()
        max_chars = cfg.ai.max_description_chars
        embed_input = query_text[:max_chars] if max_chars > 0 else query_text
        client = create_ai_client()

        async def _embed_query():
            async with client:
                return await client.embed(embed_input)

        query_embedding = asyncio.run(_embed_query())
        query_vec_literal = vector_literal(query_embedding)

    with SessionLocal() as session:
        filters = ["p.active = true"]
        params: Dict[str, Any] = {
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }

        if query_vec_literal is not None:
            filters.append("p.embedding IS NOT NULL")
            params["q_vec"] = query_vec_literal

        if platform:
            filters.append("p.platform = :platform")
            params["platform"] = platform
        if max_price is not None:
            filters.append("p.price <= :max_price")
            params["max_price"] = max_price
        if min_bedrooms is not None:
            filters.append("p.bedrooms >= :min_bedrooms")
            params["min_bedrooms"] = min_bedrooms
        if min_parking is not None:
            filters.append("p.parking >= :min_parking")
            params["min_parking"] = min_parking
        if neighborhood_name:
            names = [n.strip() for n in neighborhood_name.split(",")]
            nbr_filters = []
            for i, name in enumerate(names):
                nbr_filters.append(f"(n.name ILIKE :nbr_{i} OR p.props_json->>'neighborhood' ILIKE :nbr_{i})")
                params[f"nbr_{i}"] = f"%{name}%"
            filters.append(f"({' OR '.join(nbr_filters)})")
        if min_score is not None:
            filters.append("COALESCE(ms.combined_score, 0) >= :min_score")
            params["min_score"] = min_score

        if listing_type and listing_type != "both":
            LISTING_TYPE_COL = {
                "rent": "available_for_rent",
                "sale": "available_for_sale"
            }
            if listing_type in LISTING_TYPE_COL:
                col = LISTING_TYPE_COL[listing_type]
                filters.append(f"(p.props_json->>{col!r})::boolean = true")

        if property_type:
            filters.append("p.props_json->>'type' ILIKE :property_type")
            params["property_type"] = f"%{property_type}%"

        if is_furnished is not None:
            filters.append("(p.props_json->>'isFurnished')::boolean = :is_furnished")
            params["is_furnished"] = is_furnished

        if accepts_pets is not None:
            if accepts_pets:
                filters.append("p.props_json->'amenities' ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO'")
            else:
                filters.append("NOT (p.props_json->'amenities' ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO')")

        if bbox:
            try:
                parts = [float(x.strip()) for x in bbox.split(",")]
                if len(parts) == 4:
                    min_lon, min_lat, max_lon, max_lat = parts
                    filters.append(
                        "ST_Within(p.location, ST_MakeEnvelope("
                        ":bbox_min_lon, :bbox_min_lat, :bbox_max_lon, :bbox_max_lat, 4326)) = true"
                    )
                    params["bbox_min_lon"] = min_lon
                    params["bbox_min_lat"] = min_lat
                    params["bbox_max_lon"] = max_lon
                    params["bbox_max_lat"] = max_lat
            except (ValueError, IndexError):
                pass  # ignore malformed bbox

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
            order = f"{sort_col_map[sort_by]} {sort_dir.upper()}"

        sql = text(f"""
            SELECT
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
                n.name AS neighborhood_name,
                p.parking,
                p.description,
                p.props_json,
                ST_X(p.location::geometry) AS lon,
                ST_Y(p.location::geometry) AS lat,
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

        # Remove pagination params for count
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}

        total = session.execute(count_sql, count_params).scalar() or 0
        rows = session.execute(sql, params).mappings().fetchall()

        properties = []
        for row in rows:
            meta = row["meta"] or {}
            visual = meta.get("visual", {})
            sentiment = meta.get("sentiment", {})
            props_json = row["props_json"] or {}

            neighborhood_name_val = row["neighborhood_name"] or props_json.get("neighborhood")

            properties.append(
                {
                    "id": str(row["id"]),
                    "platform": row["platform"],
                    "platform_id": row["platform_id"],
                    "title": row["title"],
                    "price": row["price"],
                    "area_m2": row["area_m2"],
                    "bedrooms": row["bedrooms"],
                    "bathrooms": row["bathrooms"],
                    "address": row["address"],
                    "image_urls": row["image_urls"] or [],
                    "created_at": row["first_seen"].isoformat() if row["first_seen"] else None,
                    "lat": float(row["lat"]) if row["lat"] is not None else None,
                    "lon": float(row["lon"]) if row["lon"] is not None else None,
                    "stat_score": (round(float(row["stat_score"]), 3) if row["stat_score"] is not None else None),
                    "ai_score": (round(float(row["ai_score"]), 3) if row["ai_score"] is not None else None),
                    "combined_score": (round(float(row["combined_score"]), 3) if row["combined_score"] is not None else None),
                    "percentile_rank": (round(float(row["percentile_rank"]), 3) if row["percentile_rank"] is not None else None),
                    "z_score": (round(float(row["z_score"]), 3) if row["z_score"] is not None else None),
                    "price_per_m2": (round(float(row["price_per_m2"]), 2) if row["price_per_m2"] is not None else None),
                    "neighborhood_mean": (round(float(row["neighborhood_mean"]), 2) if row["neighborhood_mean"] is not None else None),
                    "neighborhood_name": neighborhood_name_val,
                    "parking": row["parking"],
                    "description": row["description"],
                    "available_for_rent": props_json.get("available_for_rent", False),
                    "available_for_sale": props_json.get("available_for_sale", False),
                    "ai_features": visual.get("features_detected", []),
                    "ai_issues": visual.get("issues_detected", []),
                    "ai_green_flags": sentiment.get("green_flags", []),
                    "ai_red_flags": sentiment.get("red_flags", []),
                    "condition_score": visual.get("condition_score"),
                    "sentiment_score": sentiment.get("sentiment_score"),
                    "stat_category": meta.get("stat_analysis", {}).get("category"),
                    "stat_reasoning": meta.get("stat_analysis", {}).get("reasoning"),
                    "deal_summary": meta.get("deal_verdict", {}).get("verdict"),
                    "visual_category": visual.get("category"),
                    "visual_reasoning": visual.get("reasoning"),
                    "sentiment_category": sentiment.get("category"),
                    "sentiment_reasoning": sentiment.get("reasoning"),
                    "listings": row["listings"] or [],
                }
            )

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
            "properties": properties,
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


@router.get("/{property_id}", response_model=PropertyDetailModel)
def get_property(property_id: str) -> Dict[str, Any]:
    """Return a single property with full scoring details."""
    with SessionLocal() as session:
        sql = text("""
            SELECT
                p.id, p.platform, p.platform_id, p.title, p.description,
                p.price, p.area_m2, p.bedrooms, p.bathrooms, p.parking,
                p.address, p.image_urls, p.first_seen, p.props_json,
                ms.stat_score, ms.ai_score, ms.combined_score,
                ms.percentile_rank, ms.z_score, ms.price_per_m2,
                ms.neighborhood_mean, ms.neighborhood_median, ms.meta,
                n.name AS neighborhood_name,
                ST_X(p.location::geometry) AS lon, ST_Y(p.location::geometry) AS lat,
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
            FROM properties p
            LEFT JOIN metrics_scoring ms ON ms.property_id = p.id
            LEFT JOIN neighborhoods n ON n.id = p.neighborhood_id
            WHERE p.id = :id
        """)
        row = session.execute(sql, {"id": property_id}).mappings().fetchone()
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Property not found")

        meta = row["meta"] or {}
        return {
            "id": str(row["id"]),
            "platform": row["platform"],
            "platform_id": row["platform_id"],
            "title": row["title"],
            "description": row["description"],
            "price": row["price"],
            "area_m2": row["area_m2"],
            "bedrooms": row["bedrooms"],
            "bathrooms": row["bathrooms"],
            "parking": row["parking"],
            "address": row["address"],
            "image_urls": row["image_urls"] or [],
            "created_at": row["first_seen"].isoformat() if row["first_seen"] else None,
            "props_json": row["props_json"] or {},
            "stat_score": float(row["stat_score"]) if row["stat_score"] is not None else None,
            "ai_score": float(row["ai_score"]) if row["ai_score"] is not None else None,
            "combined_score": float(row["combined_score"]) if row["combined_score"] is not None else None,
            "percentile_rank": float(row["percentile_rank"]) if row["percentile_rank"] is not None else None,
            "z_score": float(row["z_score"]) if row["z_score"] is not None else None,
            "price_per_m2": float(row["price_per_m2"]) if row["price_per_m2"] is not None else None,
            "neighborhood_mean": float(row["neighborhood_mean"]) if row["neighborhood_mean"] is not None else None,
            "neighborhood_median": float(row["neighborhood_median"]) if row["neighborhood_median"] is not None else None,
            "neighborhood_name": row["neighborhood_name"] or (row["props_json"] or {}).get("neighborhood"),
            "location": {"lon": row["lon"], "lat": row["lat"]},
            "listings": row["listings"] or [],
            "deal_summary": meta.get("deal_verdict", {}).get("verdict"),
            "stat_analysis": meta.get("stat_analysis", {}),
            "ai_analysis": {
                "visual": meta.get("visual", {}),
                "sentiment": meta.get("sentiment", {}),
            },
        }


@router.get("/{property_id}/price-history", response_model=List[PriceHistoryModel])
def get_price_history(
    property_id: str,
    listing_type: Optional[str] = Query(None, pattern="^(rent|sale)$"),
    platform: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return ordered price-history intervals for a property.

    Optionally filter by listing_type (rent/sale) and/or platform.
    """
    with SessionLocal() as session:
        # Verify property exists
        check = session.execute(
            text("SELECT id FROM properties WHERE id = :id"),
            {"id": property_id},
        ).fetchone()
        if check is None:
            from fastapi import HTTPException

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
