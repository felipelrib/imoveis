# Transit proximity — GTFS / OSM stop scoring for neighbourhoods

> Feature branch: `feat/bin-89-transit-proximity` · Linear: `BIN-89` · Status: implemented

## Problem

“Near metro/bus” in listing copy is seller marketing. Operators need an objective
`transit_score` grounded in real stop/station geometry for BH / SP / Campinas.

## Approach

- Offline-first ingest: parse GTFS `stops.txt` (optional route/trip/stop_times for
  mode) and/or OSM Point GeoJSON; no live Overpass/GTFS HTTP in CI.
- Score each neighbourhood polygon centroid with config-driven radii and mode
  weights (metro/BRT > bus) → write `neighborhoods.transit_score` and
  `quality_meta.transit` without wiping other profile fields.
- Documented refresh CLI (`scripts/dev/refresh_transit_proximity.py`); no Celery
  beat for v1. No persistent stops table — files remain the source of truth.

## Changes

Files touched:

```
 configs/app_config.yaml                              | ADD — neighbourhood_quality.transit
 src/infra/config.py                                  | ADD — NeighbourhoodTransitConfig / QualityConfig
 src/core/transit_proximity.py                        | NEW — parse, score, apply
 scripts/dev/refresh_transit_proximity.py             | NEW — ops refresh job
 src/tests/fixtures/transit/                          | NEW — GTFS + OSM offline fixtures
 src/tests/unit/test_transit_proximity.py             | NEW — parse/score unit tests
 src/tests/integration/test_transit_proximity.py      | NEW — DB write → API read
 src/tests/unit/test_config.py                        | ADD — neighbourhood_quality critical section
 docs/features/67-transit-proximity.md                | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | 6-4 → done
```

## New Dependencies

None.

## How to Test

1. Unit + integration via the agent gate:
   ```bash
   bash scripts/agent/validate.sh backend
   ```
2. Dry-run refresh against fixtures (requires neighbourhoods with geometry in DB):
   ```bash
   PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \
     --gtfs-dir src/tests/fixtures/transit/gtfs_tiny \
     --osm-geojson src/tests/fixtures/transit/osm_stops_tiny.geojson \
     --dry-run
   ```
3. Live write (after loading polygons):
   ```bash
   PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \
     --gtfs-dir /path/to/gtfs \
     --osm-geojson /path/to/osm_stops.geojson
   ```

## Notes / Follow-ups

- Stretch (not in this PR): GTFS service frequency / headways — BIN-119.
- Sibling fills: BIN-87 curated YAML, BIN-88 OSM amenities, BIN-90 access, BIN-91 risk.
- Blending into property ranking/UI is BIN-94.
- Persist `transit_stops` + optional Celery beat: shipped in BIN-118 /
  `docs/features/91-persist-transit-stops.md`.
