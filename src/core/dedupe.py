import logging
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.entities import PropertyCandidate

logger = logging.getLogger(__name__)


@dataclass
class DedupeMatchResult:
    """Result of a deduplication match."""

    property_id: str
    action: str  # "created", "updated", "noop"


def text_similarity(
    a: Optional[str],
    b: Optional[str],
    algorithm: str = "jaro_winkler",
) -> float:
    """Calculate similarity between two strings."""
    try:
        if not a or not b:
            return 0.0

        # Importação condicional para evitar dependências desnecessárias
        if algorithm == "jaro_winkler":
            from jellyfish import jaro_winkler_similarity

            return jaro_winkler_similarity(a, b)
        elif algorithm == "levenshtein":
            from jellyfish import levenshtein_distance

            max_len = max(len(a), len(b))
            if max_len == 0:
                return 1.0
            distance = levenshtein_distance(a, b)
            return 1.0 - (distance / max_len)
        else:
            raise ValueError(f"Unknown similarity algorithm: {algorithm}")

    except Exception as e:
        logger.error(f"Error calculating text similarity: {e}")
        return 0.0


def match_or_create_property(
    session: Session,
    candidate: PropertyCandidate,
    radius_m: float = 50.0,
    text_threshold: float = 0.85,
    area_tol: float = 5.0,
) -> DedupeMatchResult:
    """Match a scraper candidate against existing properties, or create a new one.

    Matching strategy:
      1. Exact match on (platform, platform_id) → update.
      2. Spatial proximity + title similarity → merge as duplicate.
      3. No match → create new property.

    Args:
        session: Active SQLAlchemy session.
        candidate: Validated scraper output.
        radius_m: Geospatial search radius in metres.
        text_threshold: Minimum Jaro-Winkler similarity for title match.
        area_tol: Maximum absolute difference in area_m2 for fuzzy match.

    Returns:
        DedupeMatchResult with the property_id and action taken.
    """
    from adapters.db.models import Property

    # --- Step 1: Exact platform match ---
    existing = session.query(Property).filter_by(platform=candidate.platform, platform_id=candidate.platform_id).one_or_none()
    if existing is not None:
        # Update mutable fields
        existing.price = candidate.price
        existing.title = candidate.title
        existing.description = candidate.description
        existing.image_urls = candidate.image_urls
        existing.props_json = candidate.props_json
        existing.active = True
        listings = candidate.listings or []
        _upsert_listings(session, str(existing.id), listings)
        # Fallback: if no listings provided, record property-level price history
        if not listings:
            _record_price_change(session, str(existing.id), candidate.price)
        session.flush()
        return DedupeMatchResult(property_id=str(existing.id), action="updated")

    # --- Step 2: Spatial + text fuzzy match ---
    loc = candidate.location
    if loc and loc.get("lat") and loc.get("lon"):
        lat, lon = loc["lat"], loc["lon"]
        nearby_query = text("""
            SELECT id, title, area_m2
            FROM properties
            WHERE ST_DWithin(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
            AND active = true
        """)
        nearby = session.execute(nearby_query, {"lat": lat, "lon": lon, "radius": radius_m}).fetchall()

        for row in nearby:
            title_sim = text_similarity(candidate.title, row.title)
            area_close = (
                abs((candidate.area_m2 or 0) - (row.area_m2 or 0)) <= area_tol if candidate.area_m2 and row.area_m2 else True
            )
            if title_sim >= text_threshold and area_close:
                # Merge: update the matched property
                prop = session.get(Property, row.id)
                if prop:
                    prop.price = candidate.price
                    prop.active = True
                    prop.image_urls = candidate.image_urls
                    prop.props_json = candidate.props_json
                    listings = candidate.listings or []
                    _upsert_listings(session, str(prop.id), listings)
                    # Fallback: if no listings provided, record property-level price history
                    if not listings:
                        _record_price_change(session, str(prop.id), candidate.price)
                    session.flush()
                    return DedupeMatchResult(property_id=str(prop.id), action="updated")

    # --- Step 3: Create new property ---
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    new_location = None
    if loc and loc.get("lat") and loc.get("lon"):
        new_location = from_shape(Point(loc["lon"], loc["lat"]), srid=4326)

    new_prop = Property(
        platform=candidate.platform,
        platform_id=candidate.platform_id,
        title=candidate.title,
        description=candidate.description,
        price=candidate.price,
        area_m2=candidate.area_m2,
        bedrooms=candidate.bedrooms,
        bathrooms=candidate.bathrooms,
        parking=candidate.parking,
        location=new_location,
        address=candidate.address,
        image_urls=candidate.image_urls,
        props_json=candidate.props_json,
        active=True,
        currency=candidate.currency,
    )
    session.add(new_prop)
    session.flush()
    listings = candidate.listings or []
    _upsert_listings(session, str(new_prop.id), listings)
    # Fallback: if no listings provided, seed property-level price history
    if not listings:
        _record_price_change(session, str(new_prop.id), candidate.price)
    session.flush()
    return DedupeMatchResult(property_id=str(new_prop.id), action="created")


