# maplibre-gl 5 → 6 upgrade — named-import migration + tile-independent map readiness

> Feature branch: `feat/maplibre-gl-v6` · Linear: `BIN-271` · Status: implemented

## Problem

Dependabot PR #33 bumped `maplibre-gl` 5.24.0 → 6.x. maplibre-gl v6 ships breaking
changes that broke the build and the map e2e tests:

1. **Default export removed** (v6 is ESM-only). `MapView.tsx` did
   `import maplibregl, { … } from 'maplibre-gl'`, which no longer type-checks
   (`TS1192: Module … has no default export`) — the whole frontend build failed.
2. **`idle` no longer fires while raster tiles are pending.** The map readiness
   signal (`data-map-ready`) and the marker-sync effect keyed off `idle` /
   `isStyleLoaded()`. Under v6, `isStyleLoaded()` stays `false` while raster tiles
   load, and `idle` never fires when tiles never succeed — which is exactly the test
   environment (the OSM tile host blocks headless/automated requests) and any
   offline/blocked-tile production scenario. The readiness attribute hung forever and
   the 5 `compare-map-select` e2e tests timed out.

## Approach

- **Named imports.** Replaced the default import with named value imports
  (`Map as MLMap`, `Marker as MLMarker`, `Popup`, `NavigationControl`) plus the
  existing type-only imports, and updated the four `new maplibregl.X(...)` call sites.
  Chosen over a `import * as maplibregl` namespace import to keep the existing
  `MLMap`/`MLMarker` type aliases and minimise churn.
- **Readiness keyed off `load`, not `idle`.** Added a `loadedRef` set `true` in the
  map's `load` handler. Both the `data-map-ready` signal and the marker-sync effect
  now gate on `loadedRef` instead of `isStyleLoaded()` + an `once('idle')` fallback.
  `load` fires once the style is parsed and the first frame renders — independent of
  whether external tiles ever load — so the map is usable offline / when tiles are
  blocked. This preserves the BIN-189 intent (never add sources/layers/markers before
  the style is ready) while removing the tile-dependent hang.

## Changes

Files touched:

```
 frontend/package.json                       | CHANGED — maplibre-gl ^5.24.0 → ^6.1.0
 frontend/package-lock.json                  | CHANGED — lockfile for maplibre-gl 6.1.0
 frontend/src/components/MapView.tsx         | CHANGED — named imports; load-gated readiness + marker sync
 docs/features/BIN-271-maplibre-gl-v6.md     | NEW — this doc
```

## New Dependencies

None new — `maplibre-gl` major-version bump (5 → 6) only.

## How to Test

```bash
cd frontend && npx tsc --noEmit && npm run build && npm run lint
npm run test:e2e   # tests/e2e/compare-map-select.spec.js — 5 map tests, previously failing
```

The `compare-map-select` suite is the regression lock: those tests run with the OSM
tile host effectively unavailable (only `**/api/**` is mocked; tile requests are not
served), so they exercise the tile-independent readiness path and fail on plain v6
without the `load`-gating fix.

## Notes / Follow-ups

- Supersedes Dependabot PR #33 (closed as superseded — Dependabot only bumped the
  version and could not carry the required `MapView.tsx` code changes).
- Dev-server only: Vite's dep optimizer logs a benign warning about
  `maplibre-gl-worker.mjs` under v6; the production build and e2e are unaffected. If it
  ever becomes noisy, add `maplibre-gl` to `optimizeDeps.exclude` in `vite.config`.
