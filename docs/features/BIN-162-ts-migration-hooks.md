# TS migration: hooks — type useAlerts and useSystemStatus

> Feature branch: `feat/bin-162-ts-migration-hooks-usealerts-usesystemstatus` · Linear: `BIN-162` · Status: implemented

## Problem

Second ticket of the v0.11 frontend TypeScript migration epic (BIN-160), after the leaf
modules landed in BIN-161. The two polling hooks — `useAlerts` and `useSystemStatus` — are
small, self-contained, and consume `api.ts`'s already-typed response functions, so they are
a clean early proof-of-pattern for hook migration.

## Approach

- Renamed `hooks/useAlerts.js` → `.ts` and `hooks/useSystemStatus.js` → `.ts` with typed
  params, state, and an explicit result interface each (`UseAlertsResult`,
  `UseSystemStatusResult`).
- Reused `api.ts` response types directly: `AlertItem[]` for the alerts state (from
  `fetchAlerts`) and `SystemStatus | null` for the status state (from `fetchStatus`),
  imported with inline `type` specifiers (`isolatedModules`-safe).
- `error` state typed `string | null`. The only behavioural-looking change is strict
  `catch` typing: `catch (err)` binds `err` as `unknown`, so `err.message` became
  `err instanceof Error ? err.message : String(err)`. All values thrown by the `api.ts`
  fetchers are `Error` instances, so the message shown is unchanged in practice — this only
  removes an unsafe `any` access.
- Consumers (`App.jsx`, `Dashboard.jsx`, `ScraperControl.jsx`) already import via `.js`
  specifiers that resolve to the `.ts` source — **no consumer file changed**.

## Changes

Files touched (all under `frontend/src/hooks`):

```
 useAlerts.js       -> useAlerts.ts       | Typed alerts polling hook (AlertItem[], UseAlertsResult)
 useSystemStatus.js -> useSystemStatus.ts | Typed system-status polling hook (SystemStatus|null, UseSystemStatusResult)
```

No consumer files changed (`.js` specifiers resolve to `.ts`).

## New Dependencies

None.

## How to Test

Behaviour is unchanged — compile-time-only migration.

```bash
# from frontend/:
npx tsc --noEmit    # clean under strict
npm run lint        # clean

# full CI gate — vite build + Playwright e2e pass unchanged
bash scripts/agent/validate.sh all
```

## Notes / Follow-ups

- Remaining epic (BIN-160) tickets: BIN-163 (presentational components, incl.
  `i18n/LocaleContext.jsx`), BIN-164 (Dashboard/ScraperControl), BIN-165 (`Properties.jsx`).
- The other hooks under `hooks/` (`useCompareSelection`, `usePropertiesFiltersState`,
  `usePropertiesPagination`) were created by the BIN-141 `Properties.jsx` split and are
  scoped to migrate alongside `Properties.jsx` in **BIN-165**, not here — this ticket is
  explicitly just the two standalone polling hooks.
