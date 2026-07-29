"""Refresh neighbourhood transit_score from GTFS/OSM files + persist stops (BIN-118)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from adapters.db.models import Neighborhood
from core.gtfs_headways import (
    StopHeadway,
    merge_stop_headways,
    parse_gtfs_stop_headways,
)
from core.transit_proximity import (
    TransitProximityError,
    apply_transit_scores,
    merge_stops,
    params_from_config,
    parse_gtfs_stops,
    parse_osm_transit_geojson,
    score_neighbourhood_rows,
)
from core.transit_stops import LoadResult, stops_from_db, upsert_transit_stops
from infra.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TransitRefreshResult:
    status: str
    neighbourhoods_updated: int = 0
    stops_inserted: int = 0
    stops_updated: int = 0
    stops_skipped: int = 0
    stops_loaded: int = 0
    provider: str = ""
    mode: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "neighbourhoods_updated": self.neighbourhoods_updated,
            "stops_inserted": self.stops_inserted,
            "stops_updated": self.stops_updated,
            "stops_skipped": self.stops_skipped,
            "stops_loaded": self.stops_loaded,
            "provider": self.provider,
            "mode": self.mode,
        }


def _provider_label(gtfs_dirs: Sequence[str], osm_paths: Sequence[str]) -> str:
    sources: list[str] = []
    if gtfs_dirs:
        sources.append("gtfs")
    if osm_paths:
        sources.append("osm")
    return "+".join(sources) if sources else "db"


def _parse_file_stops(
    gtfs_dirs: Sequence[str],
    osm_paths: Sequence[str],
) -> list:
    groups = []
    for path in gtfs_dirs:
        groups.append(parse_gtfs_stops(path))
    for path in osm_paths:
        groups.append(parse_osm_transit_geojson(path))
    return merge_stops(*groups) if groups else []


def _parse_file_headways(gtfs_dirs: Sequence[str]) -> dict[str, StopHeadway]:
    maps = [parse_gtfs_stop_headways(path) for path in gtfs_dirs]
    return merge_stop_headways(*maps) if maps else {}


def refresh_transit_proximity(
    session: Session,
    *,
    gtfs_dirs: Sequence[str] | None = None,
    osm_geojson_paths: Sequence[str] | None = None,
    from_db: bool = False,
    persist: bool = True,
    dry_run: bool = False,
    city: str | None = None,
    cfg: Any | None = None,
) -> TransitRefreshResult:
    """Parse (or load DB) stops, optionally upsert, then score neighbourhoods."""
    gtfs = [p for p in (gtfs_dirs or []) if str(p).strip()]
    osm = [p for p in (osm_geojson_paths or []) if str(p).strip()]
    mode = "from_db" if from_db else "files"
    stop_headways: dict[str, StopHeadway] = {}

    if from_db:
        stops = stops_from_db(session)
        provider = "db"
        stop_load = LoadResult(skipped=len(stops))
    else:
        if not gtfs and not osm:
            logger.warning("transit_refresh_missing_paths")
            return TransitRefreshResult(status="error", mode=mode)
        try:
            stops = _parse_file_stops(gtfs, osm)
            stop_headways = _parse_file_headways(gtfs)
        except (OSError, TransitProximityError) as exc:
            logger.warning("transit_refresh_parse_failed", error=str(exc))
            return TransitRefreshResult(status="error", mode=mode)
        provider = _provider_label(gtfs, osm)
        stop_load = LoadResult()
        if persist and not dry_run:
            stop_load = upsert_transit_stops(session, stops)

    if not stops:
        logger.warning("transit_refresh_no_stops", mode=mode)
        return TransitRefreshResult(
            status="empty",
            mode=mode,
            provider=provider,
            stops_inserted=stop_load.inserted,
            stops_updated=stop_load.updated,
            stops_skipped=stop_load.skipped,
            stops_loaded=0,
        )

    params = params_from_config(cfg)
    query = session.query(Neighborhood).filter(Neighborhood.geometry.isnot(None))
    if city:
        query = query.filter(Neighborhood.city == city)
    rows = []
    for n in query.all():
        try:
            poly = to_shape(n.geometry)
        except Exception:
            continue
        if poly is None or poly.is_empty:
            continue
        rows.append((n.id, poly))

    if not rows:
        if persist and not dry_run and not from_db:
            session.commit()
        return TransitRefreshResult(
            status="empty",
            mode=mode,
            provider=provider,
            stops_inserted=stop_load.inserted,
            stops_updated=stop_load.updated,
            stops_skipped=stop_load.skipped,
            stops_loaded=len(stops),
        )

    scores = score_neighbourhood_rows(
        rows,
        stops,
        params,
        provider=provider,
        stop_headways=stop_headways,
    )
    updated = 0
    if not dry_run:
        updated = apply_transit_scores(session, scores)
        session.commit()

    status = "ok" if not dry_run else "dry_run"
    logger.info(
        "transit_refresh_done",
        status=status,
        neighbourhoods_updated=updated,
        stops_loaded=len(stops),
        provider=provider,
        mode=mode,
    )
    return TransitRefreshResult(
        status=status,
        neighbourhoods_updated=updated if not dry_run else len(scores),
        stops_inserted=stop_load.inserted,
        stops_updated=stop_load.updated,
        stops_skipped=stop_load.skipped,
        stops_loaded=len(stops),
        provider=provider,
        mode=mode,
    )
