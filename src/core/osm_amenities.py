"""OSM amenity density scoring for neighbourhood polygons (BIN-88).

Pure helpers — no I/O. Counts classified POIs inside a polygon (optional
meter buffer) and maps category counts to an amenity score in ``[0, 1]``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from shapely.geometry import Point, Polygon, shape
from shapely.geometry.base import BaseGeometry

from core.neighbourhood_quality import normalize_quality_score

AMENITY_CATEGORIES: tuple[str, ...] = ("shop", "park", "school", "healthcare")

DEFAULT_CATEGORY_TARGETS: dict[str, float] = {
    "shop": 3.0,
    "park": 1.0,
    "school": 1.0,
    "healthcare": 2.0,
}

_SHOP_VALUES = frozenset(
    {"supermarket", "convenience", "mall", "department_store", "greengrocer"}
)
_PARK_LEISURE = frozenset({"park", "garden"})
_SCHOOL_AMENITY = frozenset({"school", "kindergarten", "university", "college"})
_HEALTH_AMENITY = frozenset({"hospital", "clinic", "pharmacy", "doctors"})


@dataclass(frozen=True)
class AmenityPOI:
    """A point of interest with OSM-style tags."""

    lon: float
    lat: float
    tags: Mapping[str, str]


def classify_amenity_tags(tags: Mapping[str, Any] | None) -> Optional[str]:
    """Map OSM tags / GeoJSON properties to a category, or ``None`` if ignored."""
    if not tags:
        return None
    normalized: dict[str, str] = {}
    for key, value in tags.items():
        if value is None:
            continue
        text = str(value).strip().lower()
        if text:
            normalized[str(key).strip().lower()] = text

    shop = normalized.get("shop")
    if shop in _SHOP_VALUES:
        return "shop"
    if normalized.get("amenity") == "marketplace":
        return "shop"

    leisure = normalized.get("leisure")
    if leisure in _PARK_LEISURE:
        return "park"
    if normalized.get("landuse") == "recreation_ground":
        return "park"

    amenity = normalized.get("amenity")
    if amenity in _SCHOOL_AMENITY:
        return "school"
    if amenity in _HEALTH_AMENITY:
        return "healthcare"

    # Pre-classified GeoJSON / fixture shortcut
    category = normalized.get("category")
    if category in AMENITY_CATEGORIES:
        return category
    return None


def classify_poi(poi: AmenityPOI) -> Optional[str]:
    """Classify a POI into an amenity category."""
    return classify_amenity_tags(poi.tags)


def _as_polygon(polygon: BaseGeometry | Mapping[str, Any] | Polygon) -> Polygon:
    if isinstance(polygon, Polygon):
        poly = polygon
    elif isinstance(polygon, Mapping):
        geom = shape(polygon)
        if not isinstance(geom, Polygon):
            raise TypeError(f"Expected Polygon geometry, got {geom.geom_type}")
        poly = geom
    elif isinstance(polygon, BaseGeometry):
        if not isinstance(polygon, Polygon):
            raise TypeError(f"Expected Polygon geometry, got {polygon.geom_type}")
        poly = polygon
    else:
        raise TypeError(f"Unsupported polygon type: {type(polygon)!r}")
    if poly.is_empty:
        raise ValueError("Polygon is empty")
    return poly


def buffer_polygon_meters(polygon: Polygon, buffer_m: float) -> Polygon:
    """Expand a WGS84 polygon by approximately ``buffer_m`` meters."""
    if buffer_m <= 0:
        return polygon
    lat = float(polygon.centroid.y)
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * max(math.cos(math.radians(lat)), 1e-6)
    # Use the smaller degree size so the buffer is at least buffer_m in both axes.
    deg = buffer_m / min(meters_per_deg_lat, meters_per_deg_lon)
    buffered = polygon.buffer(deg)
    if not isinstance(buffered, Polygon) or buffered.is_empty:
        return polygon
    return buffered


def empty_amenity_counts() -> dict[str, int]:
    """Zero counts for every amenity category."""
    return {name: 0 for name in AMENITY_CATEGORIES}


def count_amenities_by_category(
    pois: Sequence[AmenityPOI],
    polygon: BaseGeometry | Mapping[str, Any] | Polygon,
    buffer_m: float = 0.0,
) -> dict[str, int]:
    """Count classified POIs that fall inside ``polygon`` (+ optional buffer)."""
    poly = buffer_polygon_meters(_as_polygon(polygon), float(buffer_m or 0.0))
    counts = empty_amenity_counts()
    for poi in pois:
        category = classify_poi(poi)
        if category is None:
            continue
        point = Point(float(poi.lon), float(poi.lat))
        if poly.covers(point):
            counts[category] += 1
    return counts


def category_scores_from_counts(
    counts: Mapping[str, int],
    targets: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Per-category saturating scores in ``[0, 1]``."""
    tgt = dict(DEFAULT_CATEGORY_TARGETS)
    if targets:
        for key, value in targets.items():
            if key in AMENITY_CATEGORIES:
                try:
                    tgt[key] = float(value)
                except (TypeError, ValueError):
                    continue
    scores: dict[str, float] = {}
    for category in AMENITY_CATEGORIES:
        target = tgt.get(category, 1.0)
        if target <= 0:
            scores[category] = 0.0
            continue
        raw = float(counts.get(category, 0) or 0) / target
        scores[category] = min(1.0, max(0.0, raw))
    return scores


def score_from_counts(
    counts: Mapping[str, int],
    targets: Mapping[str, float] | None = None,
) -> float:
    """Mean of per-category saturating scores, clamped to ``[0, 1]``."""
    scores = category_scores_from_counts(counts, targets)
    if not scores:
        return 0.0
    mean = sum(scores.values()) / len(scores)
    normalized = normalize_quality_score(mean)
    return 0.0 if normalized is None else normalized


def build_amenity_quality_meta(
    counts: Mapping[str, int],
    *,
    mode: str,
    refreshed_at: str,
    category_scores: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build ``quality_meta`` fragment for an OSM amenity refresh."""
    scores = (
        dict(category_scores)
        if category_scores is not None
        else category_scores_from_counts(counts)
    )
    return {
        "source": "osm",
        "refreshed_at": refreshed_at,
        "mode": mode,
        "amenity_counts": {name: int(counts.get(name, 0) or 0) for name in AMENITY_CATEGORIES},
        "amenity_category_scores": {
            name: float(scores.get(name, 0.0)) for name in AMENITY_CATEGORIES
        },
    }


def merge_amenity_quality_meta(
    existing: Mapping[str, Any] | None,
    amenity_meta: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge OSM amenity fields into existing ``quality_meta`` (preserve other keys)."""
    merged: dict[str, Any] = dict(existing) if isinstance(existing, Mapping) else {}
    merged.update(dict(amenity_meta))
    return merged
