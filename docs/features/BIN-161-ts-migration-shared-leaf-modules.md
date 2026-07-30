# TS migration: shared leaf modules — type i18n, labels, savedSearchFilters, utils

> Feature branch: `feat/bin-161-ts-migration-shared-leaf-modules-i18n-labels` · Linear: `BIN-161` · Status: implemented

## Problem

BIN-140 (v0.10) committed the frontend to an incremental TypeScript migration, but only
migrated `api.js` → `api.ts`, leaving the rest of `frontend/src` as `.js`/`.jsx` under a
gradual `tsconfig.json` (`allowJs: true`, `checkJs: false`). The v0.11 epic (BIN-160)
finishes that migration.

This is the **first** ticket in the epic. The shared *leaf* modules — the i18n catalog,
formatters, display-label helpers, saved-search wire mappers, and primary-listing/score
utilities — are imported by nearly every component and page. Typing them first prevents
`any` from leaking downstream when the consuming components/pages are migrated in later
tickets (BIN-162…BIN-165).

## Approach

- Renamed the 7 pure-logic `.js` modules to `.ts` with real types (no blanket `any`),
  reusing the interface conventions already established in `api.ts` (e.g. importing
  `ListingType` from `api.ts` in `utils/scores.ts`).
- **Import specifiers left untouched.** Consumers already import these modules with
  explicit `.js` extensions (e.g. `import { t } from './i18n/index.js'`), and both TS
  (`moduleResolution: "bundler"`) and Vite resolve a `.js` specifier to the `.ts` source.
  This is the same resolution `api.ts` already relies on, so **no consumer file changed** —
  keeping this a genuinely typing-only, zero-behaviour-change PR.
- `tsconfig.json` left unchanged (still gradual/`allowJs`, per the acceptance criteria) —
  the `allowJs`/`checkJs` accommodation is only removed once nothing `.jsx`/`.js` remains,
  at the end of the epic.
- Modelled loose runtime shapes precisely rather than with `any`: a recursive
  `MessageNode`/`Catalog` type for the nested i18n JSON; a structural `ListingLike` /
  `PropertyLike` subset for the primary-listing helpers; a `ScoredProperty` interface that
  extends the base scores with the dual rent/sale variants (`combined_score_rent`, … —
  BIN-83) that `api.ts`'s `Property` omits; `Record<string, unknown>` (`FilterMap`) for the
  camelCase↔snake_case saved-search blobs.

### Scope note — `i18n/LocaleContext.jsx`

The epic's wave-1 line item names the `i18n/` directory, but `LocaleContext.jsx` is a React
**provider component** (JSX) that depends on `ToastProvider.jsx` (`useToast`), not a pure
leaf module — and BIN-161's acceptance criteria say "`.js`→`.ts`". Migrating it here would
mean a `.tsx` importing an un-migrated `.jsx` (making `useToast` transitionally `any`) and
pulls component concerns into a leaf-module ticket. It is therefore **deferred to BIN-163**
(presentational components), alongside the `ToastProvider` it depends on. BIN-163's Linear
scope was updated to include it so it is not orphaned before the milestone exit criteria
("every file under `frontend/src` is `.tsx`/`.ts`").

## Changes

Files touched (all under `frontend/src`):

```
 i18n/index.js        -> i18n/index.ts        | Typed catalog (MessageNode/Catalog), t(), label/reasoning helpers
 i18n/activeLocale.js -> i18n/activeLocale.ts | Typed module-level active-locale accessor
 i18n/format.js       -> i18n/format.ts       | Typed number/date/currency formatters (DateLike)
 labels.js            -> labels.ts            | Typed platform/property-type labels + TranslateFn/PropertyTypeOption
 savedSearchFilters.js-> savedSearchFilters.ts| Typed camelCase<->snake_case wire mappers (FilterMap)
 utils/primaryListing.js -> utils/primaryListing.ts | Typed primary-listing helpers (ListingLike/PropertyLike)
 utils/scores.js      -> utils/scores.ts      | Typed filter-aware score selection (ScoredProperty)
```

No consumer files changed (see Approach — `.js` specifiers resolve to `.ts`).

## New Dependencies

None.

## How to Test

Behaviour is unchanged — this is a compile-time-only migration. The existing gates are the
lock:

```bash
# from frontend/: strict typecheck of the migrated modules (no errors)
npx tsc --noEmit
npm run lint

# full CI gate — vite build + Playwright e2e must pass unchanged
bash scripts/agent/validate.sh all
```

`tsc --noEmit` passes clean under `strict: true`; `eslint .` passes; `vite build` succeeds;
all 83 Playwright e2e specs pass unchanged.

## Notes / Follow-ups

- Next in the epic: BIN-162 (hooks: `useAlerts`, `useSystemStatus`), then BIN-163
  (presentational components — now including `i18n/LocaleContext.jsx`, see Scope note),
  BIN-164 (Dashboard/ScraperControl), BIN-165 (`Properties.jsx`).
- The pre-commit `forbid-hardcoded-secrets` hook greps `--include="*.js" --include="*.jsx"`
  but not `*.ts`/`*.tsx`; as the migration progresses the secret scan will stop covering
  migrated files. Worth extending the hook's include globs in a later epic ticket. — fix hint:
  add `--include="*.ts" --include="*.tsx"` to the hook entry in `.pre-commit-config.yaml`.
