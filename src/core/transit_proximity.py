"""Transit proximity scoring from GTFS / OSM stop files (BIN-89).

Offline-first: parse stop points from exported files, score each neighbourhood
centroid with config-driven radii and mode weights, then write
``neighborhoods.transit_score`` + ``quality_meta["transit"]``.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Union

from shapely.geometry import Point, Polygon, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

GeoJsonInput = Union[str, Path, Mapping[str, Any]]
TransitMode = str  # metro | brt | rail | bus | other

_EARTH_RADIUS_M = 6_371_000.0

# GTFS route_type → mode (https://gtfs.org/schedule/reference/#routestxt)
_GTFS_ROUTE_TYPE_MODE: dict[int, TransitMode] = {
    0: "brt",  # tram / light rail — treat as high-capacity corridor
    1: "metro",
    2: "rail",
    3: "bus",
    5: "brt",  # cable tram / similar
}


@dataclass(frozen=True)
class TransitStop:
    lon: float
    lat: float
    mode: TransitMode
    name: str
    source: str
    stop_id: str | None = None


@dataclass(frozen=True)
class NeighbourhoodTransitScore:
    neighborhood_id: Any
    transit_score: float
    meta: dict[str, Any]


@dataclass(frozen=True)
class TransitScoreParams:
    """Scoring knobs (mirrors NeighbourhoodTransitConfig)."""

    count_radius_m: float = 400.0
    max_radius_m: float = 1200.0
    nearest_weight: float = 0.7
    density_weight: float = 0.3
    density_cap: float = 8.0
    mode_weights: Mapping[str, float] | None = None

    def weight_for(self, mode: str) -> float:
        weights = self.mode_weights or {
            "metro": 1.0,
            "brt": 0.9,
            "rail": 0.85,
            "bus": 0.55,
            "other": 0.4,
        }
        return float(weights.get(mode, weights.get("other", 0.4)))


class TransitProximityError(ValueError):
    """Invalid transit stop input."""


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters between two WGS84 positions."""
    rlon1, rlat1, rlon2, rlat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    dlon = rlon2 - rlon1
    dlat = rlat2 - rlat1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def gtfs_route_type_to_mode(route_type: int) -> TransitMode:
    return _GTFS_ROUTE_TYPE_MODE.get(int(route_type), "other")


def infer_osm_mode(props: Mapping[str, Any]) -> TransitMode:
    """Infer mode from explicit properties.mode or common OSM tags."""
    explicit = props.get("mode")
    if explicit and str(explicit).strip():
        mode = str(explicit).strip().lower()
        if mode in {"metro", "brt", "rail", "bus", "other"}:
            return mode
    railway = str(props.get("railway") or "").lower()
    if railway in {"station", "subway_entrance", "halt"}:
        return "metro" if railway != "halt" else "rail"
    if railway in {"tram_stop", "tram"}:
        return "brt"
    highway = str(props.get("highway") or "").lower()
    if highway == "bus_stop":
        return "bus"
    pt = str(props.get("public_transport") or "").lower()
    if pt in {"station", "stop_position", "platform"}:
        if railway:
            return "metro"
        return "bus"
    return "other"


def _read_gtfs_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _gtfs_stop_modes(gtfs_dir: Path) -> dict[str, TransitMode]:
    """Best (highest-capacity) mode per stop_id when route files exist."""
    routes_path = gtfs_dir / "routes.txt"
    trips_path = gtfs_dir / "trips.txt"
    times_path = gtfs_dir / "stop_times.txt"
    if not (routes_path.is_file() and trips_path.is_file() and times_path.is_file()):
        return {}

    route_mode: dict[str, TransitMode] = {}
    for row in _read_gtfs_csv(routes_path):
        rid = row.get("route_id")
        if not rid:
            continue
        try:
            rtype = int(row.get("route_type") or "3")
        except ValueError:
            rtype = 3
        route_mode[rid] = gtfs_route_type_to_mode(rtype)

    trip_route: dict[str, str] = {}
    for row in _read_gtfs_csv(trips_path):
        tid = row.get("trip_id")
        rid = row.get("route_id")
        if tid and rid:
            trip_route[tid] = rid

    # Prefer higher-capacity modes when a stop serves multiple routes.
    mode_rank = {"metro": 5, "brt": 4, "rail": 3, "bus": 2, "other": 1}
    stop_modes: dict[str, TransitMode] = {}
    for row in _read_gtfs_csv(times_path):
        sid = row.get("stop_id")
        tid = row.get("trip_id")
        if not sid or not tid:
            continue
        rid = trip_route.get(tid)
        if not rid:
            continue
        mode = route_mode.get(rid, "bus")
        prev = stop_modes.get(sid)
        if prev is None or mode_rank.get(mode, 0) > mode_rank.get(prev, 0):
            stop_modes[sid] = mode
    return stop_modes


