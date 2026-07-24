"""AD-12 canonical property projection — primary listing + shared serializers.

Primary-listing rule (decisioning price):
  Among listings with a non-null price, pick the lowest price.
  Ties: listing_type ``rent`` before ``sale``; then ``platform`` ascending.
  If no priced listings, ``primary_listing`` is None and callers keep ``p.price``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

_LISTING_TYPE_RANK = {"rent": 0, "sale": 1}


def _round_or_none(value: Any, digits: int) -> Optional[float]:
    return round(float(value), digits) if value is not None else None


def select_primary_listing(listings: Sequence[Mapping[str, Any]] | None) -> Optional[Dict[str, Any]]:
    """Return the canonical primary listing dict, or None if none are priced."""
    if not listings:
        return None

    priced: List[Mapping[str, Any]] = []
    for listing in listings:
        price = listing.get("price")
        if price is None:
            continue
        try:
            float(price)
        except (TypeError, ValueError):
            continue
        priced.append(listing)

    if not priced:
        return None

    def _sort_key(listing: Mapping[str, Any]) -> tuple:
        price = float(listing["price"])
        listing_type = str(listing.get("listing_type") or "sale")
        type_rank = _LISTING_TYPE_RANK.get(listing_type, 99)
        platform = str(listing.get("platform") or "")
        return (price, type_rank, platform)

    winner = min(priced, key=_sort_key)
    return dict(winner)


def decisioning_price(row_price: Any, primary: Optional[Mapping[str, Any]]) -> float:
    """Top-level price: primary listing price when present, else property row price."""
    if primary is not None and primary.get("price") is not None:
        return float(primary["price"])
    return float(row_price)


def neighborhood_fields(row: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    """Neighbourhood id/label for AD-12 decisioning views."""
    props_json = row.get("props_json") or {}
    neighborhood_id = row.get("neighborhood_id")
    if neighborhood_id is not None:
        neighborhood_id = str(neighborhood_id)
    neighborhood_name = row.get("neighborhood_name") or props_json.get("neighborhood")
    return {
        "neighborhood_id": neighborhood_id,
        "neighborhood_name": neighborhood_name,
    }


def map_property_list_item(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Serialize a DB row to the list/batch PropertyModel projection."""
    meta = row.get("meta") or {}
    visual = meta.get("visual", {})
    sentiment = meta.get("sentiment", {})
    props_json = row.get("props_json") or {}
    listings = list(row.get("listings") or [])
    primary = select_primary_listing(listings)
    nbr = neighborhood_fields(row)

    return {
        "id": str(row["id"]),
        "platform": row["platform"],
        "platform_id": row["platform_id"],
        "title": row["title"],
        "price": decisioning_price(row["price"], primary),
        "area_m2": row["area_m2"],
        "bedrooms": row["bedrooms"],
        "bathrooms": row["bathrooms"],
        "address": row["address"],
        "image_urls": row["image_urls"] or [],
        "created_at": row["first_seen"].isoformat() if row.get("first_seen") else None,
        "lat": float(row["lat"]) if row.get("lat") is not None else None,
        "lon": float(row["lon"]) if row.get("lon") is not None else None,
        "stat_score": _round_or_none(row.get("stat_score"), 3),
        "ai_score": _round_or_none(row.get("ai_score"), 3),
        "combined_score": _round_or_none(row.get("combined_score"), 3),
        "percentile_rank": _round_or_none(row.get("percentile_rank"), 3),
        "z_score": _round_or_none(row.get("z_score"), 3),
        "price_per_m2": _round_or_none(row.get("price_per_m2"), 2),
        "neighborhood_mean": _round_or_none(row.get("neighborhood_mean"), 2),
        "neighborhood_id": nbr["neighborhood_id"],
        "neighborhood_name": nbr["neighborhood_name"],
        "parking": row.get("parking"),
        "description": row.get("description"),
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
        "listings": listings,
        "primary_listing": primary,
    }


def map_property_detail(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Serialize a DB row to PropertyDetailModel (nested analysis + AD-12 fields)."""
    meta = row.get("meta") or {}
    listings = list(row.get("listings") or [])
    primary = select_primary_listing(listings)
    nbr = neighborhood_fields(row)

    return {
        "id": str(row["id"]),
        "platform": row["platform"],
        "platform_id": row["platform_id"],
        "title": row["title"],
        "description": row.get("description"),
        "price": decisioning_price(row["price"], primary),
        "area_m2": row.get("area_m2"),
        "bedrooms": row.get("bedrooms"),
        "bathrooms": row.get("bathrooms"),
        "parking": row.get("parking"),
        "address": row.get("address"),
        "image_urls": row.get("image_urls") or [],
        "created_at": row["first_seen"].isoformat() if row.get("first_seen") else None,
        "props_json": row.get("props_json") or {},
        "stat_score": float(row["stat_score"]) if row.get("stat_score") is not None else None,
        "ai_score": float(row["ai_score"]) if row.get("ai_score") is not None else None,
        "combined_score": float(row["combined_score"]) if row.get("combined_score") is not None else None,
        "percentile_rank": float(row["percentile_rank"]) if row.get("percentile_rank") is not None else None,
        "z_score": float(row["z_score"]) if row.get("z_score") is not None else None,
        "price_per_m2": float(row["price_per_m2"]) if row.get("price_per_m2") is not None else None,
        "neighborhood_mean": float(row["neighborhood_mean"]) if row.get("neighborhood_mean") is not None else None,
        "neighborhood_median": (
            float(row["neighborhood_median"]) if row.get("neighborhood_median") is not None else None
        ),
        "neighborhood_id": nbr["neighborhood_id"],
        "neighborhood_name": nbr["neighborhood_name"],
        "location": {"lon": row.get("lon"), "lat": row.get("lat")},
        "listings": listings,
        "primary_listing": primary,
        "deal_summary": meta.get("deal_verdict", {}).get("verdict"),
        "stat_analysis": meta.get("stat_analysis", {}),
        "ai_analysis": {
            "visual": meta.get("visual", {}),
            "sentiment": meta.get("sentiment", {}),
        },
    }


# Shared SQL fragments for AD-12 list/export/digest queries (BIN-50 / BIN-52).
LISTINGS_JSON_AGG = """
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
                'iptu', pl.iptu,
                'base_price', pl.base_price,
                'fees_bundled', (pl.raw_json->>'fees_bundled')::boolean
            )
        )
        FROM property_listings pl
        WHERE pl.property_id = p.id
    ) AS listings
"""

LIST_SELECT_COLUMNS = f"""
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
                {LISTINGS_JSON_AGG}
"""
