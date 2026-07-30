# TS migration: pages + app shell — Dashboard, ScraperControl, App, main

> Feature branch: `feat/bin-164-ts-migration-dashboardjsx-and-scrapercontroljsx` · Linear: `BIN-164` · Status: implemented

## Problem

Fourth ticket (Wave 3) of the v0.11 frontend TypeScript migration epic (BIN-160), after leaf
modules (BIN-161), hooks (BIN-162), and components (BIN-163). Migrates the two medium pages
plus the app shell/entry, leaving only `Properties.jsx` + its sub-tree for BIN-165.

## Approach

Migrated 4 files to TS with typed props/state, reusing `api.ts` response types and the
`SystemStatus`/hook types from earlier tickets:

- `main.jsx` → `main.tsx` — trivial ReactDOM entry (`getElementById('root')!`).
- `App.jsx` → `App.tsx` — providers + react-router-dom v7 routing; typed `NavEntry`,
  `NavItem`/`ServiceDot` prop interfaces. Passes `status: SystemStatus | null` to `Dashboard`.
- `pages/Dashboard.jsx` → `.tsx` — pipeline charts, alerts, service tiles, selective
  enrichment form. Typed state (`RerunForm` with `EnrichmentMode`/`EnrichmentStages`,
  `HistoryPoint[]`, `PipelineStatus | null`).
- `pages/ScraperControl.jsx` → `.tsx` — scrape launcher, worker controls, schedule table,
  activity log. Typed state (`PlatformRow[]`, `ScheduleRow[]`, `LogEntry[]`, a local
  `ScraperPipeline` for the non-null initial pipeline object).

### Typing the loose API seam

`api.ts` intentionally types many responses as `Record<string, unknown>` (the backend seam:
`SystemStatus` sub-objects, `PipelineStatus.proxy`/`ai_metrics`/`scrapers_status`,
`AlertItem`, `ScheduleEntry`, `PlatformInfo`, `AdminActionResult`). Rather than widen those
shared wire types, each page declares **local "view" interfaces** (`StatusView`,
`ProxyInfo`, `AiMetricsView`, `AlertRow`, `ScraperPipeline`, `ScheduleRow`, `PlatformRow`, …)
and narrows the loose values at the read boundary with a single `as` cast each. This keeps
the intentional wire looseness in `api.ts` while giving the page bodies full type safety.

### One shared-type change (behaviour-preserving)

`i18n/index.ts` — widened `TranslateParams` from `Record<string, string | number>` to also
allow `null | undefined`. The interpolator already renders a null/undefined value as the
literal `{key}` placeholder, so this is **exactly the current runtime behaviour** — it just
lets the pages forward optional fields (e.g. `pct: alert.drop_pct?.toFixed(1)`) without
coercing them to `''` first (which would have *changed* the rendered output). This removes
~20 coercions across the two pages and is backward compatible (existing `string`/`number`
callers unaffected).

### Behaviour-preserving TS adjustments

- Strict `catch (e: unknown)` → a small `errMessage(e)` helper (`e instanceof Error`), used
  wherever a message was read for a toast/log line. The api layer throws `Error`s, so text
  is unchanged.
- `rerunForm.mode`/`stages` typed as `EnrichmentMode`/`EnrichmentStages`; the `<select>`
  `onChange` casts `e.target.value` to the union (values are the fixed option set).

## Changes

```
 main.jsx                  -> main.tsx           | ReactDOM entry
 App.jsx                   -> App.tsx            | providers + router; NavEntry/NavItem/ServiceDot typed
 pages/Dashboard.jsx       -> pages/Dashboard.tsx| typed state + local API view interfaces
 pages/ScraperControl.jsx  -> pages/ScraperControl.tsx | typed state + local ScraperPipeline/ScheduleRow/…
 i18n/index.ts             | TranslateParams widened to allow null|undefined (behaviour-preserving)
```

No consumer files changed (`.jsx`/`.js` specifiers resolve to the new `.tsx`; verified by a
clean `vite build` — including the still-`.jsx` `Properties.jsx` that `App.tsx` lazy-imports).

## New Dependencies

None. (react-router-dom v7 ships its own types.)

## How to Test

Behaviour is unchanged — compile-time-only migration.

```bash
# from frontend/:
npx tsc --noEmit    # clean under strict
npm run lint        # clean
npm run build       # vite build succeeds

bash scripts/agent/validate.sh all   # build + Playwright e2e pass unchanged
```

`tsc --noEmit` passes under `strict: true`; `eslint .` passes; `vite build` succeeds; all 83
Playwright e2e specs pass unchanged (covers Dashboard charts/enrichment and Scraper Control
critical paths).

## Notes / Follow-ups

- Final epic ticket: **BIN-165** — `Properties.jsx` + `components/properties/*` + its three
  hooks + `routes/propertyPaths.js`; once it lands, remove `tsconfig.json`'s
  `allowJs`/`checkJs` after verifying nothing `.jsx`/`.js` remains under `frontend/src`.
- Pre-existing follow-up (BIN-161): the pre-commit `forbid-hardcoded-secrets` hook still
  scans only `*.js`/`*.jsx`. — fix hint: add `--include="*.ts" --include="*.tsx"`.
