# Frontend TypeScript: tooling + api.js migration (scoped)

> Feature branch: `feat/ts-tooling-migrate-api` · Linear: `BIN-140` · Status: implemented

## Problem

`frontend/package.json` listed `@types/react`/`@types/react-dom` as devDependencies, but every source file was `.jsx`/`.js` and no `tsconfig.json` existed — the type packages were dead weight, consumed by nothing. `Properties.jsx` (1264 lines) and `api.js` (481 lines), the app's entire surface, had zero compile-time type safety on API response shapes: a backend field rename/removal was only ever caught at runtime in the browser.

## Approach

Decision (recorded on the ticket, 2026-07-29): **migrate, but scoped to tooling + `api.js` only** for this ticket. A full `frontend/src` migration is XL and explicitly deferred to a follow-up epic (see Notes / Follow-ups) — attempting it here would balloon well past this ticket's intent.

- Added `frontend/tsconfig.json` with `allowJs: true` + `checkJs: false` so `.jsx`/`.js` and `.tsx`/`.ts` can coexist indefinitely — existing JS files are still parsed (for the module graph/resolution) but never type-checked, so nothing pre-existing needed to satisfy `strict` on day one. `strict: true` is set, but since `checkJs` is off it only binds the files that actually opt in by being `.ts`/`.tsx` — a deliberately gradual, not all-or-nothing, config. `moduleResolution: "Bundler"` + `noEmit: true` (Vite/esbuild does the real transpile; `tsc` here is type-checking only, invoked ad hoc via `npx tsc --noEmit`, not wired into a build/CI gate in this ticket).
- Migrated `frontend/src/api.js` → `api.ts` via `git mv` (preserves history), adding real interfaces for every request/response shape it touches — `Property`, `PropertyDetail`, `PaginatedProperties`, `WatchlistItem`, `FavouriteWithProperty`, `SavedSearchItem`, `PipelineStatus`, `EnrichmentRerunOptions`, etc. — hand-written to mirror `src/api/schemas.py` (`PropertyModel`, `PropertyDetailModel`, `PaginatedPropertiesResponse`, ...) plus the watchlist/favourites/saved-searches routers' inline Pydantic models, rather than a generated client — this is the highest-bug-catch-value single file (the backend/frontend seam), and hand types make the mirroring intent to `schemas.py` legible in review.
- Left permissive `Record<string, unknown>` shapes for endpoints whose payloads are already loosely typed on the backend (`Dict[str, Any]` in FastAPI — e.g. `SystemStatus.database`/`redis`/`ollama`/`workers`, `PipelineStatus.scrapers_status`/`ai_metrics`) rather than inventing structure the backend itself doesn't guarantee.
- Extended the BIN-139 flat ESLint config: added `typescript-eslint`'s non-type-checked `recommended` preset (`tseslint.configs.recommended`, mapped with `files: ['**/*.{ts,tsx}']` since the preset's own array doesn't scope `files` on every entry — combining it as-is in a mixed JS/TS project would've applied the TS parser repo-wide) plus a second `**/*.{ts,tsx}` block carrying the same React/hooks/refresh rules as the `.jsx` block, with `@typescript-eslint/no-unused-vars` replacing the base `no-unused-vars` (TS-aware, understands overloads/types). Non-type-checked preset on purpose — consistent with the "gradual tooling, not big-bang strict" tone of the tsconfig.
- No Vite config changes needed: `@vitejs/plugin-react` + esbuild already transpile `.ts`/`.tsx` out of the box; `vite.config.js` stays `.js` (not touched — out of scope).
- Verified (didn't assume) that the 9 existing `from '../api.js'` import sites resolve correctly to the new `api.ts` — Vite's resolver transparently maps a `.js` import specifier to an on-disk `.ts` file (the standard pattern for gradual TS adoption; no import site needed to change). Confirmed via `npm run build` (2385 modules, no resolution errors) and the full Playwright e2e suite.
- Added `typescript` + `typescript-eslint` devDependencies. `typescript-eslint`'s peer range pinned the resolved `typescript` to `6.0.3` (not the newly-released `7.x` line) — same "plugin peer range caps the tool version" pattern BIN-139 hit with `eslint@10`.

## Changes

Files touched:

```
 frontend/tsconfig.json      | NEW — gradual allowJs/checkJs:false TS config
 frontend/src/api.js         | RENAMED (git mv) -> api.ts
 frontend/src/api.ts         | NEW (from api.js) — added typed request/response interfaces for every export
 frontend/eslint.config.js   | extended with typescript-eslint recommended, scoped to **/*.{ts,tsx}
 frontend/package.json       | new devDependencies: typescript, typescript-eslint
 frontend/package-lock.json  | regenerated for the new devDependencies
 docs/features/BIN-140-ts-tooling-migrate-api.md | NEW — this doc
```

## New Dependencies

`frontend/package.json` devDependencies added: `typescript@^6.0.3`, `typescript-eslint@^8.65.0`. `@types/react`/`@types/react-dom` (already present) are now genuinely consumed — kept, not removed. No production/runtime dependencies changed.

## How to Test

1. Type-check the migrated file directly:
   ```bash
   cd frontend && npx tsc --noEmit
   ```
   Expect a clean run — no output, exit 0.
2. Lint (now covers `.ts`/`.tsx` too):
   ```bash
   cd frontend && npm run lint
   ```
3. Build + full gate (build, lint, unit/integration/contract, Playwright e2e):
   ```bash
   bash scripts/agent/validate.sh all
   ```
   All 70 Playwright e2e specs pass unchanged — this is a typing/tooling change, not a logic change (behavior lock per ticket AC).

## Notes / Follow-ups

- **Follow-up epic (to be created under BIN-128): migrate the rest of `frontend/src`.** Rough breakdown for sizing into separate tickets:
  - `pages/Properties.jsx` (1264 lines, ~36 `useState`) — highest value and highest risk; likely wants to land *after* **BIN-141** (structural split into sub-components) so each smaller file converts independently instead of one XL `.tsx` diff.
  - `pages/Dashboard.jsx`, `pages/ScraperControl.jsx` — medium, self-contained pages.
  - `components/PropertyModal.jsx`, `components/CompareView.jsx`, `components/CredentialGate.jsx`, `components/ToastProvider.jsx`, `components/ErrorBoundary.jsx` — small/medium, mostly presentational; good early wins once `Properties.jsx` no longer blocks on shared prop shapes.
  - `hooks/useAlerts.js`, `hooks/useSystemStatus.js` — trivial, good first PR to prove the per-file conversion pattern before touching bigger pages.
  - `i18n/` (`index.js`, `activeLocale.js`, `LocaleContext.jsx`) and `labels.js`, `savedSearchFilters.js`, `utils/` — shared/leaf modules; typing these earlier (before the pages that consume them) reduces `any` leakage into the page conversions.
  - `routes/` — thin, convert alongside whichever page each route wraps.
  - Each converted file can reuse the interfaces already defined in `api.ts` (`Property`, `PropertyDetail`, etc.) instead of re-deriving shapes.
- `checkJs: false` means existing `.jsx`/`.js` files get zero type-checking benefit yet — that's intentional for this ticket's scope, not an oversight; it flips on a file at a time as each is renamed `.tsx`/`.ts` in the follow-up epic.
- `tsc --noEmit` is not wired into `validate.sh` or CI in this ticket (build/lint were the ACs) — worth adding as a fast gate once more of the tree is typed, so type errors fail fast rather than only showing up in editor tooling.
- Parent epic: BIN-128 (2026-07-29 technical debt remediation audit). Blocks **BIN-141** (split `Properties.jsx`) per the epic's ordering note, though BIN-141 can proceed as a plain structural split regardless of migration pace once this merges.
