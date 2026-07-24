import json
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.entities import PropertyCandidate
from infra.logging import get_logger

logger = get_logger(__name__)


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
    import jellyfish  # Validate import fails loudly at call time if not installed
    try:
        if not a or not b:
            return 0.0

        if algorithm == "jaro_winkler":
            return jellyfish.jaro_winkler_similarity(a, b)
        elif algorithm == "levenshtein":
            max_len = max(len(a), len(b))
            if max_len == 0:
                return 1.0
            distance = jellyfish.levenshtein_distance(a, b)
            return 1.0 - (distance / max_len)
        elif algorithm == "token_sort":
            tokens_a = sorted(a.split())
            tokens_b = sorted(b.split())
            return jellyfish.jaro_winkler_similarity(" ".join(tokens_a), " ".join(tokens_b))
        else:
            raise ValueError(f"Unknown similarity algorithm: {algorithm!r}")

    except (TypeError, ValueError) as exc:
        logger.warning("text_similarity_error", algorithm=algorithm, error=str(exc))
        return 0.0


def match_or_create_property(
    session: Session,
    candidate: PropertyCandidate,
    radius_m: float = 50.0,
    text_threshold: float = 0.65,
    area_tol: float = 5.0,
    algorithm: str = "jaro_winkler",
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

    existing = session.query(Property).filter_by(platform=candidate.platform, platform_id=candidate.platform_id).one_or_none()
    if existing is not None:
        return _update_or_noop(session, existing, candidate)
    matched = _find_fuzzy_match(session, candidate, radius_m, text_threshold, area_tol, algorithm)
    if matched is not None:
        return _update_fuzzy_match(session, matched, candidate)
    return _create_property(session, candidate)


def _record_candidate_listings(session: Session, property_id: str, candidate: PropertyCandidate) -> None:
    listings = candidate.listings or []
    _upsert_listings(session, property_id, listings)
    if not listings:
        _record_price_change(session, property_id, candidate.price)


def _update_or_noop(session: Session, existing, candidate: PropertyCandidate) -> DedupeMatchResult:
    if _is_unchanged(session, existing, candidate):
        return DedupeMatchResult(property_id=str(existing.id), action="noop")
    for field in ("price", "title", "description", "image_urls", "props_json"):
        setattr(existing, field, getattr(candidate, field))
    existing.active = True
    _record_candidate_listings(session, str(existing.id), candidate)
    session.flush()
    return DedupeMatchResult(property_id=str(existing.id), action="updated")


def _find_fuzzy_match(session, candidate, radius_m, text_threshold, area_tol, algorithm):
    loc = candidate.location
    if not (loc and loc.get("lat") and loc.get("lon")):
        return None
    nearby = session.execute(text("""
        SELECT id, title, area_m2 FROM properties
        WHERE ST_DWithin(location::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
        AND active = true
    """), {"lat": loc["lat"], "lon": loc["lon"], "radius": radius_m}).fetchall()
    for row in nearby:
        area_close = not (candidate.area_m2 and row.area_m2) or abs(candidate.area_m2 - row.area_m2) <= area_tol
        if area_close and text_similarity(candidate.title, row.title, algorithm=algorithm) >= text_threshold:
            return row.id
    return None


def _update_fuzzy_match(session: Session, property_id, candidate: PropertyCandidate) -> DedupeMatchResult:
    from adapters.db.models import Property

    prop = session.get(Property, property_id)
    if prop is None:
        return _create_property(session, candidate)
    prop.price, prop.active = candidate.price, True
    prop.image_urls, prop.props_json = candidate.image_urls, candidate.props_json
    _record_candidate_listings(session, str(prop.id), candidate)
    session.flush()
    return DedupeMatchResult(property_id=str(prop.id), action="updated")


def _create_property(session: Session, candidate: PropertyCandidate) -> DedupeMatchResult:
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    from adapters.db.models import Property

    loc = candidate.location
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
    _record_candidate_listings(session, str(new_prop.id), candidate)
    session.flush()
    return DedupeMatchResult(property_id=str(new_prop.id), action="created")


def _is_unchanged(session: Session, existing, candidate: PropertyCandidate) -> bool:
    """Return True if the candidate data is identical to the existing property.

    Checks the fields that matter for AI enrichment and price history:
    price, title, description, and image_urls.
    """
    from adapters.db.models import PropertyListing

    if any((
        float(existing.price or 0) != float(candidate.price or 0),
        (existing.title or "") != (candidate.title or ""),
        (existing.description or "") != (candidate.description or ""),
        sorted(existing.image_urls or []) != sorted(candidate.image_urls or []),
    )):
        return False

    try:
        existing_listings = (
            session.query(PropertyListing)
            .filter(
                PropertyListing.property_id == existing.id,
                PropertyListing.active == True,   # noqa: E712
            )
            .all()
        )
    except Exception as exc:
        logger.warning("is_unchanged_db_error", property_id=str(existing.id), error=str(exc))
        return False  # Safe default: treat as changed, allow re-enrichment

    return _listings_prices_unchanged(existing_listings, candidate.listings or [])


def _listings_prices_unchanged(existing_listings, candidate_listings) -> bool:
    if existing_listings and not candidate_listings:
        return False
    candidate_map = {
        (cl.get("platform"), cl.get("platform_listing_id"), cl.get("listing_type")): float(cl.get("price", 0))
        for cl in candidate_listings
    }
    for el in existing_listings:
        key = (el.platform, el.platform_listing_id, el.listing_type)
        if key in candidate_map and float(el.price or 0) != candidate_map[key]:
            return False
    return True


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
            "WHERE property_id = :pid AND listing_type = :lt AND platform IS NOT DISTINCT FROM :platform "
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


def _prices_equal(a, b, tolerance=0.001) -> bool:
    """Safely compare two prices that may have gone through float/Decimal conversion."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < tolerance


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
    except Exception as exc:
        # watchlist table may not exist in test SQLite databases
        logger.warning("watchlist_query_error", property_id=str(property_id), error=str(exc))
        return

    if not rows:
        return

    for row in rows:
        min_drop_pct = float(row.min_drop_pct or 5.0)
        reference_price = row.last_notified_price or old_price

        # Calculate percentage drop
        if reference_price is None or float(reference_price) <= 0:
            continue

        reference_price_float = float(reference_price)
        drop_pct = ((reference_price_float - float(new_price)) / reference_price_float) * 100.0

        if drop_pct >= min_drop_pct and not _prices_equal(row.last_notified_price, new_price):
            # Fire alert asynchronously via Celery
            try:
                from adapters.queue.tasks import send_price_drop_alert

                alert_dict = {
                    "property_id": property_id,
                    "old_price": old_price,
                    "new_price": new_price,
                    "drop_pct": drop_pct,
                    "platform": platform,
                    "listing_type": listing_type,
                    "title": "Property",  # Fallback, should ideally fetch title
                }
                send_price_drop_alert.delay(alert_dict)

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
                    "condo_fee = :condo_fee, iptu = :iptu, base_price = :base_price, "
                    "raw_json = :raw_json, "
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
                    "base_price": listing.get("base_price"),
                    "raw_json": json.dumps(listing.get("raw_json") or {}),
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
                    "base_price, raw_json, first_seen, last_seen, active) "
                    "VALUES (:id, :pid, :platform, :plid, :lt, "
                    ":price, :currency, :url, :is_furnished, :accepts_pets, :condo_fee, :iptu, "
                    ":base_price, :raw_json, :now, :now, true)"
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
                    "base_price": listing.get("base_price"),
                    "raw_json": json.dumps(listing.get("raw_json") or {}),
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
