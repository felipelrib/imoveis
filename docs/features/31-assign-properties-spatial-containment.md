# Assign properties by spatial containment — PostGIS neighbourhood FK from pipeline

> Feature branch: `feat/bin-54-spatial-property-assignment` · Linear: `BIN-54` · Status: implemented

## Problem

Properties carried a nullable `neighborhood_id` FK and scrapers put a string neighbourhood in `props_json`, but nothing ever set the FK from geography. Score cohorts and deal verdicts therefore relied on brittle string fallback even after neighbourhood polygons were loaded (BIN-53 / FR-22).

## Approach

- Named enrichment-pipeline stage `core.neighbourhood_assignment.assign_property_neighbourhood` (AD-10): PostGIS `ST_Covers(n.geometry, p.location)` so boundary points count as inside (plain `ST_Contains` would exclude them).
- Overlapping polygons resolve deterministically with `ORDER BY n.name ASC LIMIT 1`.
- Outside all polygons (or no matching geometry): set `neighborhood_id = NULL`; `props_json->>'neighborhood'` remains the documented scoring/UI fallback.
- Null `location`: leave existing FK unchanged (no-op).
- Wired in `scrape_listings` after dedupe (before commit) so properties without AI images still get assigned, and again in `ai_enrich` immediately before `score_single_property` so admin re-enrich refreshes the FK before cohorts run.
- Not called from API handlers (AD-3).

## Changes

Files touched:

```
 src/core/neighbourhood_assignment.py                    | NEW — ST_Covers assignment stage
 src/adapters/queue/tasks.py                             | Hook scrape + ai_enrich (pre-score)
 src/tests/unit/test_neighbourhood_assignment.py         | NEW — missing / null location / API guard
 src/tests/integration/test_neighbourhood_assignment.py  | NEW — inside / boundary / outside
 docs/features/31-assign-properties-spatial-containment.md | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | Story 5.2 done
```

## New Dependencies

None.

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Focused integration (with worktree `DATABASE_URL` / `POSTGRES_PORT`):
   ```bash
   PYTHONPATH=src pytest src/tests/integration/test_neighbourhood_assignment.py -v
   ```
3. After loading polygons (`scripts/dev/load_neighbourhood_polygons.py`), scrape or re-enrich a property whose point falls inside a polygon and confirm `properties.neighborhood_id` is set.

## Notes / Follow-ups

- BIN-55 / Story 5.3: scoring cohorts prefer spatially assigned neighbourhoods (readers already `COALESCE` FK over string).
- Existing rows without a re-scrape / `ai_enrich` stay unassigned until the pipeline runs again (no bulk backfill in this story).
- Optional later: GIST on `properties.location` if containment volume needs it.
