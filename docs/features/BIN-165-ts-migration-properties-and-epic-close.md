# TS migration: Properties subtree + epic close — drop allowJs/checkJs

> Feature branch: `feat/bin-165-ts-migration-propertiesjsx-after-bin-141-split` · Linear: `BIN-165` · Status: implemented

## Problem

Final ticket of the v0.11 frontend TypeScript migration epic (BIN-160). Migrates the
`Properties` page and everything BIN-141's structural split produced, then removes the
`tsconfig.json` gradual-migration accommodation now that nothing `.jsx`/`.js` remains under
`frontend/src` — completing the milestone exit criteria.

## Approach

Migrated the 9 remaining files to TS (all reusing `api.ts` + earlier-ticket types):

- `routes/propertyPaths.js` → `.ts` — path/link helpers; typed `LinkableProperty`. This
  removes the last `any` seam feeding `MapView`/`App` (both now get `string | null` from
  `linkIdForProperty` / `boolean` from `isPropertiesSurface`).
- `hooks/useCompareSelection.js`, `usePropertiesPagination.js`, `usePropertiesFiltersState.js`
  → `.ts` — the BIN-141-extracted hooks, with exported result interfaces. `buildListQueryFilters`
  returns a typed `PropertyFilterOptions`; `applyFilters` narrows the loose saved-search blob.
- `components/properties/{PropertiesFilterBar,PropertiesPagination,PropertiesResultsGrid,PropertyCard}.jsx`
  → `.tsx` — explicit prop interfaces; setters typed as `Dispatch<SetStateAction<…>>`,
  handlers as `SyntheticEvent`; `PropertyCard` reuses `Property`/`PropertyListing` and the
  BIN-161 score/listing helpers.
- `pages/Properties.jsx` → `.tsx` — the orchestrator: ~30 typed `useState`s (`PaginatedProperties`,
  `SavedSearchItem[]`, `Set<string>`, `Neighborhood[]`/`City[]`, …), typed router hooks, and
  typed compare/watchlist/favourite/export/saved-search handlers.

### Epic close

- Verified `find frontend/src -name '*.jsx' -o -name '*.js'` returns **nothing**, then removed
  `allowJs`/`checkJs` from `tsconfig.json`. (The root config files `vite.config.js`,
  `eslint.config.js`, `playwright.config.js` are Node configs outside `src` and excluded by
  `include: ["src"]`.) `.js` import specifiers still resolve to `.ts` sources — that is bundler
  module resolution, independent of `allowJs` — so no import specifiers changed.

### Notable typing decisions (behaviour-preserving)

- The **favourites projection** reshapes `FavouriteWithProperty` rows into partial `Property`
  objects for the shared `PropertyCard` (many fields absent; the card already guards them).
  Asserted as `Property[]` with a documented `as unknown as Property[]` at that one seam.
- `displayScore` now does `parseFloat(String(v))` (v may be a number) — same result.
- `PropertyCard` image `onError` uses `e.currentTarget` + an `instanceof HTMLElement` guard on
  the sibling placeholder (was `e.target.style` / `e.target.nextSibling.style`) — same effect,
  correctly typed.
- The `MapView.onToggleCompare` callback in Properties dropped its dead object-branch: MapView's
  typed contract only ever passes a `string` id, so the never-reached branch is gone (behaviour
  identical — it was unreachable in JS too).
- Strict `catch` → an `errMessage(e)` helper for the toast/error-state messages.

## Changes

```
 routes/propertyPaths.js                       -> .ts
 hooks/useCompareSelection.js                  -> .ts
 hooks/usePropertiesPagination.js              -> .ts
 hooks/usePropertiesFiltersState.js            -> .ts
 components/properties/PropertiesFilterBar.jsx -> .tsx
 components/properties/PropertiesPagination.jsx-> .tsx
 components/properties/PropertiesResultsGrid.jsx-> .tsx
 components/properties/PropertyCard.jsx        -> .tsx
 pages/Properties.jsx                          -> .tsx
 tsconfig.json                                 | removed allowJs/checkJs (migration complete)
```

## New Dependencies

None.

## How to Test

```bash
# from frontend/:
npx tsc --noEmit    # clean under strict, allowJs removed
npm run lint        # clean
npm run build       # vite build succeeds

bash scripts/agent/validate.sh all   # build + Playwright e2e (esp. /properties) pass unchanged
```

`tsc --noEmit` passes under `strict: true` with `allowJs`/`checkJs` **removed**; `eslint .`
passes; `vite build` succeeds; all 83 Playwright e2e specs pass unchanged.

## Notes / Follow-ups

- **Epic BIN-160 (v0.11) complete** — every file under `frontend/src` is now `.tsx`/`.ts` and
  the gradual-migration `tsconfig` accommodation is gone; the whole SPA type-checks under
  `strict`.
- Pre-existing follow-up carried through the epic (from BIN-161): the pre-commit
  `forbid-hardcoded-secrets` hook still scans only `*.js`/`*.jsx`. Now that **all** SPA source
  is `.ts`/`.tsx`, that hook no longer covers any app source — worth a small housekeeping
  ticket. — fix hint: add `--include="*.ts" --include="*.tsx"` to the hook entry in
  `.pre-commit-config.yaml` (the migrated files contain no secrets; this is scan-coverage
  hygiene, not an active leak).
