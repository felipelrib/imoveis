"""Assign Properties to neighbourhoods via PostGIS spatial containment.

Named enrichment-pipeline stage (AD-10). Uses ST_Covers so boundary points
count as inside; properties outside all polygons get neighborhood_id = NULL
(props_json string neighbourhood remains the documented fallback).
"""

from __future__ import annotations

import unicodedata
from typing import Optional, Union
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

PropertyId = Union[str, UUID]


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
