# PropertyModal fetch-failure crash guard — render an error state instead of blanking the page

> Feature branch: `fix/propertymodal-fetch-crash` · Linear: `BIN-153` · Status: implemented

## Problem

`PropertyModal.jsx` fetched the property detail with `fetchProperty(id).then(setProperty).catch(console.error)`. On failure, `property` stayed `null` while `loading` still flipped to `false` in `.finally`. The non-loading render branch then dereferenced `p.platform`, `p.price_per_m2_rent`, `p.combined_score_rent`, and several other properties **without optional chaining** (unlike the top of the component, which used `p?.`).

Any 404/500/network failure on `GET /properties/{id}` therefore threw `TypeError: Cannot read properties of null`. That error propagated up to the single app-wide `ErrorBoundary` in `App.jsx`, which blanked the *entire* Properties page — grid, filters, and sidebar — instead of just the modal that failed to load. No e2e test exercised a failed property fetch; `property-modal-listings.spec.js` only covered the happy path.

## Approach

- Render an explicit error/empty state in the modal body when `!loading && !property`, instead of falling through into the data-dependent JSX that assumes a populated `property` object.
- Keep the fix scoped to the modal body: the header (favourite/watchlist buttons, listing links) already used `p?.` accessors, so it was already crash-safe and needed no change.
- Reuse the existing `errors.propertyFetchFailed` i18n key pattern by adding two new keys (`modal.loadErrorTitle`, `modal.loadErrorBody`) to both `en` and `pt-BR` catalogs to keep locale parity.
- Added a dedicated Playwright regression spec (`property-modal-fetch-failure.spec.js`) that mocks both a 404 and a 500 on the property-detail endpoint and asserts the modal renders the error state instead of throwing — and that the rest of the Properties page (grid) stays intact after closing the modal.

## Changes

Files touched:

```
 frontend/src/components/PropertyModal.jsx                | FIX — render an explicit error state when !loading && !property instead of falling through to the data-dependent render branch
 frontend/src/i18n/locales/en.json                         | NEW — modal.loadErrorTitle / modal.loadErrorBody keys
 frontend/src/i18n/locales/pt-BR.json                       | NEW — modal.loadErrorTitle / modal.loadErrorBody keys (pt-BR translation)
 frontend/tests/e2e/property-modal-fetch-failure.spec.js   | NEW — regression Playwright spec: 404 and 500 on GET /properties/{id} render the error state, not a crash
```

## New Dependencies

None.

## How to Test

1. `bash scripts/agent/validate.sh all` (includes the new Playwright spec in the e2e suite).
2. Manually: open a property in the dashboard, then in devtools throttle/block the `GET /api/properties/{id}` request (or navigate directly to a deep link for a deleted property) — the modal should show "Couldn't load this property" instead of a blank page.

## Notes / Follow-ups

- Two sibling tickets (BIN-155, BIN-158) also touch `PropertyModal.jsx` and were intentionally blocked on this one merging first to avoid conflicts.
- Parent epic: BIN-128 (v0.10 — Technical debt remediation). Several other siblings remain open; epic close is not yet ready.
