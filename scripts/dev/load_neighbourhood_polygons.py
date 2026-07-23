#!/usr/bin/env python3
"""Load neighbourhood polygons from a GeoJSON FeatureCollection into PostGIS.

Vendor-agnostic: pass any BH (or other) GeoJSON path — open data or manually
drawn. Does not hardcode a data provider URL.

Usage:
  PYTHONPATH=src python scripts/dev/load_neighbourhood_polygons.py \\
    --geojson path/to/neighbourhoods.geojson

  PYTHONPATH=src python scripts/dev/load_neighbourhood_polygons.py \\
    --geojson src/tests/fixtures/geo/bh_neighbourhoods_tiny.geojson --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))

from core.neighbourhood_geojson import (  # noqa: E402
    NeighbourhoodGeoJSONError,
    load_neighbourhood_geojson,
    neighbourhood_to_geojson_feature,
    parse_feature_collection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent load of neighbourhood POLYGON geometries (SRID 4326)."
    )
    parser.add_argument(
        "--geojson",
        required=True,
        help="Path to a GeoJSON FeatureCollection (Polygon / MultiPolygon features).",
    )
    parser.add_argument(
        "--city",
        default="Belo Horizonte",
        help="Default city when a feature omits properties.city (default: Belo Horizonte).",
    )
    parser.add_argument(
        "--state",
        default="MG",
        help="Default UF when a feature omits properties.state (default: MG).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate only; do not write to the database.",
    )
    args = parser.parse_args(argv)

    try:
        rows = parse_feature_collection(
            args.geojson, default_city=args.city, default_state=args.state
        )
    except (OSError, NeighbourhoodGeoJSONError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Parsed {len(rows)} neighbourhood feature(s) from {args.geojson}")
    if args.dry_run:
        for row in rows:
            neighbourhood_to_geojson_feature(row)
            print(
                f"  - {row.name} ({row.city}/{row.state}) "
                f"bounds={row.polygon.bounds}"
            )
        print("Dry-run complete; no database writes.")
        return 0

    from infra.db import SessionLocal

    with SessionLocal() as session:
        result = load_neighbourhood_geojson(
            session,
            args.geojson,
            default_city=args.city,
            default_state=args.state,
        )
        session.commit()

    print(
        f"Done: inserted={result.inserted} updated={result.updated} "
        f"skipped={result.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
