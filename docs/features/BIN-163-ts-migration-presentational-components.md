# TS migration: presentational components — type the shared component layer

> Feature branch: `feat/bin-163-ts-migration-smallmedium-presentational-components` · Linear: `BIN-163` · Status: implemented

## Problem

Third ticket (Wave 2) of the v0.11 frontend TypeScript migration epic (BIN-160), after leaf
modules (BIN-161) and hooks (BIN-162). This migrates the shared presentational component
layer that the pages (BIN-164) and `Properties.jsx` (BIN-165) consume, so those later
tickets inherit typed props/context instead of `any`.

## Approach

Migrated 8 `.jsx` components to `.tsx` with **explicit prop interfaces** (the chosen
convention — no `React.FC`), reusing `api.ts` response types throughout:

- `ToastProvider.tsx` — establishes the toast contract (`ToastType`, `ToastOptions`,
  `ShowToast`) consumed everywhere `useToast()` is called.
- `i18n/LocaleContext.tsx` — provider component (moved here from BIN-161 because it depends
  on `ToastProvider`'s `useToast`). Exposes `LocaleContextValue` and the `TFunction` type
  reused by `CredentialGate`, `CompareView`, `MapView`, etc.
- `ErrorBoundary.tsx` — the one class component; typed `Props`/`State`.
- `CredentialGate.tsx`, `SearchableMultiSelect.tsx` — form/interaction components with typed
  events and a `SmsOption`/`SearchableMultiSelectProps` public API.
- `CompareView.tsx`, `PropertyModal.tsx` — the data-heavy views; reuse `Property` /
  `PropertyDetail` / `PriceHistoryPoint` and type the Recharts data locally (`ChartPoint`).
- `MapView.tsx` — MapLibre GL; typed with maplibre-gl's own types (`Map`, `Marker`,
  `GeoJSONSource`, `MapLayerMouseEvent`, `StyleSpecification`) + `geojson` `FeatureCollection`
  /`Feature`/`Point`. A `hasCoords` type-predicate narrows `lat`/`lon` for the marker/feature
  builders; the dynamic map feature `properties` stay loose at the library boundary
  (`GeoJsonProperties`), which is inherent, not a blanket `any`.

**No consumer changes.** Existing importers use `.jsx`/`.js` specifiers that resolve to the
new `.tsx`/`.ts` sources under both TS `bundler` resolution and Vite (verified by a clean
`vite build` of the still-`.jsx` `App.jsx`/pages/`properties/*` against the migrated files).

### Small supporting type changes (necessary, additive)

Two shared-type touch-ups were required to type the components without `any` or casts:

- `api.ts` — added the **optional** listing-type-aware fields the modal/compare/map already
  read but the schema didn't model: `combined_score_rent/sale`, `stat_score_rent/sale`,
  `z_score_rent/sale`, `percentile_rank_rent/sale`, `price_per_m2_rent/sale`,
  `neighborhood_mean_rent/sale` on `Property`, and an optional legacy `platform_id` on
  `PropertyListing` (used only for React keys). All additive/optional — non-breaking, and
  they also unblock BIN-164/165.
- `utils/primaryListing.ts` — made `groupListings` generic (`<T extends ListingLike>`) so a
  caller passing `PropertyListing[]` gets `PropertyListing[]` groups back (the modal reads
  `base_price`/`condo_fee`/`iptu`/…), instead of a widened `ListingLike`. Backward compatible.
- Added `src/vite-env.d.ts` (`/// <reference types="vite/client" />`) — the standard Vite
  ambient types, needed now that a `.tsx` file (`MapView`) imports a `.css` side-effect.

### Behaviour-preserving TS adjustments

- `container.style = '...'` string assignments in MapView's DOM popup became
  `container.style.cssText = '...'` (identical effect; `.style` is read-only in TS).
- Image `onError={e => e.target.style...}` → `e.currentTarget` (same node, correctly typed).
- Strict `catch (err: unknown)` → `err instanceof Error ? err.message : …` where a message
  was read (CredentialGate, LocaleContext, CompareView). The api layer throws `Error`s, so
  the surfaced text is unchanged.
- Optional-array length guards use `(x?.length ?? 0) > 0` (TS-safe, same truthiness).

## Changes

```
 components/ErrorBoundary.jsx        -> .tsx  | Typed class ErrorBoundary (Props/State)
 components/ToastProvider.jsx        -> .tsx  | ToastType/ToastOptions/ShowToast contract
 components/CredentialGate.jsx       -> .tsx  | Typed form events
 components/SearchableMultiSelect.jsx-> .tsx  | SmsOption / SearchableMultiSelectProps
 components/CompareView.jsx          -> .tsx  | Typed compare table + Recharts (ChartPoint)
 components/PropertyModal.jsx        -> .tsx  | PropertyDetail + VisualAnalysis/SentimentAnalysis/StatAnalysis
 components/MapView.jsx              -> .tsx  | maplibre-gl + geojson typed
 i18n/LocaleContext.jsx              -> .tsx  | LocaleContextValue / TFunction (moved from BIN-161)
 api.ts                              | additive optional dual-score/price fields + platform_id
 utils/primaryListing.ts            | groupListings made generic
 src/vite-env.d.ts                  | NEW — vite/client ambient types
```

No consumer files changed.

## New Dependencies

None. (Uses type packages already present: `maplibre-gl` self-types, `recharts` types,
`@types/geojson`, `@types/react`.)

## How to Test

Behaviour is unchanged — compile-time-only migration.

```bash
# from frontend/:
npx tsc --noEmit    # clean under strict
npm run lint        # clean
npm run build       # vite build succeeds (also proves .jsx->.tsx resolution)

# full CI gate — build + Playwright e2e pass unchanged
bash scripts/agent/validate.sh all
```

`tsc --noEmit` passes under `strict: true`; `eslint .` passes; `vite build` succeeds; all 83
Playwright e2e specs pass unchanged.

## Notes / Follow-ups

- Remaining epic (BIN-160): BIN-164 (Dashboard/ScraperControl + `App.jsx`/`main.jsx` shell),
  BIN-165 (`Properties.jsx` + `properties/*` + its hooks + `routes/`), which removes the
  `allowJs`/`checkJs` accommodation once nothing `.jsx`/`.js` remains.
- MapView's map-feature `properties` are typed `GeoJsonProperties` (loose) at the MapLibre
  boundary — tightening would require a source-typed GeoJSON wrapper, out of scope here.
- Pre-existing follow-up (from BIN-161): the pre-commit `forbid-hardcoded-secrets` hook still
  scans only `*.js`/`*.jsx`; migrated `.tsx`/`.ts` files fall out of that scan. — fix hint:
  add `--include="*.ts" --include="*.tsx"` to the hook in `.pre-commit-config.yaml`.
