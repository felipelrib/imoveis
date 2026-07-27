"""OSRM routing client for neighbourhood access scoring (BIN-90)."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

import httpx


def _profile_for_mode(mode: str) -> str:
    normalized = (mode or "driving").strip().lower()
    if normalized in {"driving", "car"}:
        return "driving"
    if normalized in {"walking", "foot"}:
        return "walking"
    if normalized in {"cycling", "bike"}:
        return "cycling"
    return "driving"


class OsrmClient:
    """Thin httpx wrapper around OSRM ``/route/v1/{profile}/…``.

    Returns ``(minutes, distance_m)`` or ``None`` on soft failure so callers
    can fall back to haversine without raising.
    """

    def __init__(
        self,
        base_url: str,
        *,
        mode: str = "driving",
        timeout_sec: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/") + "/"
        self.mode = mode
        self.timeout_sec = float(timeout_sec)
        self._client = client
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OsrmClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout_sec,
                follow_redirects=True,
            )
        return self._client

    def route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
    ) -> Optional[tuple[float, float]]:
        """Return ``(minutes, distance_m)`` or ``None`` if routing fails."""
        if not self.base_url.strip("/"):
            return None
        profile = _profile_for_mode(self.mode)
        # OSRM expects lon,lat order
        coords = f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
        path = f"route/v1/{profile}/{coords}"
        url = urljoin(self.base_url, path)
        try:
            response = self._get_client().get(
                url,
                params={"overview": "false"},
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict) or payload.get("code") != "Ok":
            return None
        routes = payload.get("routes") or []
        if not routes:
            return None
        first = routes[0] or {}
        try:
            duration_sec = float(first["duration"])
            distance_m = float(first["distance"])
        except (KeyError, TypeError, ValueError):
            return None
        if duration_sec < 0 or distance_m < 0:
            return None
        return (duration_sec / 60.0, distance_m)
