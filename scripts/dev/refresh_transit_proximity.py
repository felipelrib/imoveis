#!/usr/bin/env python3
"""Refresh neighbourhood transit_score from GTFS and/or OSM stop files (BIN-89/118).

Offline / ops job — no live Overpass or GTFS HTTP. Export municipal GTFS or
OSM ``public_transport`` / railway station extracts for operator cities
(Belo Horizonte, São Paulo, Campinas), then run this script.

By default stops are upserted into ``transit_stops`` (idempotent on
``source`` + ``external_id``) before neighbourhood scores are written.
Use ``--from-db`` to rescore from the persisted table without re-parsing files.
Use ``--dry-run`` to parse/score without any database writes.

Optional Celery beat (off by default)::

    neighbourhood_quality.transit.enabled: true
    neighbourhood_quality.transit.gtfs_dirs: [/path/to/gtfs]
    neighbourhood_quality.transit.osm_geojson_paths: [/path/to/stops.geojson]
    neighbourhood_quality.transit.interval_hours: 168

Expected GTFS layout (directory)::

    stops.txt                 # required
    routes.txt                # optional — enables metro/bus mode mapping
    trips.txt
    stop_times.txt            # modes + optional headway fallback (departure times)
    frequencies.txt           # optional — preferred headway_secs for quality_meta

Headways are nested under ``quality_meta.transit.headway`` (schedule estimate,
not live). ``--from-db`` / OSM-only refreshes leave headway as unavailable.

OSM GeoJSON: FeatureCollection of Point features with ``properties.mode``
or OSM-style tags (``railway=station``, ``highway=bus_stop``, …).

Usage::

  PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \\
    --gtfs-dir path/to/gtfs --osm-geojson path/to/stops.geojson

  PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \\
    --osm-geojson src/tests/fixtures/transit/osm_stops_tiny.geojson --dry-run

  PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py --from-db
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from adapters.geo.transit_refresh import refresh_transit_proximity  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score neighbourhood transit proximity from GTFS/OSM stop files "
            "(or persisted transit_stops), upsert stops, and write "
            "neighborhoods.transit_score + quality_meta.transit."
        )
    )
    parser.add_argument(
        "--gtfs-dir",
        action="append",
        default=[],
        help="GTFS directory containing stops.txt (repeatable).",
    )
    parser.add_argument(
        "--osm-geojson",
        action="append",
        default=[],
        help="OSM-style Point FeatureCollection GeoJSON (repeatable).",
    )
    parser.add_argument(
        "--city",
        default=None,
        help="Only score neighbourhoods in this city (exact match).",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Score from persisted transit_stops only (ignore file args).",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not upsert into transit_stops (score only from files).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and score only; do not write to the database.",
    )
    args = parser.parse_args(argv)

    if not args.from_db and not args.gtfs_dir and not args.osm_geojson:
        print(
            "error: provide --from-db or at least one --gtfs-dir / --osm-geojson",
            file=sys.stderr,
        )
        return 1

    cfg = get_config()
    with SessionLocal() as session:
        result = refresh_transit_proximity(
            session,
            gtfs_dirs=args.gtfs_dir,
            osm_geojson_paths=args.osm_geojson,
            from_db=args.from_db,
            persist=not args.no_persist,
            dry_run=args.dry_run,
            city=args.city,
            cfg=cfg,
        )

    print(
        f"status={result.status} mode={result.mode} provider={result.provider} "
        f"stops_loaded={result.stops_loaded} "
        f"stops_inserted={result.stops_inserted} "
        f"stops_updated={result.stops_updated} "
        f"stops_skipped={result.stops_skipped} "
        f"neighbourhoods_updated={result.neighbourhoods_updated}"
    )
    if result.status == "error":
        return 1
    if result.status == "dry_run":
        print("Dry-run complete; no database writes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
