#!/usr/bin/env python3
"""Refresh neighbourhood amenity_score from OSM POIs (BIN-88).

Offline-first: point ``neighbourhood_quality.osm_amenities.mode`` at ``geojson``
and a POI FeatureCollection path. For live Overpass, set ``mode: overpass``
and be polite (rate_limit_per_minute).

Usage:
  PYTHONPATH=src python scripts/dev/refresh_neighbourhood_amenities.py

  PYTHONPATH=src python scripts/dev/refresh_neighbourhood_amenities.py \\
    --mode geojson --poi-geojson src/tests/fixtures/geo/osm_pois_tiny.geojson

  PYTHONPATH=src python scripts/dev/refresh_neighbourhood_amenities.py \\
    --mode overpass --enabled
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from adapters.geo.amenity_refresh import refresh_neighbourhood_amenities  # noqa: E402
from infra.config import get_config  # noqa: E402
from infra.db import SessionLocal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh neighborhoods.amenity_score from OSM POI density."
    )
    parser.add_argument(
        "--mode",
        choices=("geojson", "overpass"),
        default=None,
        help="Override config mode (geojson | overpass).",
    )
    parser.add_argument(
        "--poi-geojson",
        default=None,
        help="Override path to a POI FeatureCollection (mode=geojson).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Max neighbourhoods to refresh in this run.",
    )
    parser.add_argument(
        "--buffer-m",
        type=float,
        default=None,
        help="Expand neighbourhood polygons by this many meters when matching POIs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved settings and exit without writing.",
    )
    args = parser.parse_args(argv)

    cfg = get_config()
    osm = cfg.neighbourhood_quality.osm_amenities
    mode = args.mode or osm.mode
    poi_path = args.poi_geojson if args.poi_geojson is not None else osm.poi_geojson_path
    batch_size = args.batch_size if args.batch_size is not None else osm.batch_size
    buffer_m = args.buffer_m if args.buffer_m is not None else osm.buffer_m

    settings = {
        "mode": mode,
        "poi_geojson_path": poi_path,
        "batch_size": batch_size,
        "buffer_m": buffer_m,
        "overpass_url": osm.overpass_url,
        "rate_limit_per_minute": osm.rate_limit_per_minute,
        "cache_dir": osm.cache_dir or None,
    }
    if args.dry_run:
        print(json.dumps(settings, indent=2))
        return 0

    if mode == "geojson" and not (poi_path or "").strip():
        print("error: mode=geojson requires --poi-geojson or config poi_geojson_path", file=sys.stderr)
        return 2

    with SessionLocal() as session:
        result = refresh_neighbourhood_amenities(
            session,
            mode=mode,
            poi_geojson_path=poi_path or "",
            buffer_m=float(buffer_m),
            category_targets=dict(osm.category_targets),
            batch_size=int(batch_size),
            overpass_url=osm.overpass_url,
            request_timeout_sec=float(osm.request_timeout_sec),
            rate_limit_per_minute=float(osm.rate_limit_per_minute),
            cache_dir=osm.cache_dir,
            cache_ttl_hours=float(osm.cache_ttl_hours),
        )
    print(json.dumps(result.as_dict(), indent=2))
    return 0 if result.status in ("ok", "empty", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
