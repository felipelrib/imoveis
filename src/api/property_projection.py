"""AD-12 canonical property projection — primary listing + shared serializers.

Primary-listing rule (decisioning price):
  Among listings with a non-null price, pick the lowest price.
  Ties: listing_type ``rent`` before ``sale``; then ``platform`` ascending.
  If no priced listings, ``primary_listing`` is None and callers keep ``p.price``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from core.neighbourhood_quality import quality_profile_fields

_LISTING_TYPE_RANK = {"rent": 0, "sale": 1}


def _round_or_none(value: Any, digits: int) -> Optional[float]:
    return round(float(value), digits) if value is not None else None


def _dual_score_fields(row: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    """Map rent/sale score columns from a DB row (BIN-83)."""
    return {
        "stat_score_rent": _round_or_none(row.get("stat_score_rent"), 3),
        "stat_score_sale": _round_or_none(row.get("stat_score_sale"), 3),
        "z_score_rent": _round_or_none(row.get("z_score_rent"), 3),
        "z_score_sale": _round_or_none(row.get("z_score_sale"), 3),
        "percentile_rank_rent": _round_or_none(row.get("percentile_rank_rent"), 3),
        "percentile_rank_sale": _round_or_none(row.get("percentile_rank_sale"), 3),
        "combined_score_rent": _round_or_none(row.get("combined_score_rent"), 3),
        "combined_score_sale": _round_or_none(row.get("combined_score_sale"), 3),
    }


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


def _humanize_label(value: str | None) -> Optional[str]:
    """Title-case slug-like neighborhood labels (e.g. ``sion`` → ``Sion``)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "-" in text or "_" in text or text == text.lower():
        return text.replace("-", " ").replace("_", " ").strip().title()
    return text


def neighborhood_fields(row: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    """Neighbourhood id/label + city for AD-12 decisioning views."""
    props_json = row.get("props_json") or {}
    neighborhood_id = row.get("neighborhood_id")
    if neighborhood_id is not None:
        neighborhood_id = str(neighborhood_id)
    raw_nb = row.get("neighborhood_name") or props_json.get("neighborhood")
    neighborhood_name = _humanize_label(raw_nb) if raw_nb else None
    city = row.get("city") or props_json.get("city")
    if city is not None:
        city = str(city).strip() or None
    # City leaked into neighborhood — prefer showing city only at city field.
    if (
        neighborhood_name
        and city
        and neighborhood_name.casefold() == city.casefold()
    ):
        neighborhood_name = None
    return {
        "neighborhood_id": neighborhood_id,
        "neighborhood_name": neighborhood_name,
        "city": city,
    }


def neighbourhood_quality_fields(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Objective quality profile when the property is linked to a neighbourhood."""
    if row.get("neighborhood_id") is None:
        return None
    profile = quality_profile_fields(
        {
            "id": row.get("neighborhood_id"),
            "amenity_score": row.get("amenity_score"),
            "transit_score": row.get("transit_score"),
            "access_score": row.get("access_score"),
            "safety_score": row.get("safety_score"),
            "risk_flags": row.get("risk_flags"),
            "quality_meta": row.get("quality_meta"),
            "quality_notes": row.get("quality_notes"),
        }
    )
    profile.pop("id", None)
    return profile


def format_location_label(
    neighborhood_name: str | None, city: str | None
) -> Optional[str]:
    """Card pin text: ``Neighborhood, City`` when both differ."""
    nb = (neighborhood_name or "").strip() or None
    c = (city or "").strip() or None
    if nb and c and nb.casefold() != c.casefold():
        return f"{nb}, {c}"
    return nb or c


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
        "public_id": int(row["public_id"]) if row.get("public_id") is not None else None,
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
        "price_per_m2_rent": _round_or_none(row.get("price_per_m2_rent"), 2),
        "price_per_m2_sale": _round_or_none(row.get("price_per_m2_sale"), 2),
        "neighborhood_mean_rent": _round_or_none(row.get("neighborhood_mean_rent"), 2),
        "neighborhood_mean_sale": _round_or_none(row.get("neighborhood_mean_sale"), 2),
        **_dual_score_fields(row),
        "neighborhood_id": nbr["neighborhood_id"],
        "neighborhood_name": nbr["neighborhood_name"],
        "city": nbr["city"],
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
        "neighbourhood_quality": neighbourhood_quality_fields(row),
    }


def map_property_detail(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Serialize a DB row to PropertyDetailModel (nested analysis + AD-12 fields)."""
    meta = row.get("meta") or {}
    listings = list(row.get("listings") or [])
    primary = select_primary_listing(listings)
    nbr = neighborhood_fields(row)

    return {
        "id": str(row["id"]),
        "public_id": int(row["public_id"]) if row.get("public_id") is not None else None,
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
        "price_per_m2_rent": (
            float(row["price_per_m2_rent"]) if row.get("price_per_m2_rent") is not None else None
        ),
        "price_per_m2_sale": (
            float(row["price_per_m2_sale"]) if row.get("price_per_m2_sale") is not None else None
        ),
        "neighborhood_mean_rent": (
            float(row["neighborhood_mean_rent"]) if row.get("neighborhood_mean_rent") is not None else None
        ),
        "neighborhood_mean_sale": (
            float(row["neighborhood_mean_sale"]) if row.get("neighborhood_mean_sale") is not None else None
        ),
        "neighborhood_median_rent": (
            float(row["neighborhood_median_rent"])
            if row.get("neighborhood_median_rent") is not None
            else None
        ),
        "neighborhood_median_sale": (
            float(row["neighborhood_median_sale"])
            if row.get("neighborhood_median_sale") is not None
            else None
        ),
        **_dual_score_fields(row),
        "neighborhood_id": nbr["neighborhood_id"],
        "neighborhood_name": nbr["neighborhood_name"],
        "city": nbr["city"],
        "location": {"lon": row.get("lon"), "lat": row.get("lat")},
        "listings": listings,
        "primary_listing": primary,
        "deal_summary": meta.get("deal_verdict", {}).get("verdict"),
        "stat_analysis": meta.get("stat_analysis", {}),
        "ai_analysis": {
            "visual": meta.get("visual", {}),
            "sentiment": meta.get("sentiment", {}),
        },
        "neighbourhood_quality": neighbourhood_quality_fields(row),
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
        WHERE pl.property_id = p.id AND pl.active = true
    ) AS listings
"""

LIST_SELECT_COLUMNS = f"""
                p.id,
                p.public_id,
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
                ms.price_per_m2_rent,
                ms.price_per_m2_sale,
                ms.neighborhood_mean_rent,
                ms.neighborhood_mean_sale,
                ms.stat_score_rent,
                ms.stat_score_sale,
                ms.z_score_rent,
                ms.z_score_sale,
                ms.percentile_rank_rent,
                ms.percentile_rank_sale,
                ms.combined_score_rent,
                ms.combined_score_sale,
                ms.meta,
                p.neighborhood_id,
                n.name AS neighborhood_name,
                COALESCE(n.city, p.props_json->>'city') AS city,
                n.amenity_score,
                n.transit_score,
                n.access_score,
                n.safety_score,
                n.risk_flags,
                n.quality_meta,
                n.quality_notes,
                p.parking,
                p.description,
                p.props_json,
                ST_X(p.location::geometry) AS lon,
                ST_Y(p.location::geometry) AS lat,
                {LISTINGS_JSON_AGG}
"""
