# osm-amenity-density-for-neighbourhoods — OSM amenity density → amenity_score

> Feature branch: `feat/bin-88-osm-amenity-density` · Linear: `BIN-88` · Status: implemented

## Problem

Neighbourhood “near supermarket / park / school” signals came only from listing copy. BIN-86 added `amenity_score` storage, but nothing filled it from objective map data.

## Approach

- Count OSM-tagged POIs (shops, parks, schools, healthcare) inside each neighbourhood polygon (optional meter buffer).
- Score = mean of per-category saturating ratios `min(1, count / target)` with config targets.
- Dual source: offline POI GeoJSON (CI/dev) or HTTP Overpass (rate-limited, optional disk cache). No vendor SDK; no raw PBF parser (operator converts extract → GeoJSON).
- Celery task `tasks.refresh_neighbourhood_amenities` on the `scrapers` queue; default `enabled: false`.
- Writes `amenity_score` + merges `quality_meta` with `source: osm`, `refreshed_at`, and `amenity_counts`.

## Changes

Files touched:

```
 src/core/osm_amenities.py                                  | NEW — classify / count / score
 src/adapters/geo/osm_poi_loader.py                         | NEW — offline GeoJSON POIs
 src/adapters/geo/osm_overpass.py                           | NEW — Overpass HTTP + cache
 src/adapters/geo/amenity_refresh.py                        | NEW — DB refresh orchestration
 src/adapters/geo/__init__.py                               | NEW — package
 src/infra/config.py                                        | OsmAmenitiesConfig
 configs/app_config.yaml                                    | neighbourhood_quality.osm_amenities
 src/adapters/queue/celery_app.py                           | route + beat gate
 src/adapters/queue/tasks.py                                | refresh_neighbourhood_amenities task
 scripts/dev/refresh_neighbourhood_amenities.py             | NEW — operator CLI
 src/tests/fixtures/geo/osm_pois_tiny.geojson               | NEW — fixture POIs
 src/tests/unit/test_osm_amenities.py                       | NEW — domain tests
 src/tests/unit/test_osm_amenity_adapters.py                | NEW — loader/overpass/task
 src/tests/unit/test_schedule.py                            | Beat/route assertions
 docs/features/67-osm-amenity-density-for-neighbourhoods.md | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml   | 6-3 done
```

## New Dependencies

None (httpx + shapely already present). Offline path expects a prepared POI GeoJSON, not `.osm.pbf`.

## How to Test

1. Load neighbourhood polygons if needed (`scripts/dev/load_neighbourhood_polygons.py`).
2. Offline dry run:
   ```bash
   PYTHONPATH=src python scripts/dev/refresh_neighbourhood_amenities.py \
     --mode geojson \
     --poi-geojson src/tests/fixtures/geo/osm_pois_tiny.geojson
   ```
3. Confirm `GET /properties/neighborhoods/{id}` shows `amenity_score` and `quality_meta.source == "osm"`.
4. Automated (no live Overpass):
   ```bash
   bash scripts/agent/validate.sh all
   ```

### Operator notes

- Prefer `mode: geojson` for local/CI. Export POIs from an OSM extract (Overpass turbo, osmium tags-filter → GeoJSON, etc.) with Point features and OSM tags as properties.
- For Overpass: set `mode: overpass`, optionally `cache_dir`, keep `rate_limit_per_minute` low, then either run the CLI or set `enabled: true` and rebuild beat + scraper worker.
- Raw PBF is out of scope; convert to GeoJSON first.

## Notes / Follow-ups

- Sibling fills: [BIN-87](https://linear.app/felipelrib/issue/BIN-87) curated YAML, [BIN-89](https://linear.app/felipelrib/issue/BIN-89) transit, [BIN-90](https://linear.app/felipelrib/issue/BIN-90) access, [BIN-91](https://linear.app/felipelrib/issue/BIN-91) risk.
- Blend into scoring/UI: [BIN-94](https://linear.app/felipelrib/issue/BIN-94). Epic: [BIN-85](https://linear.app/felipelrib/issue/BIN-85).
- Concurrent YAML + OSM writers may overwrite top-level `source` / `refreshed_at` in `quality_meta`; counts remain under `amenity_counts`.
