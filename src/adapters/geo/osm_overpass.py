"""HTTP Overpass client for amenity POIs (no vendor SDK)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import httpx
from shapely.geometry import Polygon

from core.osm_amenities import AmenityPOI
from infra.logging import get_logger

logger = get_logger(__name__)

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass QL fragments for amenity categories (node + way centroids via out center).
_OVERPASS_SELECTORS = (
    'node["shop"~"^(supermarket|convenience|mall|department_store|greengrocer)$"]({bbox});',
    'way["shop"~"^(supermarket|convenience|mall|department_store|greengrocer)$"]({bbox});',
    'node["amenity"="marketplace"]({bbox});',
    'way["amenity"="marketplace"]({bbox});',
    'node["leisure"~"^(park|garden)$"]({bbox});',
    'way["leisure"~"^(park|garden)$"]({bbox});',
    'node["landuse"="recreation_ground"]({bbox});',
    'way["landuse"="recreation_ground"]({bbox});',
    'node["amenity"~"^(school|kindergarten|university|college)$"]({bbox});',
    'way["amenity"~"^(school|kindergarten|university|college)$"]({bbox});',
    'node["amenity"~"^(hospital|clinic|pharmacy|doctors)$"]({bbox});',
    'way["amenity"~"^(hospital|clinic|pharmacy|doctors)$"]({bbox});',
)


def polygon_bbox(polygon: Polygon) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) for Overpass bbox syntax."""
    minx, miny, maxx, maxy = polygon.bounds
    return (float(miny), float(minx), float(maxy), float(maxx))


def build_overpass_query(polygon: Polygon) -> str:
    """Build an Overpass QL query for amenity POIs in the polygon bbox."""
    south, west, north, east = polygon_bbox(polygon)
    bbox = f"{south},{west},{north},{east}"
    selectors = "\n  ".join(s.replace("{bbox}", bbox) for s in _OVERPASS_SELECTORS)
    return (
        "[out:json][timeout:60];\n"
        "(\n"
        f"  {selectors}\n"
        ");\nout center tags;"
    )


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _read_cache(cache_dir: Path, key: str, ttl_hours: float) -> Optional[dict[str, Any]]:
    path = cache_dir / f"{key}.json"
    if not path.is_file():
        return None
    age_sec = time.time() - path.stat().st_mtime
    if age_sec > max(ttl_hours, 0) * 3600:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_cache(cache_dir: Path, key: str, payload: Mapping[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def parse_overpass_elements(payload: Mapping[str, Any]) -> list[AmenityPOI]:
    """Convert Overpass JSON elements into ``AmenityPOI`` rows."""
    elements = payload.get("elements")
    if not isinstance(elements, Sequence):
        return []
    pois: list[AmenityPOI] = []
    for el in elements:
        if not isinstance(el, Mapping):
            continue
        tags_raw = el.get("tags")
        tags: dict[str, str] = {}
        if isinstance(tags_raw, Mapping):
            for key, value in tags_raw.items():
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    tags[str(key)] = text
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            center = el.get("center")
            if isinstance(center, Mapping):
                lat = center.get("lat")
                lon = center.get("lon")
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        pois.append(AmenityPOI(lon=lon_f, lat=lat_f, tags=tags))
    return pois


class OverpassClient:
    """Thin Overpass HTTP client with rate-limit sleep and optional disk cache."""

    def __init__(
        self,
        *,
        url: str = DEFAULT_OVERPASS_URL,
        timeout_sec: float = 60.0,
        rate_limit_per_minute: float = 8.0,
        cache_dir: str | Path | None = None,
        cache_ttl_hours: float = 24.0,
        client: httpx.Client | None = None,
        sleep_fn=time.sleep,
    ):
        self.url = url
        self.timeout_sec = float(timeout_sec)
        self.rate_limit_per_minute = max(float(rate_limit_per_minute), 0.1)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl_hours = float(cache_ttl_hours)
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep_fn
        self._min_interval = 60.0 / self.rate_limit_per_minute
        self._last_request_at = 0.0

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OverpassClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_sec)
        return self._client

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            self._sleep(wait)

    def fetch_pois_for_polygon(self, polygon: Polygon) -> list[AmenityPOI]:
        """Query Overpass for amenity POIs near ``polygon`` (bbox)."""
        query = build_overpass_query(polygon)
        key = _cache_key(query)
        if self.cache_dir is not None:
            cached = _read_cache(self.cache_dir, key, self.cache_ttl_hours)
            if cached is not None:
                logger.info("overpass_cache_hit", cache_key=key[:12])
                return parse_overpass_elements(cached)

        self._throttle()
        logger.info("overpass_request", url=self.url)
        response = self._http().post(self.url, data={"data": query})
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Overpass response must be a JSON object")
        if self.cache_dir is not None:
            _write_cache(self.cache_dir, key, payload)
        return parse_overpass_elements(payload)
