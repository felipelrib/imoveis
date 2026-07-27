#!/usr/bin/env python3
"""Refresh neighbourhood transit_score from GTFS and/or OSM stop files (BIN-89).

Offline / ops job — no live Overpass or GTFS HTTP. Export municipal GTFS or
OSM ``public_transport`` / railway station extracts for operator cities
(Belo Horizonte, São Paulo, Campinas), then run this script.

Expected GTFS layout (directory)::

    stops.txt                 # required
    routes.txt                # optional — enables metro/bus mode mapping
    trips.txt
    stop_times.txt

OSM GeoJSON: FeatureCollection of Point features with ``properties.mode``
or OSM-style tags (``railway=station``, ``highway=bus_stop``, …).

Usage::

  PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \\
    --gtfs-dir path/to/gtfs --osm-geojson path/to/stops.geojson

  PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \\
    --osm-geojson src/tests/fixtures/transit/osm_stops_tiny.geojson --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from geoalchemy2.shape import to_shape  # noqa: E402

from adapters.db.models import Neighborhood  # noqa: E402
from core.transit_proximity import (  # noqa: E402
    TransitProximityError,
    apply_transit_scores,
    merge_stops,
    params_from_config,
    parse_gtfs_stops,
    parse_osm_transit_geojson,
    score_neighbourhood_rows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score neighbourhood transit proximity from GTFS/OSM stop files "
            "and write neighborhoods.transit_score + quality_meta.transit."
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
        "--dry-run",
        action="store_true",
        help="Parse and score only; do not write to the database.",
    )
    args = parser.parse_args(argv)

    if not args.gtfs_dir and not args.osm_geojson:
        print("error: provide at least one --gtfs-dir or --osm-geojson", file=sys.stderr)
        return 1

    try:
        groups = []
        for path in args.gtfs_dir:
            groups.append(parse_gtfs_stops(path))
            print(f"Loaded {len(groups[-1])} GTFS stop(s) from {path}")
        for path in args.osm_geojson:
            groups.append(parse_osm_transit_geojson(path))
            print(f"Loaded {len(groups[-1])} OSM stop(s) from {path}")
    except (OSError, TransitProximityError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    stops = merge_stops(*groups)
    if not stops:
        print("error: no stops parsed", file=sys.stderr)
        return 1

    sources = set()
    if args.gtfs_dir:
        sources.add("gtfs")
    if args.osm_geojson:
        sources.add("osm")
    provider = "+".join(sorted(sources)) if sources else "unknown"

    from infra.config import get_config
    from infra.db import SessionLocal

    params = params_from_config(get_config())

    with SessionLocal() as session:
        q = session.query(Neighborhood).filter(Neighborhood.geometry.isnot(None))
        if args.city:
            q = q.filter(Neighborhood.city == args.city)
        rows = []
        for n in q.all():
            poly = to_shape(n.geometry)
            rows.append((n.id, poly))

        if not rows:
            print("No neighbourhoods with geometry found; nothing to score.")
            return 0

        scores = score_neighbourhood_rows(
            rows, stops, params, provider=provider
        )
        print(f"Scored {len(scores)} neighbourhood(s); provider={provider}")
        for item in scores[:20]:
            print(
                f"  id={item.neighborhood_id} score={item.transit_score:.3f} "
                f"nearest_m={item.meta.get('nearest_m')} "
                f"mode={item.meta.get('nearest_mode')} "
                f"count={item.meta.get('stop_count')}"
            )
        if len(scores) > 20:
            print(f"  ... and {len(scores) - 20} more")

        if args.dry_run:
            print("Dry-run complete; no database writes.")
            return 0

        updated = apply_transit_scores(session, scores)
        session.commit()
        print(f"Updated transit_score on {updated} neighbourhood(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
