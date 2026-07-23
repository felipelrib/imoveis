# Multi-select properties for comparison — grid selection UX (Story 1.2)

> Feature branch: `feat/bin-42-multi-select-properties-comparison` · Linear: `BIN-42` · Status: implemented

## Problem

House-hunters need to pick 2–4 properties from the grid before opening a side-by-side compare, without juggling browser tabs. There was no multi-select affordance, no selection cap, and no clear Compare CTA on the Properties page.

## Approach

- Client-only ordered selection via `useCompareSelection` (max 4 ids); no Redis/DB persistence (AD-8).
- Checkbox on each `PropertyCard` with `stopPropagation` so favourites/modal clicks stay intact.
- Sticky compare bar when anything is selected: count, Clear, Compare (enabled only at 2–4).
- Fifth selection blocked with a non-blocking warning toast.
- Compare button is an enabled stub for BIN-43 (side-by-side view + `fetchPropertiesByIds`); this story does not call `/properties/by-ids`.

## Changes

Files touched:

```
 frontend/src/hooks/useCompareSelection.js              | NEW — ordered max-4 selection hook
 frontend/src/pages/Properties.jsx                      | ADD checkbox, compare bar, toast on limit
 frontend/src/index.css                                 | ADD selected card + compare bar styles
 frontend/tests/e2e/helpers/apiMocks.js                 | ADD PROPERTIES_PAGE_FIVE fixture
 frontend/tests/e2e/compare-select.spec.js              | NEW — Playwright multi-select coverage
 docs/features/27-multi-select-properties-comparison.md | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | Story 1.2 → done
```

## New Dependencies

None.

## How to Test

1. Full agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: open `/properties`, check 2 cards → Compare enabled; check 4 more attempts → toast at 5th; Clear → bar gone.

## Notes / Follow-ups

- BIN-43 / Story 1.3: wire Compare to side-by-side view using `GET /properties/by-ids` / `fetchPropertiesByIds`.
- Grid still uses local `groupListings` for price display; prefer `primary_listing` from BIN-41 when convenient.
- Map view selection left out of this story (AC targets listed cards).
