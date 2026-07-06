"""Property deduplication engine.

Resolves incoming ``PropertyCandidate`` objects against the database,
either matching an existing property (updating price history if needed)
or creating a new record.

Key design choices
------------------
* **rapidfuzz** for text similarity (Jaro-Winkler or token-sort-ratio,
  selectable via ``dedup.text_similarity_algorithm`` in config).
* **SCD-2** for price history — old record gets ``end_ts = now``, new
  record starts with ``end_ts = None`` (current price).
* **PostGIS ST_DWithin** for spatial candidate search, wrapped in
  ``sqlalchemy.text()`` for SA 2.0 compatibility.
* Auto-assigns ``neighborhood_id`` via spatial lookup after creation.
* Returns a typed ``DedupeResult`` instead of a raw dict.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from geoalchemy2.shape import from_shape
from rapidfuzz import fuzz
from shapely.geometry import Point
from sqlalchemy import text
from sqlalchemy.orm import Session

from adapters.db.models import Neighborhood, PriceHistory, Property, PropertyListing
from core.entities import DedupeResult, PropertyCandidate
from infra.config import get_config
from sqlalchemy.dialects.postgresql import insert
from infra.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Text similarity
# ---------------------------------------------------------------------------

def text_similarity(
    a: Optional[str],
    b: Optional[str],
    algorithm: str = "jaro_winkler",
) -> float:
    """Return a 0-1 similarity score between two strings.

    Parameters
    ----------
    algorithm
        ``"jaro_winkler"`` — uses ``fuzz.jaro_winkler_similarity`` (0-100).
        ``"token_sort"``  — uses ``fuzz.token_sort_ratio`` (0-100).
    """
    if not a or not b:
        return 0.0
    if algorithm == "token_sort":
        return fuzz.token_sort_ratio(a, b) / 100.0
    return fuzz.jaro_winkler_similarity(a, b) / 100.0


# ---------------------------------------------------------------------------
# Spatial candidate search
# ---------------------------------------------------------------------------

def find_candidates(
    session: Session,
    lat: float,
    lon: float,
    radius_m: float = 50.0,
) -> List[str]:
    """Return candidate Property IDs within *radius_m* metres using PostGIS.

    Uses ``geography`` cast for metre-accurate distance on the WGS-84 ellipsoid.
    """
    sql = text(
        "SELECT id FROM properties "
        "WHERE ST_DWithin("
        "  location::geography, "
        "  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
        "  :radius"
        ") "
        "LIMIT 50"
    )
    rows = session.execute(sql, {"lon": lon, "lat": lat, "radius": radius_m}).fetchall()
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Neighbourhood spatial lookup
# ---------------------------------------------------------------------------

def _lookup_neighborhood(session: Session, lat: float, lon: float) -> Optional[str]:
    """Return the neighbourhood UUID whose polygon contains the point, or None."""
    sql = text(
        "SELECT id FROM neighborhoods "
        "WHERE ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) "
        "LIMIT 1"
    )
    row = session.execute(sql, {"lon": lon, "lat": lat}).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Price-change detection
# ---------------------------------------------------------------------------

def _price_changed(old: float, new: float) -> bool:
    try:
        return float(old) != float(new)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# SCD-2 price history
# ---------------------------------------------------------------------------

def _record_price_change(
    session: Session,
    prop: Property,
    new_price: float,
) -> None:
    """Close the current price-history record and open a new one (SCD-2)."""
    now = datetime.now(timezone.utc)

    # Close any open (end_ts IS NULL) price-history row
    open_record: Optional[PriceHistory] = (
        session.query(PriceHistory)
        .filter(
            PriceHistory.property_id == prop.id,
            PriceHistory.end_ts.is_(None),
        )
        .first()
    )
    if open_record is not None:
        open_record.end_ts = now
    else:
        # No open record exists yet — back-fill one for the old price
        session.add(PriceHistory(
            property_id=prop.id,
            price=prop.price,
            start_ts=prop.first_seen or now,
            end_ts=now,
        ))

    # Create the new (current) price-history row
    session.add(PriceHistory(
        property_id=prop.id,
        price=new_price,
        start_ts=now,
        end_ts=None,
    ))

    # Update the property's live price
    prop.price = new_price


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def _merge_props(existing_props: dict, incoming_props: dict) -> dict:
    """Merge props_json while preserving availability flags from both passes."""
    existing_props = existing_props or {}
    incoming_props = incoming_props or {}
    merged = {**existing_props, **incoming_props}
    if existing_props.get("available_for_rent"):
        merged["available_for_rent"] = True
    if existing_props.get("available_for_sale"):
        merged["available_for_sale"] = True
    return merged


def _upsert_listings(session: Session, prop_id: str, candidate: PropertyCandidate) -> None:
    """Upsert the specific listings (rent/sale) from the candidate."""
    if not getattr(candidate, 'listings', None):
        return
        
    for lst in candidate.listings:
        stmt = insert(PropertyListing).values(
            property_id=prop_id,
            platform=lst.platform,
            platform_id=lst.platform_id,
            listing_type=lst.listing_type,
            price=lst.price,
            url=lst.url
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=['platform', 'platform_id', 'listing_type'],
            set_={
                'price': lst.price,
                'url': lst.url,
                'property_id': prop_id,
                'last_seen_at': datetime.now(timezone.utc)
            }
        )
        session.execute(stmt)


def match_or_create_property(
    session: Session,
    incoming: PropertyCandidate,
    radius_m: float | None = None,
    area_tol: float | None = None,
    text_threshold: float | None = None,
) -> DedupeResult:
    """Match *incoming* to an existing property or create a new one.

    Parameters that are ``None`` fall back to values in the centralised
    ``dedup`` config section.

    Returns
    -------
    DedupeResult
        Typed result with ``action``, ``property_id``, ``is_duplicate``,
        and optional ``matched_property_id``.
    """
    cfg = get_config().dedup

    radius_m = radius_m if radius_m is not None else cfg.radius_m
    area_tol = area_tol if area_tol is not None else cfg.area_tolerance_m2
    text_threshold = text_threshold if text_threshold is not None else cfg.text_similarity_threshold
    sim_algorithm: str = cfg.text_similarity_algorithm

    lat = incoming.location.lat
    lon = incoming.location.lon
    desc = incoming.description or ""

    # ------------------------------------------------------------------
    # Step 0: exact match by platform and platform_id
    # ------------------------------------------------------------------
    existing = session.query(Property).filter_by(
        platform=incoming.platform, 
        platform_id=incoming.platform_id
    ).first()

    if existing:
        merged_props = _merge_props(existing.props_json, incoming.props_json)
        if _price_changed(existing.price, incoming.price):
            logger.info("price_changed_exact", property_id=str(existing.id), old=existing.price, new=incoming.price)
            _record_price_change(session, existing, incoming.price)
            existing.props_json = merged_props
            existing.image_urls = incoming.image_urls
            session.flush()
            _upsert_listings(session, str(existing.id), incoming)
            return DedupeResult(action="updated", property_id=str(existing.id), is_duplicate=True, matched_property_id=str(existing.id))
        
        # Unchanged
        existing.props_json = merged_props
        existing.image_urls = incoming.image_urls
        session.flush()
        _upsert_listings(session, str(existing.id), incoming)
        return DedupeResult(action="noop", property_id=str(existing.id), is_duplicate=True, matched_property_id=str(existing.id))

    # ------------------------------------------------------------------
    # Step 1: spatial candidate fetch
    # ------------------------------------------------------------------
    candidate_ids = find_candidates(session, lat, lon, radius_m=radius_m)

    for cand_id in candidate_ids:
        prop: Optional[Property] = session.get(Property, cand_id)
        if prop is None:
            continue

        # Discrete-field mismatch → skip
        if (
            (prop.bedrooms is not None and incoming.bedrooms is not None and prop.bedrooms != incoming.bedrooms)
            or (prop.bathrooms is not None and incoming.bathrooms is not None and prop.bathrooms != incoming.bathrooms)
            or (prop.parking is not None and incoming.parking is not None and prop.parking != incoming.parking)
        ):
            continue

        # Area tolerance
        if prop.area_m2 is not None and incoming.area_m2 is not None:
            if abs(prop.area_m2 - incoming.area_m2) > area_tol:
                continue

        # Text similarity
        sim = text_similarity(prop.description or "", desc, algorithm=sim_algorithm)
        if sim < text_threshold:
            continue

        # ---- Duplicate confirmed -----------------------------------------
        logger.info(
            "duplicate_found",
            existing_id=str(prop.id),
            platform=incoming.platform,
            platform_id=incoming.platform_id,
            similarity=round(sim, 4),
        )

        if _price_changed(prop.price, incoming.price):
            logger.info(
                "price_changed",
                property_id=str(prop.id),
                old_price=prop.price,
                new_price=incoming.price,
            )
            _record_price_change(session, prop, incoming.price)
            prop.props_json = _merge_props(prop.props_json, incoming.props_json)
            prop.image_urls = incoming.image_urls
            session.flush()
            _upsert_listings(session, str(prop.id), incoming)
            return DedupeResult(
                action="updated",
                property_id=str(prop.id),
                is_duplicate=True,
                matched_property_id=str(prop.id),
            )

        # Price unchanged — just refresh metadata
        prop.props_json = _merge_props(prop.props_json, incoming.props_json)
        prop.image_urls = incoming.image_urls
        session.flush()
        _upsert_listings(session, str(prop.id), incoming)
        return DedupeResult(
            action="noop",
            property_id=str(prop.id),
            is_duplicate=True,
            matched_property_id=str(prop.id),
        )

    # ------------------------------------------------------------------
    # Step 2: no match — create new property
    # ------------------------------------------------------------------
    point = from_shape(Point(lon, lat), srid=4326)
    new_prop = Property(
        platform=incoming.platform,
        platform_id=incoming.platform_id,
        title=incoming.title,
        description=desc,
        price=incoming.price,
        area_m2=incoming.area_m2,
        bedrooms=incoming.bedrooms,
        bathrooms=incoming.bathrooms,
        parking=incoming.parking,
        location=point,
        address=incoming.address,
        image_urls=incoming.image_urls,
        props_json=incoming.props_json,
    )

    # Spatial neighbourhood assignment
    nbh_id = _lookup_neighborhood(session, lat, lon)
    if nbh_id is not None:
        new_prop.neighborhood_id = nbh_id

    session.add(new_prop)
    # Create initial price-history row (open-ended, current price)
    session.flush()  # ensure new_prop.id is populated
    session.add(PriceHistory(
        property_id=new_prop.id,
        price=incoming.price,
        end_ts=None,
    ))
    _upsert_listings(session, str(new_prop.id), incoming)
    session.flush()

    logger.info(
        "property_created",
        property_id=str(new_prop.id),
        platform=incoming.platform,
        platform_id=incoming.platform_id,
        neighborhood_id=str(nbh_id) if nbh_id else None,
    )

    return DedupeResult(
        action="created",
        property_id=str(new_prop.id),
        is_duplicate=False,
    )
