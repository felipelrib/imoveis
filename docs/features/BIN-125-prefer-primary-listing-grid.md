# Prefer primary_listing in grid/modal — AD-12 decisioning price

> Feature branch: `feat/bin-125-prefer-primary-listing` · Linear: `BIN-125` · Status: implemented

## Problem

Properties grid and modal still flattened decisioning price locally via `groupListings` / top-level `price`, even though the API already ships AD-12 `primary_listing`. That risked diverging from the canonical projection and left a second “best price” rule in React.

## Approach

- Shared helpers in `frontend/src/utils/primaryListing.js`: `decisioningPrice`, `groupListings`, `bestListingForType`, `isPrimaryListingRow`.
- Grid cards keep multi-type / multi-platform display rows via `groupListings`, but each type’s displayed listing prefers `primary_listing` when types match.
- Modal header uses `decisioningPrice`; listings-by-platform table still groups locally and stars the primary row for its type.
- Compare and map reuse the same `decisioningPrice` helper — no second projection shape.

## Changes

Files touched:

```
 frontend/src/utils/primaryListing.js                    | NEW — shared AD-12 helpers
 frontend/src/pages/Properties.jsx                       | USE bestListingForType / decisioningPrice
 frontend/src/components/PropertyModal.jsx               | USE decisioningPrice + groupListings
 frontend/src/components/CompareView.jsx                 | IMPORT shared decisioningPrice
 frontend/src/components/MapView.jsx                     | Feature price via decisioningPrice
 frontend/tests/e2e/primary-listing-grid.spec.js         | NEW — util + card/modal regression
 docs/features/BIN-125-prefer-primary-listing-grid.md         | NEW — this doc
 docs/features/BIN-41-canonical-property-projection.md       | UPDATE — follow-up done
 docs/features/BIN-42-multi-select-properties-comparison.md  | UPDATE — follow-up done
```

## New Dependencies

None.

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Playwright focus:
   ```bash
   cd frontend && npx playwright test tests/e2e/primary-listing-grid.spec.js
   ```
3. Manual: open `/properties` for a dual-listed property — card rent/sale rows match API `primary_listing` for the decisioning type; modal header matches; listings-by-platform table still shows all platforms.

## Notes / Follow-ups

- Closed the grid/modal follow-ups from features 26 and 27 (BIN-125).
- Export/digest already reuse the API projection (AD-12); no further frontend flatteners planned.
