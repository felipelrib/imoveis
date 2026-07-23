# Export from the Properties UI — CSV/JSON download for current filters

> Feature branch: `feat/bin-51-export-properties-ui` · Linear: `BIN-51` · Status: implemented

## Problem

House-hunters can call `GET /properties/export` (Story 4.1) but had no Properties-page action to download the filtered shortlist. Crafting API URLs by hand breaks AD-8 (all browser I/O via `api.js`) and hides the feature from day-to-day use.

## Approach

- Add `exportProperties()` in `api.js`: same filter params as `fetchProperties`, optional `X-API-Key`, triggers a browser download for CSV or JSON.
- Place **Export CSV** / **Export JSON** buttons on the Properties toolbar; errors toast non-blockingly via ToastProvider.
- Export always uses the current list filters (Story 4.1 surface), including when favourites view is active.
- Playwright covers happy-path downloads with filters and a non-blocking error toast.

## Changes

Files touched:

```
 frontend/src/api.js                                      | ADD buildPropertyFilterParams + exportProperties download helper
 frontend/src/pages/Properties.jsx                        | ADD Export CSV/JSON buttons + handleExport toasts
 frontend/tests/e2e/helpers/apiMocks.js                   | ADD mockPropertiesExport
 frontend/tests/e2e/properties-export.spec.js             | NEW — e2e for export + error toast
 docs/features/36-export-from-properties-ui.md            | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | Story 4.2 → done
```

## New Dependencies

None.

## How to Test

1. Full gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual (frontend + API up):
   - Open `/properties`, set Max price / beds / search.
   - Click **Export CSV** → browser downloads `properties-export.csv`.
   - Click **Export JSON** → browser downloads `properties-export.json`.
   - With API returning 5xx on `/properties/export`, confirm error toast and list still visible.

## Notes / Follow-ups

- Depends on BIN-50 (`docs/features/35-export-filtered-properties-api.md`).
- Digest (BIN-52) remains separate; no favourites-only export in this story.