def parse_gtfs_stops(gtfs_dir: str | Path, *, default_mode: TransitMode = "bus") -> list[TransitStop]:
    """Parse ``stops.txt`` (and optional route/trip/stop_times for modes)."""
    directory = Path(gtfs_dir)
    stops_path = directory / "stops.txt" if directory.is_dir() else directory
    if not stops_path.is_file():
        raise TransitProximityError(f"GTFS stops.txt not found at {stops_path}")
    gtfs_root = stops_path.parent
    stop_modes = _gtfs_stop_modes(gtfs_root)

    stops: list[TransitStop] = []
    for row in _read_gtfs_csv(stops_path):
        sid = row.get("stop_id") or None
        try:
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TransitProximityError(f"Invalid stop lat/lon in stops.txt: {row}") from exc
        name = row.get("stop_name") or sid or "unnamed"
        mode = stop_modes.get(sid or "", default_mode) if sid else default_mode
        if not stop_modes:
            mode = default_mode
        stops.append(
            TransitStop(
                lon=lon,
                lat=lat,
                mode=mode,
                name=name,
                source="gtfs",
                stop_id=sid,
            )
        )
    return stops


def _as_geojson_mapping(data: GeoJsonInput) -> Mapping[str, Any]:
    if isinstance(data, (str, Path)):
        path = Path(data)
        with path.open(encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, Mapping):
            raise TransitProximityError("GeoJSON root must be an object")
        return loaded
    return data


def parse_osm_transit_geojson(data: GeoJsonInput) -> list[TransitStop]:
    """Parse Point FeatureCollection of transit stops (OSM export style)."""
    root = _as_geojson_mapping(data)
    if root.get("type") != "FeatureCollection":
        raise TransitProximityError("Root type must be FeatureCollection")
    features = root.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)):
        raise TransitProximityError("features must be an array")

    stops: list[TransitStop] = []
    for idx, feature in enumerate(features):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise TransitProximityError(f"Feature at index {idx} must be a Feature object")
        props = feature.get("properties") or {}
        if not isinstance(props, Mapping):
            raise TransitProximityError(f"Feature at index {idx} properties must be an object")
        geom_raw = feature.get("geometry")
        if not geom_raw:
            raise TransitProximityError(f"Feature at index {idx} is missing geometry")
        try:
            geom = shape(geom_raw)
        except Exception as exc:
            raise TransitProximityError(
                f"Feature at index {idx} has invalid geometry: {exc}"
            ) from exc
        if not isinstance(geom, Point) or geom.is_empty:
            raise TransitProximityError(
                f"Feature at index {idx} must be a Point; got {geom.geom_type!r}"
            )
        name = str(props.get("name") or f"stop-{idx}").strip()
        stops.append(
            TransitStop(
                lon=float(geom.x),
                lat=float(geom.y),
                mode=infer_osm_mode(props),
                name=name,
                source="osm",
                stop_id=str(props.get("id") or props.get("osm_id") or "") or None,
            )
        )
    return stops


def merge_stops(*groups: Iterable[TransitStop]) -> list[TransitStop]:
    """Concatenate stop lists (no dedupe — callers may pass overlapping sources)."""
    out: list[TransitStop] = []
    for group in groups:
        out.extend(group)
    return out


