"""Assign Properties to neighbourhoods via PostGIS spatial containment.

Named enrichment-pipeline stage (AD-10). Uses ST_Covers so boundary points
count as inside; properties outside all polygons get neighborhood_id = NULL
(props_json string neighbourhood remains the documented fallback).
"""

from __future__ import annotations

from typing import Optional, Union
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

PropertyId = Union[str, UUID]


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
