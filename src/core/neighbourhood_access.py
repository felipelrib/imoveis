"""Neighbourhood access / travel-time scoring to downtown hubs (BIN-90).

Scores are floats in ``[0.0, 1.0]`` (closer/faster → higher). Meta is nested
under ``quality_meta["access"]`` so parallel fill jobs do not wipe siblings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from core.neighbourhood_quality import normalize_quality_score

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class HubTravelResult:
    """Travel estimate from a neighbourhood representative point to one hub."""

    hub_id: str
    minutes: float
    distance_m: float
    mode: str
    provider: str
    label: str = ""


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def minutes_from_haversine(distance_m: float, avg_speed_kmh: float) -> float:
    """Convert a straight-line distance to estimated travel minutes."""
    if avg_speed_kmh <= 0:
        raise ValueError("avg_speed_kmh must be positive")
    return (float(distance_m) / 1000.0) / float(avg_speed_kmh) * 60.0


def access_score_from_minutes(
    minutes: Optional[float], max_minutes: float
) -> Optional[float]:
    """Map travel minutes to ``[0, 1]`` (0 at/over max, 1 at zero minutes)."""
    if minutes is None:
        return None
    try:
        mins = float(minutes)
        cap = float(max_minutes)
    except (TypeError, ValueError):
        return None
    if cap <= 0 or mins < 0:
        return None
    return normalize_quality_score(max(0.0, 1.0 - mins / cap))


def hubs_for_city(
    hubs_cfg: Mapping[str, Sequence[Any]], city: Optional[str]
) -> list[Any]:
    """Return hubs for ``city`` with case-insensitive key match (empty if none)."""
    if not city or not hubs_cfg:
        return []
    needle = str(city).strip().casefold()
    if not needle:
        return []
    for key, hubs in hubs_cfg.items():
        if str(key).strip().casefold() == needle:
            return list(hubs or [])
    return []


def pick_best_hub_result(
    results: Sequence[HubTravelResult],
) -> Optional[HubTravelResult]:
    """Pick the hub with the lowest travel minutes (ties: first)."""
    best: Optional[HubTravelResult] = None
    for result in results:
        if result.minutes < 0:
            continue
        if best is None or result.minutes < best.minutes:
            best = result
    return best


def merge_access_meta(
    existing_meta: Optional[Mapping[str, Any]],
    access_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge nested ``access`` into ``quality_meta`` without wiping siblings."""
    meta: dict[str, Any] = dict(existing_meta) if isinstance(existing_meta, Mapping) else {}
    meta["access"] = dict(access_payload)
    return meta


def access_meta_from_result(
    result: HubTravelResult,
    *,
    refreshed_at: Optional[str] = None,
) -> dict[str, Any]:
    """Build the nested ``quality_meta.access`` payload for a best-hub result."""
    ts = refreshed_at or datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "hub_id": result.hub_id,
        "minutes": round(float(result.minutes), 2),
        "distance_m": round(float(result.distance_m), 1),
        "mode": result.mode,
        "provider": result.provider,
        "refreshed_at": ts,
    }
    if result.label:
        payload["hub_label"] = result.label
    return payload


def estimate_hub_haversine(
    *,
    origin_lat: float,
    origin_lon: float,
    hub_id: str,
    hub_lat: float,
    hub_lon: float,
    mode: str,
    avg_speed_kmh: float,
    label: str = "",
) -> HubTravelResult:
    """Haversine fallback travel estimate to one hub."""
    distance_m = haversine_m(origin_lat, origin_lon, hub_lat, hub_lon)
    minutes = minutes_from_haversine(distance_m, avg_speed_kmh)
    return HubTravelResult(
        hub_id=hub_id,
        minutes=minutes,
        distance_m=distance_m,
        mode=mode,
        provider="haversine",
        label=label,
    )


RouteFn = Callable[
    [float, float, float, float],
    Optional[tuple[float, float]],
]
"""``(origin_lat, origin_lon, hub_lat, hub_lon) -> (minutes, distance_m) | None``."""


def travel_to_hubs(
    *,
    origin_lat: float,
    origin_lon: float,
    hubs: Sequence[Any],
    mode: str,
    avg_speed_kmh: float,
    route_fn: Optional[RouteFn] = None,
) -> list[HubTravelResult]:
    """Estimate travel to each hub; ``route_fn`` wins, else haversine fallback."""
    results: list[HubTravelResult] = []
    for hub in hubs:
        hub_id = str(getattr(hub, "id", "") or "").strip()
        if not hub_id:
            continue
        hub_lat = float(getattr(hub, "lat"))
        hub_lon = float(getattr(hub, "lon"))
        label = str(getattr(hub, "label", "") or "")
        provider = "haversine"
        minutes: Optional[float] = None
        distance_m: Optional[float] = None
        if route_fn is not None:
            routed = route_fn(origin_lat, origin_lon, hub_lat, hub_lon)
            if routed is not None:
                minutes, distance_m = float(routed[0]), float(routed[1])
                provider = "osrm"
        if minutes is None or distance_m is None:
            estimated = estimate_hub_haversine(
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                hub_id=hub_id,
                hub_lat=hub_lat,
                hub_lon=hub_lon,
                mode=mode,
                avg_speed_kmh=avg_speed_kmh,
                label=label,
            )
            results.append(estimated)
            continue
        results.append(
            HubTravelResult(
                hub_id=hub_id,
                minutes=minutes,
                distance_m=distance_m,
                mode=mode,
                provider=provider,
                label=label,
            )
        )
    return results
