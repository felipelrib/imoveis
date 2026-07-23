# Side-by-side compare view — compare selected properties in one table (Story 1.3)

> Feature branch: `feat/bin-43-side-by-side-compare-view` · Linear: `BIN-43` · Status: implemented

## Problem

After selecting 2–4 properties on the grid (BIN-42), house-hunters had no side-by-side view for attributes, scores, price/m², and price history — the Compare button was a stub.

## Approach

- Full-screen `CompareView` overlay on the Properties page (keeps selection in `useCompareSelection`; no new route).
- Column data from `GET /properties/by-ids` / `fetchPropertiesByIds` only (AD-12 list projection + `primary_listing`).
- Price history via existing `GET /properties/{id}/price-history` per column (not in batch payload); empty/short series show placeholders instead of crashing.
- Exit: Back to grid keeps selection; Clear & exit clears selection and returns to browse.

## Changes

Files touched:

```
 frontend/src/components/CompareView.jsx              | NEW — side-by-side table + history charts
 frontend/src/pages/Properties.jsx                    | WIRE Compare → CompareView open/close
 frontend/src/index.css                               | ADD compare-view layout/table styles
 frontend/tests/e2e/helpers/apiMocks.js               | ADD by-ids + price-history mocks; enrich fixtures
 frontend/tests/e2e/compare-view.spec.js              | NEW — open, columns, exit/clear, empty history
 docs/features/29-side-by-side-compare-view.md        | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | Story 1.3 → done
```

## New Dependencies

None.

## How to Test

1. Full agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: `/properties` → select 2 cards → Compare → verify columns (price, scores, price/m², history) → Back to grid keeps bar; Clear & exit clears selection.

## Notes / Follow-ups

- Price history remains a separate endpoint (batch projection stays list-shaped per BIN-41).
- Map-view multi-select still out of scope (same as BIN-42).
- Optional later: deep-link `/properties/compare?ids=` for shareable compare URLs.
