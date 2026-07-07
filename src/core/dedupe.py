import logging
from dataclasses import dataclass
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
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
    existing = (
        session.query(Property)
        .filter_by(platform=candidate.platform, platform_id=candidate.platform_id)
        .one_or_none()
    )
    if existing is not None:
        # Update mutable fields
        existing.price = candidate.price
        existing.title = candidate.title
        existing.description = candidate.description
        existing.image_urls = candidate.image_urls
        existing.props_json = candidate.props_json
        existing.active = True
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
        nearby = session.execute(nearby_query, {
            "lat": lat, "lon": lon, "radius": radius_m
        }).fetchall()

        for row in nearby:
            title_sim = text_similarity(candidate.title, row.title)
            area_close = (
                abs((candidate.area_m2 or 0) - (row.area_m2 or 0)) <= area_tol
                if candidate.area_m2 and row.area_m2
                else True
            )
            if title_sim >= text_threshold and area_close:
                # Merge: update the matched property
                prop = session.get(Property, row.id)
                if prop:
                    prop.price = candidate.price
                    prop.active = True
                    prop.image_urls = candidate.image_urls
                    prop.props_json = candidate.props_json
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
    return DedupeMatchResult(property_id=str(new_prop.id), action="created")


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
        
        result = session.execute(query, {
            'lat': lat,
            'lon': lon,
            'radius': radius_m
        }).fetchall()
        
        candidates = []
        for row in result:
            candidates.append((row.lat, row.lon, row.address))
            
        logger.debug(f"Found {len(candidates)} candidates near ({lat}, {lon})")
        return candidates
        
    except Exception as e:
        logger.error(f"Error finding candidates: {e}")
        return []