def _record_price_change(
    session: Session,
    property_id: str,
    new_price: float,
    listing_type: str = "sale",
    platform: Optional[str] = None,
    property_listing_id: Optional[str] = None,
) -> None:
    """Record a price change in the price_history table.

    Each (property_id, listing_type, platform) triplet maintains its own
    independent open interval.  If an open interval exists and the price
    differs, close it and insert a new row.  If the price is the same,
    do nothing.  If no open interval exists, seed one (handles first-seen).

    Also checks the watchlist for price-drop alerts.
    """
    now = datetime.now(timezone.utc)

    open_row = session.execute(
        text(
            "SELECT id, price FROM price_history "
            "WHERE property_id = :pid AND listing_type = :lt AND platform = :platform "
            "AND end_ts IS NULL "
            "ORDER BY start_ts DESC LIMIT 1"
        ),
        {"pid": property_id, "lt": listing_type, "platform": platform},
    ).fetchone()

    if open_row is not None:
        old_price = float(open_row.price)
        if old_price == new_price:
            return  # price unchanged — no-op
        # Close the current open interval
        session.execute(
            text("UPDATE price_history SET end_ts = :now WHERE id = :id"),
            {"now": now, "id": str(open_row.id)},
        )
        # Insert new open interval
        session.execute(
            text(
                "INSERT INTO price_history "
                "(id, property_id, listing_type, platform, property_listing_id, price, start_ts, end_ts) "
                "VALUES (:id, :pid, :lt, :platform, :plid, :price, :now, NULL)"
            ),
            {
                "id": str(_uuid.uuid4()),
                "pid": property_id,
                "lt": listing_type,
                "platform": platform,
                "plid": property_listing_id,
                "price": new_price,
                "now": now,
            },
        )
        # Check for price-drop alerts
        _check_watchlist_alerts(session, property_id, old_price, new_price, platform, listing_type)
    else:
        # No open interval — seed initial history row
        session.execute(
            text(
                "INSERT INTO price_history "
                "(id, property_id, listing_type, platform, property_listing_id, price, start_ts, end_ts) "
                "VALUES (:id, :pid, :lt, :platform, :plid, :price, :now, NULL)"
            ),
            {
                "id": str(_uuid.uuid4()),
                "pid": property_id,
                "lt": listing_type,
                "platform": platform,
                "plid": property_listing_id,
                "price": new_price,
                "now": now,
            },
        )


def _check_watchlist_alerts(
    session: Session,
    property_id: str,
    old_price: float,
    new_price: float,
    platform: Optional[str],
    listing_type: Optional[str],
) -> None:
    """Check if any watchlist entries should be alerted for this price drop."""
    try:
        rows = session.execute(
            text(
                "SELECT id, min_drop_pct, last_notified_price "
                "FROM watchlist WHERE property_id = :pid"
            ),
            {"pid": property_id},
        ).fetchall()
    except Exception:
        # watchlist table may not exist in test SQLite databases
        return

    if not rows:
        return

    for row in rows:
        min_drop_pct = float(row.min_drop_pct or 5.0)
        last_notified_price = float(row.last_notified_price) if row.last_notified_price is not None else None

        # Calculate percentage drop
        if old_price <= 0:
            continue
        drop_pct = ((old_price - new_price) / old_price) * 100.0

        if drop_pct >= min_drop_pct and last_notified_price != new_price:
            # Fire alert
            try:
                from adapters.notify import get_notifiers
                from adapters.notify.base import PriceDropAlert

                alert = PriceDropAlert(
                    property_id=property_id,
                    old_price=old_price,
                    new_price=new_price,
                    drop_pct=drop_pct,
                    platform=platform,
                    listing_type=listing_type,
                )
                for notifier in get_notifiers():
                    notifier.send(alert)

                # Update last_notified_price
                session.execute(
                    text("UPDATE watchlist SET last_notified_price = :price WHERE id = :id"),
                    {"price": new_price, "id": str(row.id)},
                )
            except Exception as exc:
                logger.warning(
                    "watchlist_alert_error",
                    property_id=property_id,
                    error=str(exc),
                )


