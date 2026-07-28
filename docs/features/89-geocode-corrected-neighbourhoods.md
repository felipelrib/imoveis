# Geocode corrected neighbourhoods — low-precision polygon pins

> Feature branch: `feat/bin-112-geocode-corrected-neighbourhoods` · Linear: `BIN-112` · Status: implemented

## Problem

After OLX location reconcile corrects a neighbourhood and clears the seller pin, properties kept `location = NULL`. Name-based `neighborhood_id` assignment still worked for string cohorts, but spatial containment, map pins, and any pipeline that needs a point stayed empty until coordinates existed.

## Approach

- Prefer the matched neighbourhood polygon’s `ST_PointOnSurface` (guaranteed inside) over an external street geocoder — avoids inventing false parcel precision.
- Stamp `props_json.location_source = neighbourhood_point_on_surface` and `location_precision = neighbourhood` so consumers know the pin is approximate.
- Hook after by-name assign on scrape and in `fix_olx_listings.py`; gate with `scraping.olx_location.backfill_coords_from_neighbourhood`.
- Persist location clears / address / props on exact-match dedupe updates so re-scrapes do not leave stale seller pins.

## Changes

Files touched:

```
 src/core/neighbourhood_assignment.py              | apply_neighbourhood_representative_point + provenance constants
 src/core/dedupe.py                                | Persist location/address/props; intentional clear on OLX correction
 src/adapters/queue/tasks.py                       | Backfill pin after by-name assign
 scripts/dev/fix_olx_listings.py                  | Same backfill after correction apply
 src/infra/config.py                               | OlxLocationConfig
 configs/app_config.yaml                           | olx_location.backfill_coords_from_neighbourhood
 src/tests/unit/test_neighbourhood_assignment.py   | Unit specs for representative point
 src/tests/integration/test_neighbourhood_assignment.py | Point inside polygon + ST_Covers round-trip
 src/tests/unit/test_dedupe_orchestration.py       | Location clear / keep / props change
 src/tests/unit/test_scrape_listings_pipeline.py   | Expect backfill call
 src/tests/unit/test_scrape_run_telemetry.py       | Mock backfill
 docs/features/51-olx-listing-type-and-location.md | Follow-up closed → BIN-112
 docs/features/89-geocode-corrected-neighbourhoods.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Unit + integration:
   ```bash
   bash scripts/agent/validate.sh backend
   ```
2. Full gate before merge:
   ```bash
   bash scripts/agent/validate.sh all
   ```
3. Optional backfill dry-run / apply (existing BIN-72 script; now also writes neighbourhood pins):
   ```bash
   PYTHONPATH=src python scripts/dev/fix_olx_listings.py --skip-ai
   PYTHONPATH=src python scripts/dev/fix_olx_listings.py --apply --skip-ai
   ```

## Notes / Follow-ups

- Failure modes: no catalog/DB name match → no pin; match without `geometry` → no pin; platform pin kept when `clear_coords` is false; representative point is neighbourhood-level only (not a street address).
- External Nominatim/Google street geocoding remains out of scope.
- Related: BIN-72 / feature 51 (OLX location), BIN-54 (spatial assignment), BIN-104 epic.
