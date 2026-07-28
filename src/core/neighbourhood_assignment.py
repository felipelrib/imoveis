"""Assign Properties to neighbourhoods via PostGIS spatial containment.

Named enrichment-pipeline stage (AD-10). Uses ST_Covers so boundary points
count as inside; properties outside all polygons get neighborhood_id = NULL
(props_json string neighbourhood remains the documented fallback).

When seller/platform coords are cleared after OLX location reconcile, name
assignment can still set ``neighborhood_id``. Optionally
``apply_neighbourhood_representative_point`` fills a low-precision pin from
``ST_PointOnSurface`` so spatial cohorts / map / later ST_Covers can run —
never street-level geocoding.
"""

from __future__ import annotations

import unicodedata
from typing import Optional, Tuple, Union
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

PropertyId = Union[str, UUID]

# Provenance stamps when location is derived from neighbourhood geometry (BIN-112).
LOCATION_SOURCE_NEIGHBOURHOOD = "neighbourhood_point_on_surface"
LOCATION_PRECISION_NEIGHBOURHOOD = "neighbourhood"


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def assign_property_neighbourhood(
    session: Session,
    property_id: PropertyId,
) -> Optional[UUID]:
    """Set Property.neighborhood_id from containing neighbourhood polygon.

    Args:
        session: Active SQLAlchemy session.
        property_id: Target property UUID.

    Returns:
        Assigned neighbourhood id, or None when unassigned / missing / no location.
        When location is null, leaves existing neighborhood_id unchanged and
        returns the current value (or None).
    """
    from adapters.db.models import Property

    prop = session.get(Property, property_id)
    if prop is None:
        return None

    if prop.location is None:
        return prop.neighborhood_id

    matched_id = session.execute(
        text(
            """
            SELECT n.id
            FROM neighborhoods n
            JOIN properties p ON p.id = :pid
            WHERE n.geometry IS NOT NULL
              AND p.location IS NOT NULL
              AND ST_Covers(n.geometry, p.location)
            ORDER BY n.name ASC
            LIMIT 1
            """
        ),
        {"pid": prop.id},
    ).scalar()

    prop.neighborhood_id = matched_id
    session.flush()
    return matched_id


def assign_property_neighbourhood_by_name(
    session: Session,
    property_id: PropertyId,
    *,
    name: str | None,
    city: str | None = None,
) -> Optional[UUID]:
    """Set ``neighborhood_id`` by folded name (+ optional city) match.

    Used when OLX seller coords were cleared after text-based location
    correction, so spatial ST_Covers cannot run.
    """
    from adapters.db.models import Property

    prop = session.get(Property, property_id)
    if prop is None or not name or not str(name).strip():
        return None

    rows = session.execute(
        text(
            """
            SELECT id, name, city
            FROM neighborhoods
            WHERE name IS NOT NULL
            """
        )
    ).fetchall()
    target = _fold(name)
    city_f = _fold(city) if city else ""
    matched: Optional[UUID] = None
    for row in rows:
        if _fold(row.name or "") != target:
            continue
        if city_f and row.city and _fold(row.city) != city_f:
            continue
        matched = row.id
        break

    if matched is not None:
        prop.neighborhood_id = matched
        session.flush()
    return matched


def apply_neighbourhood_representative_point(
    session: Session,
    property_id: PropertyId,
) -> Optional[Tuple[float, float]]:
    """Set ``properties.location`` from the matched neighbourhood polygon.

    Uses ``ST_PointOnSurface`` (guaranteed inside the polygon). Does **not**
    call an external geocoder — precision is neighbourhood-level only.

    Failure modes (returns None, leaves location unchanged):
    - missing property / no ``neighborhood_id``
    - neighbourhood row missing or ``geometry`` null

    On success stamps ``props_json.location_source`` /
    ``location_precision`` so consumers do not treat the pin as parcel-accurate.

    Returns:
        ``(lon, lat)`` when a point was written, else None.
    """
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    from adapters.db.models import Property

    prop = session.get(Property, property_id)
    if prop is None or prop.neighborhood_id is None:
        return None

    row = session.execute(
        text(
            """
            SELECT
                ST_X(ST_PointOnSurface(geometry)) AS lon,
                ST_Y(ST_PointOnSurface(geometry)) AS lat
            FROM neighborhoods
            WHERE id = :nid
              AND geometry IS NOT NULL
            """
        ),
        {"nid": prop.neighborhood_id},
    ).fetchone()
    if row is None or row.lon is None or row.lat is None:
        return None

    lon = float(row.lon)
    lat = float(row.lat)
    prop.location = from_shape(Point(lon, lat), srid=4326)
    props = dict(prop.props_json or {})
    props["location_source"] = LOCATION_SOURCE_NEIGHBOURHOOD
    props["location_precision"] = LOCATION_PRECISION_NEIGHBOURHOOD
    prop.props_json = props
    session.flush()
    return (lon, lat)


def load_neighborhood_names(
    session: Session,
    cities: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Return neighbourhood display names, optionally filtered by city."""
    if cities:
        folded = {_fold(c) for c in cities if c}
        rows = session.execute(text("SELECT name, city FROM neighborhoods")).fetchall()
        names = [
            row.name
            for row in rows
            if row.name and (not folded or (row.city and _fold(row.city) in folded))
        ]
    else:
        rows = session.execute(text("SELECT name FROM neighborhoods")).fetchall()
        names = [row.name for row in rows if row.name]
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = _fold(n)
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out
