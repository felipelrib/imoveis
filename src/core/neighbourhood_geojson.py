"""Load neighbourhood polygons from a vendor-agnostic GeoJSON FeatureCollection.

Idempotent upsert keyed by (name, city, state). Coordinates are treated as
WGS84 and written as PostGIS POLYGON SRID 4326.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Union

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

GeoJsonInput = Union[str, Path, Mapping[str, Any]]


@dataclass(frozen=True)
class NeighbourhoodPolygon:
    name: str
    city: str
    state: str
    polygon: Polygon


@dataclass(frozen=True)
class LoadResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.skipped


class NeighbourhoodGeoJSONError(ValueError):
    """Invalid or incomplete neighbourhood GeoJSON."""


def _as_mapping(data: GeoJsonInput) -> Mapping[str, Any]:
    if isinstance(data, (str, Path)):
        path = Path(data)
        with path.open(encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, Mapping):
            raise NeighbourhoodGeoJSONError("GeoJSON root must be an object")
        return loaded
    return data


def _polygon_from_geometry(geom: BaseGeometry) -> Polygon:
    if isinstance(geom, Polygon):
        poly = geom
    elif isinstance(geom, MultiPolygon):
        if geom.is_empty or len(geom.geoms) == 0:
            raise NeighbourhoodGeoJSONError("MultiPolygon is empty")
        poly = max(geom.geoms, key=lambda g: g.area)
    else:
        raise NeighbourhoodGeoJSONError(
            f"Unsupported geometry type {geom.geom_type!r}; expected Polygon or MultiPolygon"
        )

    if poly.is_empty:
        raise NeighbourhoodGeoJSONError("Polygon is empty")
    if not poly.is_valid:
        poly = poly.buffer(0)
        if not isinstance(poly, Polygon) or poly.is_empty or not poly.is_valid:
            raise NeighbourhoodGeoJSONError("Polygon is not valid")
    # Ensure exterior ring is closed (GeoJSON may omit duplicate closing point)
    coords = list(poly.exterior.coords)
    if len(coords) < 4:
        raise NeighbourhoodGeoJSONError("Polygon exterior ring needs at least 4 positions")
    if coords[0] != coords[-1]:
        coords.append(coords[0])
        poly = Polygon(coords, [list(r.coords) for r in poly.interiors])
    return poly


def parse_feature_collection(
    data: GeoJsonInput,
    *,
    default_city: str = "Belo Horizonte",
    default_state: str = "MG",
) -> list[NeighbourhoodPolygon]:
    """Parse a FeatureCollection into neighbourhood polygon rows."""
    root = _as_mapping(data)
    if root.get("type") != "FeatureCollection":
        raise NeighbourhoodGeoJSONError("Root type must be FeatureCollection")
    features = root.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)):
        raise NeighbourhoodGeoJSONError("features must be an array")

    rows: list[NeighbourhoodPolygon] = []
    for idx, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise NeighbourhoodGeoJSONError(f"Feature at index {idx} must be an object")
        if feature.get("type") != "Feature":
            raise NeighbourhoodGeoJSONError(f"Feature at index {idx} type must be Feature")
        props = feature.get("properties") or {}
        if not isinstance(props, Mapping):
            raise NeighbourhoodGeoJSONError(f"Feature at index {idx} properties must be an object")
        name = props.get("name")
        if not name or not str(name).strip():
            raise NeighbourhoodGeoJSONError(f"Feature at index {idx} is missing properties.name")
        city = str(props.get("city") or default_city).strip()
        state = str(props.get("state") or default_state).strip().upper()
        if len(state) != 2:
            raise NeighbourhoodGeoJSONError(
                f"Feature at index {idx} state must be a 2-letter code, got {state!r}"
            )
        geom_raw = feature.get("geometry")
        if not geom_raw:
            raise NeighbourhoodGeoJSONError(f"Feature at index {idx} is missing geometry")
        try:
            geom = shape(geom_raw)
        except Exception as exc:  # shapely raises assorted errors
            raise NeighbourhoodGeoJSONError(
                f"Feature at index {idx} has invalid geometry: {exc}"
            ) from exc
        polygon = _polygon_from_geometry(geom)
        rows.append(
            NeighbourhoodPolygon(
                name=str(name).strip(),
                city=city,
                state=state,
                polygon=polygon,
            )
        )
    return rows


def _geometry_equals(session: Session, existing, polygon: Polygon) -> bool:
    """True when stored geometry equals the candidate (PostGIS ST_Equals)."""
    if existing.geometry is None:
        return False
    from sqlalchemy import text

    return bool(
        session.execute(
            text(
                "SELECT ST_Equals(geometry, ST_SetSRID(ST_GeomFromText(:wkt), 4326)) "
                "FROM neighborhoods WHERE id = :id"
            ),
            {"wkt": polygon.wkt, "id": existing.id},
        ).scalar()
    )


def upsert_neighbourhoods(session: Session, rows: Sequence[NeighbourhoodPolygon]) -> LoadResult:
    """Insert or update neighbourhood geometries. Idempotent on (name, city, state)."""
    from adapters.db.models import Neighborhood
    from geoalchemy2.shape import from_shape

    inserted = updated = skipped = 0
    for row in rows:
        existing = (
            session.query(Neighborhood)
            .filter_by(name=row.name, city=row.city, state=row.state)
            .one_or_none()
        )
        wkb = from_shape(row.polygon, srid=4326)
        if existing is None:
            session.add(
                Neighborhood(
                    name=row.name,
                    city=row.city,
                    state=row.state,
                    geometry=wkb,
                )
            )
            session.flush()
            inserted += 1
            continue

        if _geometry_equals(session, existing, row.polygon):
            skipped += 1
            continue
        existing.geometry = wkb
        session.flush()
        updated += 1

    return LoadResult(inserted=inserted, updated=updated, skipped=skipped)


def load_neighbourhood_geojson(
    session: Session,
    data: GeoJsonInput,
    *,
    default_city: str = "Belo Horizonte",
    default_state: str = "MG",
) -> LoadResult:
    """Parse + upsert in one call."""
    rows = parse_feature_collection(
        data, default_city=default_city, default_state=default_state
    )
    return upsert_neighbourhoods(session, rows)


def neighbourhood_to_geojson_feature(row: NeighbourhoodPolygon) -> dict[str, Any]:
    """Helper for dry-run / debugging."""
    return {
        "type": "Feature",
        "properties": {"name": row.name, "city": row.city, "state": row.state},
        "geometry": mapping(row.polygon),
    }