def score_centroid(
    lon: float,
    lat: float,
    stops: Sequence[TransitStop],
    params: TransitScoreParams | None = None,
    *,
    provider: str = "gtfs+osm",
    refreshed_at: str | None = None,
) -> tuple[float, dict[str, Any]]:
    """Score a single point; returns (transit_score, quality_meta.transit)."""
    cfg = params or TransitScoreParams()
    when = refreshed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    nearest_m: float | None = None
    nearest_mode: str | None = None
    nearest_term = 0.0
    density_sum = 0.0
    mode_counts: dict[str, int] = {}
    in_count_radius = 0

    for stop in stops:
        dist = haversine_m(lon, lat, stop.lon, stop.lat)
        if dist > cfg.max_radius_m:
            continue
        w = cfg.weight_for(stop.mode)
        proximity = max(0.0, 1.0 - dist / cfg.max_radius_m) * w
        if proximity > nearest_term:
            nearest_term = proximity
            nearest_m = dist
            nearest_mode = stop.mode
        if dist <= cfg.count_radius_m:
            density_sum += w
            in_count_radius += 1
            mode_counts[stop.mode] = mode_counts.get(stop.mode, 0) + 1

    if nearest_m is None:
        meta = {
            "provider": provider,
            "refreshed_at": when,
            "nearest_m": None,
            "nearest_mode": None,
            "count_radius_m": cfg.count_radius_m,
            "stop_count": 0,
            "mode_counts": {},
        }
        return 0.0, meta

    density = min(1.0, density_sum / max(cfg.density_cap, 1e-9))
    score = cfg.nearest_weight * nearest_term + cfg.density_weight * density
    score = max(0.0, min(1.0, score))
    meta = {
        "provider": provider,
        "refreshed_at": when,
        "nearest_m": round(nearest_m, 1),
        "nearest_mode": nearest_mode,
        "count_radius_m": cfg.count_radius_m,
        "stop_count": in_count_radius,
        "mode_counts": mode_counts,
    }
    return score, meta


def score_polygon(
    polygon: Polygon | BaseGeometry,
    stops: Sequence[TransitStop],
    params: TransitScoreParams | None = None,
    **kwargs: Any,
) -> tuple[float, dict[str, Any]]:
    """Score using the polygon centroid."""
    if polygon.is_empty:
        raise TransitProximityError("Cannot score empty polygon")
    centroid = polygon.centroid
    return score_centroid(centroid.x, centroid.y, stops, params, **kwargs)


def params_from_config(cfg: Any | None = None) -> TransitScoreParams:
    """Build scoring params from AppConfig.neighbourhood_quality.transit."""
    if cfg is None:
        from infra.config import get_config

        cfg = get_config()
    transit = cfg.neighbourhood_quality.transit
    return TransitScoreParams(
        count_radius_m=transit.count_radius_m,
        max_radius_m=transit.max_radius_m,
        nearest_weight=transit.nearest_weight,
        density_weight=transit.density_weight,
        density_cap=transit.density_cap,
        mode_weights=dict(transit.mode_weights),
    )


def apply_transit_scores(
    session: Session,
    scores: Sequence[NeighbourhoodTransitScore],
) -> int:
    """Write transit_score + merge quality_meta['transit'] for each neighbourhood."""
    from adapters.db.models import Neighborhood

    updated = 0
    for item in scores:
        row = session.get(Neighborhood, item.neighborhood_id)
        if row is None:
            continue
        row.transit_score = float(item.transit_score)
        meta = dict(row.quality_meta) if isinstance(row.quality_meta, dict) else {}
        meta["transit"] = dict(item.meta)
        row.quality_meta = meta
        updated += 1
    session.flush()
    return updated


def score_neighbourhood_rows(
    rows: Sequence[tuple[Any, Polygon]],
    stops: Sequence[TransitStop],
    params: TransitScoreParams | None = None,
    *,
    provider: str = "gtfs+osm",
) -> list[NeighbourhoodTransitScore]:
    """Score (id, polygon) pairs."""
    when = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out: list[NeighbourhoodTransitScore] = []
    for nid, polygon in rows:
        score, meta = score_polygon(
            polygon, stops, params, provider=provider, refreshed_at=when
        )
        out.append(
            NeighbourhoodTransitScore(
                neighborhood_id=nid, transit_score=score, meta=meta
            )
        )
    return out
