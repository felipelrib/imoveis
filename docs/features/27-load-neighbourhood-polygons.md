# Load neighbourhood polygons — GeoJSON seed into PostGIS (SRID 4326)

> Feature branch: `feat/bin-53-load-neighbourhood-polygons` · Linear: `BIN-53` · Status: implemented

## Problem

Spatial neighbourhood assignment (FR-22 / Epic 5) needs real polygons on `neighborhoods.geometry`. The table existed with a nullable POLYGON column, but no rows, no natural key for idempotent reload, and no import path. Polygon source (municipal open data vs manually drawn GeoJSON) is intentionally left open in the PRD — the product must not lock a vendor in code.

## Approach

- Vendor-agnostic GeoJSON `FeatureCollection` contract: each feature needs `properties.name`; `city` / `state` default to Belo Horizonte / MG.
- Core loader in `core.neighbourhood_geojson` parses features (Polygon; MultiPolygon → largest part) and upserts by `(name, city, state)`.
- Alembic adds that unique constraint plus a GIST index on `geometry` (ready for BIN-54 containment).
- CLI `scripts/dev/load_neighbourhood_polygons.py` points at any local GeoJSON path (open data export or manual). Git only ships a tiny synthetic fixture for tests — not a full BH dump.
- Re-runs are safe: identical geometries are skipped; changed rings update in place and keep the same `id`.

## Changes

Files touched:

```
 alembic/versions/f9a0b1c2d3e4_neighbourhood_geometry_constraints.py | NEW — unique key + GIST
 src/adapters/db/models.py                                          | ADD UniqueConstraint on Neighborhood
 src/core/neighbourhood_geojson.py                                  | NEW — parse + idempotent upsert
 scripts/dev/load_neighbourhood_polygons.py                         | NEW — CLI entrypoint
 src/tests/fixtures/geo/bh_neighbourhoods_tiny.geojson              | NEW — tiny BH-bbox fixture
 src/tests/unit/test_neighbourhood_geojson.py                       | NEW — parse / MultiPolygon / errors
 src/tests/integration/test_neighbourhood_polygons.py               | NEW — SRID/valid/idempotent load
 docs/features/27-load-neighbourhood-polygons.md                    | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml           | Story 5.1 done; epic-5 in-progress
```

## New Dependencies

None (uses existing `shapely` + `geoalchemy2`).

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Dry-run parse of the tiny fixture:
   ```bash
   PYTHONPATH=src python scripts/dev/load_neighbourhood_polygons.py \
     --geojson src/tests/fixtures/geo/bh_neighbourhoods_tiny.geojson --dry-run
   ```
3. Load into a running PostGIS (compose / worktree ports):
   ```bash
   PYTHONPATH=src python scripts/dev/load_neighbourhood_polygons.py \
     --geojson /path/to/your-bh-neighbourhoods.geojson
   ```
   Re-run the same command; row count stays stable.

### Polygon source (open data vs manual)

Bring your own BH (or other) GeoJSON — for example a municipal open-data bairro layer, OSM-derived export, or a manually drawn FeatureCollection. The loader only cares about the GeoJSON shape above; no provider URL or vendor SDK is hardcoded. Prefer a curated subset for local/dev; keep large dumps out of git.

## Notes / Follow-ups

- BIN-54 / Story 5.2: assign `properties.neighborhood_id` via `ST_Contains` in the enrichment pipeline (AD-10), not from API handlers (AD-3).
- BIN-55 / Story 5.3: scoring cohorts prefer spatially assigned neighbourhoods.
- Optional later: GIST on `properties.location` if containment queries need it.
