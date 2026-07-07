"""Properties query API — used by the GUI property browser."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from sqlalchemy import text

from infra.db import SessionLocal
from infra.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/properties", tags=["properties"])


@router.get("")
def list_properties(
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
    sort_by: str = Query("combined_score", pattern="^(combined_score|price|first_seen|area_m2)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
) -> Dict[str, Any]:
    """Return paginated, filtered, scored properties for the GUI grid."""
    session = SessionLocal()
    try:
        filters = ["p.active = true"]
        params: Dict[str, Any] = {
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }

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
            filters.append(f"(p.props_json->>'available_for_{listing_type}')::boolean = true")

        if property_type:
            filters.append("p.props_json->>'type' ILIKE :property_type")
            params["property_type"] = f"%{property_type}%"

        if is_furnished is not None:
            filters.append(f"(p.props_json->>'isFurnished')::boolean = {'true' if is_furnished else 'false'}")

        if accepts_pets is not None:
            if accepts_pets:
                filters.append("p.props_json->'amenities' ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO'")
            else:
                filters.append("NOT (p.props_json->'amenities' ? 'PODE_TER_ANIMAIS_DE_ESTIMACAO')")

        where = " AND ".join(filters)
        sort_col_map = {
            "combined_score": "COALESCE(ms.combined_score, 0)",
            "price": "p.price",
            "first_seen": "p.first_seen",
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
        rows = session.execute(sql, params).fetchall()

        properties = []
        for row in rows:
            meta = row[18] or {}
            visual = meta.get("visual", {})
            sentiment = meta.get("sentiment", {})
            props_json = row[22] or {}

            neighborhood_name_val = row[19] or props_json.get("neighborhood")

            properties.append(
                {
                    "id": str(row[0]),
                    "platform": row[1],
                    "platform_id": row[2],
                    "title": row[3],
                    "price": row[4],
                    "area_m2": row[5],
                    "bedrooms": row[6],
                    "bathrooms": row[7],
                    "address": row[8],
                    "image_urls": row[9] or [],
                    "created_at": row[10].isoformat() if row[10] else None,
                    "stat_score": (round(float(row[11]), 3) if row[11] is not None else None),
                    "ai_score": (round(float(row[12]), 3) if row[12] is not None else None),
                    "combined_score": (round(float(row[13]), 3) if row[13] is not None else None),
                    "percentile_rank": (round(float(row[14]), 3) if row[14] is not None else None),
                    "z_score": (round(float(row[15]), 3) if row[15] is not None else None),
                    "price_per_m2": (round(float(row[16]), 2) if row[16] is not None else None),
                    "neighborhood_mean": (round(float(row[17]), 2) if row[17] is not None else None),
                    "neighborhood_name": neighborhood_name_val,
                    "parking": row[20],
                    "description": row[21],
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
                    "visual_category": visual.get("category"),
                    "visual_reasoning": visual.get("reasoning"),
                    "sentiment_category": sentiment.get("category"),
                    "sentiment_reasoning": sentiment.get("reasoning"),
                    "listings": row[23] or [],
                }
            )

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
            "properties": properties,
        }
    finally:
        session.close()


@router.get("/{property_id}")
def get_property(property_id: str) -> Dict[str, Any]:
    """Return a single property with full scoring details."""
    session = SessionLocal()
    try:
        sql = text("""
            SELECT
                p.id, p.platform, p.platform_id, p.title, p.description,
                p.price, p.area_m2, p.bedrooms, p.bathrooms, p.parking,
                p.address, p.image_urls, p.first_seen, p.props_json,
                ms.stat_score, ms.ai_score, ms.combined_score,
                ms.percentile_rank, ms.z_score, ms.price_per_m2,
                ms.neighborhood_mean, ms.neighborhood_median, ms.meta,
                n.name AS neighborhood_name,
                ST_X(p.location) AS lon, ST_Y(p.location) AS lat,
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
        row = session.execute(sql, {"id": property_id}).fetchone()
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Property not found")

        meta = row[22] or {}
        return {
            "id": str(row[0]),
            "platform": row[1],
            "platform_id": row[2],
            "title": row[3],
            "description": row[4],
            "price": row[5],
            "area_m2": row[6],
            "bedrooms": row[7],
            "bathrooms": row[8],
            "parking": row[9],
            "address": row[10],
            "image_urls": row[11] or [],
            "created_at": row[12].isoformat() if row[12] else None,
            "props_json": row[13] or {},
            "stat_score": float(row[14]) if row[14] is not None else None,
            "ai_score": float(row[15]) if row[15] is not None else None,
            "combined_score": float(row[16]) if row[16] is not None else None,
            "percentile_rank": float(row[17]) if row[17] is not None else None,
            "z_score": float(row[18]) if row[18] is not None else None,
            "price_per_m2": float(row[19]) if row[19] is not None else None,
            "neighborhood_mean": float(row[20]) if row[20] is not None else None,
            "neighborhood_median": float(row[21]) if row[21] is not None else None,
            "neighborhood_name": row[23] or (row[13] or {}).get("neighborhood"),
            "location": {"lon": row[24], "lat": row[25]},
            "listings": row[26] or [],
            "stat_analysis": meta.get("stat_analysis", {}),
            "ai_analysis": {
                "visual": meta.get("visual", {}),
                "sentiment": meta.get("sentiment", {}),
            },
        }
    finally:
        session.close()


@router.get("/{property_id}/price-history")
def get_price_history(property_id: str) -> List[Dict[str, Any]]:
    """Return ordered price-history intervals for a property."""
    session = SessionLocal()
    try:
        # Verify property exists
        check = session.execute(
            text("SELECT id FROM properties WHERE id = :id"),
            {"id": property_id},
        ).fetchone()
        if check is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Property not found")

        rows = session.execute(
            text(
                "SELECT id, price, start_ts, end_ts "
                "FROM price_history "
                "WHERE property_id = :pid "
                "ORDER BY start_ts DESC"
            ),
            {"pid": property_id},
        ).fetchall()

        return [
            {
                "id": str(r[0]),
                "price": float(r[1]),
                "start_ts": r[2].isoformat() if r[2] else None,
                "end_ts": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]
    finally:
        session.close()
