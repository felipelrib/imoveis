"""Refresh neighbourhood amenity_score from OSM POIs (BIN-88)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from geoalchemy2.shape import to_shape
from shapely.geometry import Polygon
from sqlalchemy.orm import Session

from adapters.db.models import Neighborhood
from adapters.geo.osm_overpass import OverpassClient
from adapters.geo.osm_poi_loader import load_pois_from_geojson
from core.osm_amenities import (
    AmenityPOI,
    build_amenity_quality_meta,
    category_scores_from_counts,
    count_amenities_by_category,
    merge_amenity_quality_meta,
    score_from_counts,
)
from infra.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AmenityRefreshResult:
    status: str
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    mode: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "mode": self.mode,
        }


def _polygon_from_row(geometry: Any) -> Optional[Polygon]:
    if geometry is None:
        return None
    try:
        geom = to_shape(geometry)
    except Exception:
        return None
    if isinstance(geom, Polygon) and not geom.is_empty:
        return geom
    return None


def _load_pois_for_mode(
    *,
    mode: str,
    poi_geojson_path: str,
    overpass: OverpassClient | None,
    polygon: Polygon,
    shared_pois: Sequence[AmenityPOI] | None,
) -> list[AmenityPOI]:
    if mode == "geojson":
        if shared_pois is None:
            raise ValueError("geojson mode requires poi_geojson_path")
        return list(shared_pois)
    if mode == "overpass":
        if overpass is None:
            raise ValueError("overpass mode requires OverpassClient")
        return overpass.fetch_pois_for_polygon(polygon)
    raise ValueError(f"Unsupported osm amenities mode: {mode!r}")


def refresh_neighbourhood_amenities(
    session: Session,
    *,
    mode: str,
    poi_geojson_path: str = "",
    buffer_m: float = 0.0,
    category_targets: Mapping[str, float] | None = None,
    batch_size: int = 50,
    overpass_url: str = "https://overpass-api.de/api/interpreter",
    request_timeout_sec: float = 60.0,
    rate_limit_per_minute: float = 8.0,
    cache_dir: str = "",
    cache_ttl_hours: float = 24.0,
    overpass_client: OverpassClient | None = None,
    neighborhood_ids: Sequence[UUID] | None = None,
    now: datetime | None = None,
) -> AmenityRefreshResult:
    """Score neighbourhoods from OSM POIs and persist amenity_score + quality_meta."""
    mode_norm = (mode or "").strip().lower()
    if mode_norm not in ("geojson", "overpass"):
        logger.warning("amenity_refresh_bad_mode", mode=mode)
        return AmenityRefreshResult(status="error", mode=mode_norm, errors=1)

    refreshed_at = (now or datetime.now(timezone.utc)).isoformat()
    shared_pois: list[AmenityPOI] | None = None
    if mode_norm == "geojson":
        path = (poi_geojson_path or "").strip()
        if not path:
            logger.warning("amenity_refresh_missing_geojson_path")
            return AmenityRefreshResult(status="error", mode=mode_norm, errors=1)
        shared_pois = load_pois_from_geojson(path)

    query = session.query(Neighborhood).filter(Neighborhood.geometry.isnot(None))
    if neighborhood_ids:
        query = query.filter(Neighborhood.id.in_(list(neighborhood_ids)))
    query = query.order_by(Neighborhood.name.asc()).limit(max(int(batch_size), 1))
    rows = list(query.all())
    if not rows:
        return AmenityRefreshResult(status="empty", mode=mode_norm)

    owns_client = False
    client = overpass_client
    if mode_norm == "overpass" and client is None:
        client = OverpassClient(
            url=overpass_url,
            timeout_sec=request_timeout_sec,
            rate_limit_per_minute=rate_limit_per_minute,
            cache_dir=cache_dir or None,
            cache_ttl_hours=cache_ttl_hours,
        )
        owns_client = True

    updated = 0
    skipped = 0
    errors = 0
    try:
        for row in rows:
            poly = _polygon_from_row(row.geometry)
            if poly is None:
                skipped += 1
                continue
            try:
                pois = _load_pois_for_mode(
                    mode=mode_norm,
                    poi_geojson_path=poi_geojson_path,
                    overpass=client,
                    polygon=poly,
                    shared_pois=shared_pois,
                )
                counts = count_amenities_by_category(pois, poly, buffer_m=buffer_m)
                scores = category_scores_from_counts(counts, category_targets)
                amenity_score = score_from_counts(counts, category_targets)
                meta_fragment = build_amenity_quality_meta(
                    counts,
                    mode=mode_norm,
                    refreshed_at=refreshed_at,
                    category_scores=scores,
                )
                row.amenity_score = amenity_score
                row.quality_meta = merge_amenity_quality_meta(row.quality_meta, meta_fragment)
                updated += 1
            except Exception:
                errors += 1
                logger.exception(
                    "amenity_refresh_neighbourhood_failed",
                    neighborhood_id=str(row.id),
                    name=row.name,
                )
        session.commit()
    finally:
        if owns_client and client is not None:
            client.close()

    status = "ok" if errors == 0 else ("partial" if updated else "error")
    logger.info(
        "amenity_refresh_done",
        status=status,
        updated=updated,
        skipped=skipped,
        errors=errors,
        mode=mode_norm,
    )
    return AmenityRefreshResult(
        status=status,
        updated=updated,
        skipped=skipped,
        errors=errors,
        mode=mode_norm,
    )
