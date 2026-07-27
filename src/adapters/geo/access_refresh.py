"""Refresh neighbourhood access_score from YAML hubs + OSRM/haversine (BIN-90)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from adapters.geo.osrm_client import OsrmClient
from core.neighbourhood_access import (
    access_meta_from_result,
    access_score_from_minutes,
    hubs_for_city,
    merge_access_meta,
    pick_best_hub_result,
    travel_to_hubs,
)
from infra.config import NeighbourhoodAccessConfig

logger = logging.getLogger(__name__)


def _load_neighbourhoods_with_points(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT
                id::text AS id,
                name,
                city,
                quality_meta,
                ST_Y(ST_PointOnSurface(geometry)) AS lat,
                ST_X(ST_PointOnSurface(geometry)) AS lon
            FROM neighborhoods
            WHERE geometry IS NOT NULL
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def refresh_neighbourhood_access(
    session: Session,
    cfg: NeighbourhoodAccessConfig,
    *,
    osrm_client: OsrmClient | None = None,
) -> dict[str, int]:
    """Compute and persist ``access_score`` + nested ``quality_meta.access``.

    Returns counts: ``processed``, ``updated``, ``skipped``, ``errors``.
    """
    processed = 0
    updated = 0
    skipped = 0
    errors = 0

    owns_client = False
    client = osrm_client
    if client is None and (cfg.base_url or "").strip():
        client = OsrmClient(
            cfg.base_url,
            mode=cfg.mode,
            timeout_sec=cfg.request_timeout_sec,
        )
        owns_client = True

    def route_via_osrm(
        olat: float, olon: float, hlat: float, hlon: float
    ):
        if client is None:
            return None
        return client.route(olat, olon, hlat, hlon)

    route_fn = route_via_osrm if client is not None else None

    try:
        rows = _load_neighbourhoods_with_points(session)
        for row in rows:
            processed += 1
            city = row.get("city")
            hubs = hubs_for_city(cfg.hubs, city)
            lat, lon = row.get("lat"), row.get("lon")
            if not hubs or lat is None or lon is None:
                skipped += 1
                continue
            try:
                results = travel_to_hubs(
                    origin_lat=float(lat),
                    origin_lon=float(lon),
                    hubs=hubs,
                    mode=cfg.mode,
                    avg_speed_kmh=cfg.avg_speed_kmh,
                    route_fn=route_fn,
                )
                best = pick_best_hub_result(results)
                if best is None:
                    skipped += 1
                    continue
                score = access_score_from_minutes(best.minutes, cfg.max_minutes)
                if score is None:
                    skipped += 1
                    continue
                access_payload = access_meta_from_result(best)
                new_meta = merge_access_meta(row.get("quality_meta"), access_payload)
                session.execute(
                    text(
                        """
                        UPDATE neighborhoods
                        SET access_score = :score,
                            quality_meta = CAST(:meta AS jsonb)
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {
                        "score": score,
                        "meta": json.dumps(new_meta),
                        "id": row["id"],
                    },
                )
                updated += 1
            except Exception:
                errors += 1
                logger.exception(
                    "neighbourhood_access_row_error",
                    extra={"neighborhood_id": row.get("id"), "city": city},
                )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_client and client is not None:
            client.close()

    logger.info(
        "neighbourhood_access_refresh_done",
        extra={
            "processed": processed,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        },
    )
    return {
        "processed": processed,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
