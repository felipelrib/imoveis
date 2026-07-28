# Saved-search filter casing — camelCase SPA ↔ snake_case API

> Feature branch: `feat/bin-109-saved-search-filter-casing` · Linear: `BIN-109` · Status: implemented

## Problem

Feature 57 noted that saved-search create validated a snake_case filter model while the SPA sent camelCase, so keys like `priceType` were ignored (`extra="ignore"`). That gap was fixed in BIN-100; this ticket reconciles the stale follow-up and locks `price_type` / `max_price` round-trip with regressions.

## Approach

- Treat BIN-109 as **reconcile + regression**, not a second casing redesign.
- Keep BIN-100 contract: SPA posts snake_case EN via `toSavedSearchWire`; API still accepts camelCase aliases and dumps snake_case via `SavedSearchFilters.to_wire()`.
- Add a TestClient create-path test that posts camelCase `priceType`/`maxPrice` and asserts persisted/response wire is snake_case.
- Add Playwright save → clear → reopen for max price + price type Sale.

## Changes

Files touched:

```
 src/tests/unit/test_saved_search_filters.py              | POST camelCase → snake_case create regression
 frontend/tests/e2e/saved-search-price-type.spec.js       | NEW — maxPrice + priceType=sale save/reopen
 docs/features/57-max-price-rent-sale-filter.md           | Retire stale casing follow-up
 docs/features/85-saved-search-filter-casing.md           | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: Properties → Advanced Filters → Max price `500000`, Price type Sale → Save Current Filters → Clear All → reopen saved search → max price and Sale restored; Network POST body uses `max_price` / `price_type`.

## Notes / Follow-ups

- Sort-by-price listing-type awareness remains a separate follow-up (BIN-106).
