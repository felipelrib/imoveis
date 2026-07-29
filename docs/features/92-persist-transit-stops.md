# Persist transit_stops + optional beat refresh

> Feature branch: `feat/bin-118-persist-transit-stops` · Linear: `BIN-118` · Status: implemented

## Problem

Transit proximity (BIN-89) scored neighbourhoods from offline GTFS/OSM files
without a durable stops table or Celery beat, so operators had to re-parse
files for every rescore and BIN-119 (headways) had nothing to join against.

## Approach

- Add PostGIS `transit_stops` keyed by `(source, external_id)` with GIST on
  `location`; synthesize `lon:lat` when a parse has no stop id.
- Idempotent upsert (insert / update / skip-unchanged) plus `stops_from_db`
  to feed the existing scorer.
- Shared `adapters.geo.transit_refresh` used by the CLI and an opt-in Celery
  beat task (`enabled: false` by default), mirroring OSM amenities.
- No live GTFS/OSM HTTP; no auto-prune of removed stops (truncate if a full
  replace is needed). Headways remain BIN-119.

## Changes

Files touched:

```
 alembic/versions/3116c5d5061f_add_transit_stops.py | NEW — transit_stops table + GIST
 src/adapters/db/models.py                          | ADD — TransitStopRecord
 src/core/transit_stops.py                          | NEW — upsert / load helpers
 src/adapters/geo/transit_refresh.py                | NEW — parse → persist → score
 scripts/dev/refresh_transit_proximity.py           | UPDATE — --from-db / --no-persist / persist default
 src/infra/config.py                                | ADD — transit enabled / paths / interval
 configs/app_config.yaml                            | ADD — transit beat defaults (off)
 src/adapters/queue/celery_app.py                   | ADD — beat + scrapers route
 src/adapters/queue/tasks.py                        | ADD — tasks.refresh_transit_proximity
 src/tests/unit/test_transit_stops.py               | NEW — mocked upsert unit tests
 src/tests/unit/test_transit_refresh.py             | NEW — adapter + task unit tests
 src/tests/unit/test_schedule.py                    | ADD — beat/route coverage
 src/tests/unit/test_config.py                      | ADD — YAML transit beat defaults
 src/tests/unit/test_transit_proximity.py           | ADD — enabled/paths defaults
 src/tests/integration/test_transit_stops.py        | NEW — idempotent upsert + score-from-DB
 docs/features/67-transit-proximity.md              | UPDATE — Notes point at BIN-118
 docs/features/92-persist-transit-stops.md          | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Unit + integration:
   ```bash
   bash scripts/agent/validate.sh backend
   ```
2. Persist + score from fixtures:
   ```bash
   PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py \
     --gtfs-dir src/tests/fixtures/transit/gtfs_tiny \
     --osm-geojson src/tests/fixtures/transit/osm_stops_tiny.geojson
   ```
3. Rescore from the table only:
   ```bash
   PYTHONPATH=src python scripts/dev/refresh_transit_proximity.py --from-db
   ```
4. Enable beat (after configuring paths in `configs/app_config.yaml`):
   ```yaml
   neighbourhood_quality:
     transit:
       enabled: true
       gtfs_dirs: [/path/to/gtfs]
       osm_geojson_paths: [/path/to/stops.geojson]
       interval_hours: 168
   ```
   Rebuild `beat` + `worker_scraper` so the new route is loaded.

## Notes / Follow-ups

- GTFS service frequency / headways: BIN-119 (blocked by this table).
- Stale-stop prune / source-scoped replace not implemented — operators may
  `TRUNCATE transit_stops` before a full feed replace if needed.
- Related: BIN-89 / feature 67.
