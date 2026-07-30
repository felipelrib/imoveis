# Split Properties.jsx into sub-components — structural refactor of the monolithic properties page

> Feature branch: `feat/split-properties-page` · Linear: `BIN-141` · Status: implemented

## Problem

`frontend/src/pages/Properties.jsx` had grown to 1264 lines with 36 `useState` calls and 56 total hook calls in a single component. Filters, sorting, pagination, map sync, export, and compare-selection all lived in one component's closure, with no unit tests (only Playwright e2e specs) covering the behavior. Any change to one state slice (e.g. pagination) risked silently regressing an unrelated slice (e.g. filters), and the file's size made it hard to reason about or safely extend.

## Approach

- Pure structural refactor — **no behavior, DOM, class name, or `data-testid` change**. Every existing Playwright e2e spec covering `/properties` and `/favourites` had to keep passing unchanged (behavior lock), so JSX blocks were moved verbatim into new files rather than rewritten.
- Extracted two hooks:
  - `usePropertiesFiltersState` (`frontend/src/hooks/usePropertiesFiltersState.js`) — owns every filter/sort/search input (sort, transaction type, platform, property type, price, bedrooms, parking, score, city/neighborhood, furnished/pets, free-text search) plus the derived query-filter shape (`buildListQueryFilters`), the saved-search apply helper, and both "clear filters" variants (the advanced panel's "Clear All" resets the free-text search too; the empty-state's "Clear filters" intentionally doesn't — that distinction existed pre-split and is preserved).
  - `usePropertiesPagination` (`frontend/src/hooks/usePropertiesPagination.js`) — a thin wrapper around `useState` for the current page number, plus a pure `getPageWindow()` helper for the sliding page-number window the pager renders. Kept deliberately thin: Properties.jsx's refetch effects key off `page` directly, and returning the plain state setter (not a memoized action) preserves the existing "navigating back to page 1 always refetches" behavior (BIN-57).
- Extracted three presentational components under `frontend/src/components/properties/`:
  - `PropertiesFilterBar.jsx` — the toolbar (search / sort / transaction / source / type / export / view toggle / compare toggle / advanced-filters toggle) and the collapsible advanced-filters panel.
  - `PropertiesResultsGrid.jsx` — loading skeleton, empty state, and the property-card grid.
  - `PropertiesPagination.jsx` — the numbered pager.
  - `PropertyCard.jsx` — the individual property card (previously a ~230-line function at the bottom of Properties.jsx, along with its score/label formatting helpers).
- Properties.jsx now composes these hooks/components and keeps ownership of: routing/URL state (compare, favourites, deep links), data fetching (`load()`, the two refetch effects), watchlist/favourites/saved-searches state, map view, the property modal, and the compare bar/view — i.e. everything that still needs cross-cutting access to multiple state slices at once.
- Went with a **thin hook + prop-drilling** design over a context/reducer rewrite: the ticket is a structural split, not a state-management redesign, and prop-drilling keeps the diff a mechanical move rather than a behavioral rewrite (lower risk for an untested component).

## Changes

Files touched:

```
 frontend/src/pages/Properties.jsx                      | REWRITTEN — 1264 → ~570 lines; composes hooks + sub-components, keeps routing/fetching/modal/compare-bar ownership
 frontend/src/hooks/usePropertiesFiltersState.js         | NEW — filter/sort/search state, buildListQueryFilters, applyFilters, clearAllFilters/clearFiltersKeepSearch, hasActiveFilters
 frontend/src/hooks/usePropertiesPagination.js           | NEW — page state + getPageWindow() pure helper
 frontend/src/components/properties/PropertiesFilterBar.jsx   | NEW — toolbar + advanced-filters panel (moved verbatim)
 frontend/src/components/properties/PropertiesResultsGrid.jsx | NEW — loading/empty/grid states (moved verbatim)
 frontend/src/components/properties/PropertiesPagination.jsx  | NEW — numbered pager (moved verbatim)
 frontend/src/components/properties/PropertyCard.jsx          | NEW — property card + score/label helpers (moved verbatim)
```

## New Dependencies

None.

## How to Test

1. `bash scripts/agent/validate.sh all` — lint, backend contract/unit/integration, frontend build, and the full Playwright e2e suite (70 specs, all passing unchanged).
2. Manually: run the app, visit `/properties`, exercise filters (search, sort, transaction type, platform, property type, advanced filters incl. city/neighborhood multi-select), pagination, compare mode, favourites, export, and map view — behavior should be identical to before the split.

## Notes / Follow-ups

- Deliberately stayed in `.jsx` — a prior ticket (BIN-140) migrated only `api.js` → `api.ts` and made a scope decision to keep the rest of `frontend/src` in JS/JSX. A follow-up ticket (BIN-165, part of the BIN-160 TypeScript-migration epic) will type `Properties.jsx` and its new sub-components after this split lands.
- Discovered during implementation: ESLint's `react-hooks/set-state-in-effect` rule can't trace a state setter back to a recognized `useState()` call when it's returned from a custom hook (e.g. `usePropertiesPagination`'s `setPage`) instead of destructured directly in the component. This means an existing `eslint-disable-next-line` comment scoped to the setter call becomes an "unused directive" warning, while the *next* statement in the same effect (a plain function that itself calls a real `useState` setter, e.g. `load()`) picks up the violation instead. Not a functional bug — just something to account for when moving state out of a component into a hook near an existing effect-lint suppression. Logged in `docs/harness-troubleshooting.md`.
- No new unit-test framework was introduced for the extracted hooks (frontend has no Vitest/Jest setup, only Playwright e2e) — that's out of scope for this structural-only ticket; the e2e suite is the existing behavior lock.