def _upsert_listings(
    session: Session,
    property_id: str,
    listings: List[dict],
) -> None:
    """Upsert PropertyListing rows keyed on (platform, platform_listing_id, listing_type).

    For each listing dict from the scraper normalizer, either update an existing
    row or insert a new one.  This keeps the property_listings table in sync with
    every scrape run.  Records price history per-listing (per platform + listing_type).
    Uses raw SQL for database-agnostic operation.
    """
    for listing in listings:
        # Check if listing already exists
        check = session.execute(
            text(
                "SELECT id, price FROM property_listings "
                "WHERE property_id = :pid "
                "AND platform = :platform "
                "AND platform_listing_id = :plid "
                "AND listing_type = :lt"
            ),
            {
                "pid": property_id,
                "platform": listing["platform"],
                "plid": listing["platform_listing_id"],
                "lt": listing["listing_type"],
            },
        ).fetchone()

        now = datetime.now(timezone.utc)

        if check:
            old_price = float(check.price) if check.price is not None else None
            new_price = float(listing["price"])

            session.execute(
                text(
                    "UPDATE property_listings "
                    "SET price = :price, currency = :currency, url = :url, "
                    "is_furnished = :is_furnished, accepts_pets = :accepts_pets, "
                    "condo_fee = :condo_fee, iptu = :iptu, raw_json = :raw_json, "
                    "last_seen = :now, active = true "
                    "WHERE id = :id"
                ),
                {
                    "price": new_price,
                    "currency": listing.get("currency", "BRL"),
                    "url": listing.get("url"),
                    "is_furnished": listing.get("is_furnished"),
                    "accepts_pets": listing.get("accepts_pets"),
                    "condo_fee": listing.get("condo_fee"),
                    "iptu": listing.get("iptu"),
                    "raw_json": (str(listing.get("raw_json")) if listing.get("raw_json") is not None else None),
                    "now": now,
                    "id": str(check.id),
                },
            )

            # Record price history only if price actually changed
            if old_price is None or old_price != new_price:
                _record_price_change(
                    session,
                    property_id,
                    new_price,
                    listing_type=listing["listing_type"],
                    platform=listing["platform"],
                    property_listing_id=str(check.id),
                )
        else:
            listing_id = str(_uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO property_listings "
                    "(id, property_id, platform, platform_listing_id, listing_type, "
                    "price, currency, url, is_furnished, accepts_pets, condo_fee, iptu, "
                    "raw_json, first_seen, last_seen, active) "
                    "VALUES (:id, :pid, :platform, :plid, :lt, "
                    ":price, :currency, :url, :is_furnished, :accepts_pets, :condo_fee, :iptu, "
                    ":raw_json, :now, :now, true)"
                ),
                {
                    "id": listing_id,
                    "pid": property_id,
                    "platform": listing["platform"],
                    "plid": listing["platform_listing_id"],
                    "lt": listing["listing_type"],
                    "price": listing["price"],
                    "currency": listing.get("currency", "BRL"),
                    "url": listing.get("url"),
                    "is_furnished": listing.get("is_furnished"),
                    "accepts_pets": listing.get("accepts_pets"),
                    "condo_fee": listing.get("condo_fee"),
                    "iptu": listing.get("iptu"),
                    "raw_json": (str(listing.get("raw_json")) if listing.get("raw_json") is not None else None),
                    "now": now,
                },
            )

            # Seed initial price history for new listing
            _record_price_change(
                session,
                property_id,
                float(listing["price"]),
                listing_type=listing["listing_type"],
                platform=listing["platform"],
                property_listing_id=listing_id,
            )


def find_candidates(
    session: Session,
    lat: float,
    lon: float,
    radius_m: float = 50.0,
) -> List[Tuple]:
    """Find property candidates within a given radius using PostGIS."""
    try:
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            logger.warning("Invalid coordinates provided")
            return []

        if radius_m <= 0:
            logger.warning("Invalid radius provided")
            return []

        query = text("""
            SELECT id, ST_Y(location::geometry) as lat, ST_X(location::geometry) as lon, address
            FROM properties
            WHERE ST_DWithin(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
        """)

        result = session.execute(query, {"lat": lat, "lon": lon, "radius": radius_m}).fetchall()

        candidates = []
        for row in result:
            candidates.append((row.lat, row.lon, row.address))

        logger.debug(f"Found {len(candidates)} candidates near ({lat}, {lon})")
        return candidates

    except Exception as e:
        logger.error(f"Error finding candidates: {e}")
        return []
