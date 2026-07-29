# Map-view multi-select for compare — select 2–4 map markers into the shared compare selection

> Feature branch: `feat/bin-115-map-view-multi-select` · Linear: `BIN-115` · Status: implemented

## Problem

Map view could open property details but could not add markers to the compare selection. Multi-select (BIN-42) and side-by-side compare (BIN-43) only covered grid card checkboxes; features 27 and 29 explicitly deferred map selection.

## Approach

- Reuse the existing `useCompareSelection` hook and sticky compare bar owned by `Properties.jsx` — no new selection context.
- Gate map selection on the same Compare mode toggle as the grid.
- In compare mode, marker clicks toggle selection by `public_id` (`linkIdForProperty`) and do not open the detail modal; outside compare mode, keep the existing popup + View Details flow.
- Drive selected styling via a GeoJSON `selected` property on the unclustered circle layer; add HTML MapLibre markers with `data-testid` hit targets so Playwright can exercise selection without canvas coordinate guessing.
- Keep cluster clicks as zoom-only.

## Changes

Files touched:

```
 frontend/src/components/MapView.jsx                    | Compare props, refs, selected paint, HTML hit targets
 frontend/src/pages/Properties.jsx                      | Pass compareMode / selectedIds / onToggleCompare into MapView
 frontend/src/index.css                                 | Styles for map compare hit targets
 frontend/tests/e2e/helpers/apiMocks.js                 | Distinct lat/lon on PROPERTIES_PAGE_FIVE fixtures
 frontend/tests/e2e/compare-map-select.spec.js          | NEW — Playwright coverage for map multi-select
 docs/features/91-map-view-multi-select-compare.md      | NEW — this feature doc
```

## New Dependencies

None.

## How to Test

1. Open Properties → Map → Compare mode.
2. Click two markers; confirm the compare bar shows “2 selected” and Open Comparison is enabled.
3. Select four, then a fifth; confirm the max-4 toast and count stays at 4.
4. Clear / Exit Compare; confirm selection clears and hit targets disappear.
5. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Closes the map multi-select follow-up called out in `docs/features/27-multi-select-properties-comparison.md` and `29-side-by-side-compare-view.md`.
- Cluster multi-select (select all members of a cluster) remains out of scope.
- Fixed a pre-existing MapLibre `step` paint validation error on cluster `circle-color` (missing final stop output) while wiring layers.
- Map view no longer unmounts `MapView` on bbox refetch (`mapLoading`); an overlay is shown instead so compare hit targets stay stable.
