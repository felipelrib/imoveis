"""Idempotent persistence for transit stop geometry (BIN-118).

Upserts GTFS/OSM stops into ``transit_stops`` keyed by ``(source, external_id)``.
When a parse has no ``stop_id``, synthesize one from rounded lon/lat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy.orm import Session

from core.transit_proximity import TransitStop, haversine_m

# Treat points within this distance as unchanged (GPS / float noise).
_UNCHANGED_DISTANCE_M = 1.0


@dataclass(frozen=True)
class LoadResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.skipped


def external_id_for(stop: TransitStop) -> str:
    """Natural key within a source; synthesize lon:lat when stop_id is missing."""
    if stop.stop_id and str(stop.stop_id).strip():
        return str(stop.stop_id).strip()
    return f"{stop.lon:.5f}:{stop.lat:.5f}"


def _location_unchanged(existing_location: object, lon: float, lat: float) -> bool:
    try:
        pt = to_shape(existing_location)
    except Exception:
        return False
    if not isinstance(pt, Point) or pt.is_empty:
        return False
    return haversine_m(float(pt.x), float(pt.y), lon, lat) < _UNCHANGED_DISTANCE_M


def _row_unchanged(row: object, stop: TransitStop) -> bool:
    if str(getattr(row, "name", "")) != stop.name:
        return False
    if str(getattr(row, "mode", "")) != stop.mode:
        return False
    return _location_unchanged(getattr(row, "location", None), stop.lon, stop.lat)


def upsert_transit_stops(
    session: Session,
    stops: Sequence[TransitStop],
) -> LoadResult:
    """Insert or update stop rows. Idempotent on ``(source, external_id)``."""
    from adapters.db.models import TransitStopRecord

    inserted = updated = skipped = 0
    for stop in stops:
        ext_id = external_id_for(stop)
        existing = (
            session.query(TransitStopRecord)
            .filter_by(source=stop.source, external_id=ext_id)
            .one_or_none()
        )
        wkb = from_shape(Point(stop.lon, stop.lat), srid=4326)
        if existing is None:
            session.add(
                TransitStopRecord(
                    source=stop.source,
                    external_id=ext_id,
                    name=stop.name,
                    mode=stop.mode,
                    location=wkb,
                )
            )
            session.flush()
            inserted += 1
            continue

        if _row_unchanged(existing, stop):
            skipped += 1
            continue

        existing.name = stop.name
        existing.mode = stop.mode
        existing.location = wkb
        session.flush()
        updated += 1

    return LoadResult(inserted=inserted, updated=updated, skipped=skipped)


def stops_from_db(session: Session) -> list[TransitStop]:
    """Load persisted stops as in-memory scoring DTOs."""
    from adapters.db.models import TransitStopRecord

    out: list[TransitStop] = []
    for row in session.query(TransitStopRecord).order_by(
        TransitStopRecord.source.asc(),
        TransitStopRecord.external_id.asc(),
    ):
        pt = to_shape(row.location)
        if not isinstance(pt, Point) or pt.is_empty:
            continue
        out.append(
            TransitStop(
                lon=float(pt.x),
                lat=float(pt.y),
                mode=str(row.mode),
                name=str(row.name),
                source=str(row.source),
                stop_id=str(row.external_id),
            )
        )
    return out
