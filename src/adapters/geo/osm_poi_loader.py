"""Load amenity POIs from a GeoJSON FeatureCollection (offline OSM extract)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence, Union

from core.osm_amenities import AmenityPOI

GeoJsonInput = Union[str, Path, Mapping[str, Any]]


class OsmPoiGeoJSONError(ValueError):
    """Invalid or incomplete amenity POI GeoJSON."""


def _as_mapping(data: GeoJsonInput) -> Mapping[str, Any]:
    if isinstance(data, (str, Path)):
        path = Path(data)
        with path.open(encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, Mapping):
            raise OsmPoiGeoJSONError("GeoJSON root must be an object")
        return loaded
    return data


def _tags_from_properties(props: Mapping[str, Any] | None) -> dict[str, str]:
    if not props:
        return {}
    out: dict[str, str] = {}
    for key, value in props.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[str(key)] = text
    return out


def parse_poi_feature_collection(data: GeoJsonInput) -> list[AmenityPOI]:
    """Parse Point features into ``AmenityPOI`` rows (skips non-Point geometries)."""
    root = _as_mapping(data)
    features = root.get("features")
    if not isinstance(features, Sequence):
        raise OsmPoiGeoJSONError("GeoJSON must be a FeatureCollection with features[]")

    pois: list[AmenityPOI] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        geom = feature.get("geometry")
        if not isinstance(geom, Mapping):
            continue
        if str(geom.get("type", "")).lower() != "point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, Sequence) or len(coords) < 2:
            continue
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError):
            continue
        props = feature.get("properties")
        tags = _tags_from_properties(props if isinstance(props, Mapping) else None)
        pois.append(AmenityPOI(lon=lon, lat=lat, tags=tags))
    return pois


def load_pois_from_geojson(path: str | Path) -> list[AmenityPOI]:
    """Load amenity POIs from a GeoJSON file path."""
    return parse_poi_feature_collection(path)
