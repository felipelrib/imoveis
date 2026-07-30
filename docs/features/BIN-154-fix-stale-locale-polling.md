# Fix stale locale in Dashboard/ScraperControl polling loops after language switch

> Feature branch: `fix/stale-locale-polling` · Linear: `BIN-154` · Status: implemented

## Problem

Several `useEffect(() => {...}, [])` polling loops close over `locale`/`t` from the render that first mounted them and never re-subscribe. `MapView`'s map-popup content correctly reads `tRef.current`/`localeRef.current` at click-time (a ref pattern introduced for that exact reason), but the page-level pollers in `Dashboard.jsx` and `ScraperControl.jsx` didn't consistently use it.

Concretely, `ScraperControl.jsx`'s "Poll pipeline status" effect (`recent_scrape_runs` → activity-log entries, polled every 3s) is deliberately kept at `useEffect(..., [])` — an inline comment explains that adding `logScrapeRun` (a plain, unmemoized function recreated every render) to the deps would tear down and recreate the 3s interval on every render instead of every 3s. That's the right call for the interval, but it meant the closure's `t`/`locale` reads were frozen at mount: after a mid-session locale switch, new scrape-run log lines kept rendering in the *old* locale indefinitely (until the component unmounted), while the rest of the UI (including the sidebar locale switcher itself) switched immediately.

`Dashboard.jsx`'s pipeline history/tip poll (chart x-axis timestamps, polled every 8s) already carried `locale` in its effect's dependency array (landed incidentally via the BIN-139 ESLint flat-config / exhaustive-deps pass), so it re-subscribes and reads fresh `locale` on every switch — verified with a regression test below, but no production code change was needed there.

## Approach

- `ScraperControl.jsx`: added `tRef`/`localeRef` (mirroring `MapView.jsx`'s existing `tRef`/`localeRef` pattern) plus two small sync effects (`useEffect(() => { tRef.current = t }, [t])` / `useEffect(() => { localeRef.current = locale }, [locale])`). `logScrapeRun` — only ever invoked from the mount-only poll effect's async callback, never during render — now reads `tRef.current` for translations and computes its timestamp via `formatTime(new Date(), localeRef.current)` directly, instead of the render-scoped `t`/`ts()`. This keeps the interval un-torn-down (still `[]` deps, same rationale as before) while making the log lines it produces always reflect the *current* locale.
  - `ts()` itself (used by several event handlers and the initial `logs` state) is left reading `locale` directly — those call sites already get a fresh `locale` on every render, and `react-hooks/refs` forbids reading `ref.current` during render (the initial `logs` `useState(() => ...)` lazy initializer runs at render time, so it can't safely call a ref-based `ts()`).
  - The "poll schedule status" effect already carried `t` in its deps (also from BIN-139) and needed no change — it already tears down/restarts on locale switch.
- `Dashboard.jsx`: no production change — its pipeline poll effect already depends on `[locale]`, so a locale switch tears down and restarts the poll, and the next tick's `formatTime(new Date(), locale)` / `formatTime(p.ts, locale)` calls already use the fresh value. (`historyLoaded.current` persisting across the effect's remount means the persisted-history reload is skipped on restart, which is fine — only new poll ticks need to reflect the new locale, not the already-rendered history.)

## Changes

Files touched:

```
frontend/src/pages/ScraperControl.jsx           | Poll pipeline status effect: logScrapeRun now reads t/locale via tRef/localeRef instead of the mount-frozen closure values; comment updated to explain why.
frontend/tests/e2e/locale-stale-polling.spec.js | NEW — regression spec: switch locale mid-session, trigger a poll tick, assert new content (scraper activity log wording; dashboard chart x-axis timestamp format) renders in the new locale.
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted:

```bash
cd frontend && PLAYWRIGHT_PORT=5188 npx playwright test tests/e2e/locale-stale-polling.spec.js
```

Both specs were verified to **fail** against the pre-fix code (temporarily reverting the `ScraperControl.jsx` ref usage back to plain `t`/`locale`, and temporarily reverting `Dashboard.jsx`'s effect deps from `[locale]` to `[]`) before confirming they pass with the fix in place — locking the exact regression described in BIN-154.

Manual check: open the app, switch the sidebar language selector mid-session, trigger a scrape (or wait for a schedule tick) and watch new Activity Log lines / chart x-axis ticks render in the newly-selected locale instead of the one active at page load.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- The map-popup "rare mid-session locale switch may need a map remount" caveat noted in `docs/features/BIN-99-full-ui-string-catalog.md` is a separate, already-accepted limitation (chrome around the popup, not the ref-read content itself) and is unaffected by this fix.
- BIN-155 (hide number-input spinners) also touches `ScraperControl.jsx` and was intentionally sequenced to land after this ticket to avoid a merge conflict.
