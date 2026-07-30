# Frontend tooling: real ESLint config + commit package-lock.json

> Feature branch: `feat/frontend-eslint-lockfile` · Linear: `BIN-139` · Status: implemented

## Problem

`frontend/package.json`'s `lint` script was a no-op stub (`echo "eslint not yet configured" && exit 0`) with no ESLint config anywhere in `frontend/`. The CI/pre-commit "lint" step always reported success regardless of actual code quality, and — combined with plain JS (no TypeScript) — there was no static analysis of the frontend at all beyond Vite's build step. `frontend/package-lock.json` was believed to be uncommitted per the ticket description, which would have made `npm install` non-reproducible.

## Approach

- Added a flat ESLint 9 config (`frontend/eslint.config.js`) — the modern config format, required since this repo's `eslint` had to stay on the `9.x` line (see below) and flat config is what `eslint.config.js` means for v9.
- Wired `js.configs.recommended` + `eslint-plugin-react` (`recommended` + `jsx-runtime`, since React 19's JSX transform means files don't `import React`) + `eslint-plugin-react-hooks` (`recommended`, includes the newer `set-state-in-effect` rule) + `eslint-plugin-react-refresh` (Vite HMR-purity warnings) + `globals` (browser/Node globals split by file glob — `src/**` gets browser globals, `vite.config.js`/`playwright.config.js`/`tests/**` get Node globals).
- Pinned `eslint@^9.39.5` / `@eslint/js@^9.39.1` rather than the newly-released `eslint@10`/`@eslint/js@10` — `eslint-plugin-react@7.37.5`'s peer range caps at `eslint@^9.7`, so installing the v10 line would have produced an unresolvable peer conflict (`npm install` failed with `ERESOLVE` until pinned back to the 9.x line that all plugins actually support).
- `react/prop-types` is off — this codebase is plain JS with no PropTypes anywhere (the TypeScript-vs-PropTypes decision is BIN-140, explicitly the next ticket in this chain); turning the rule on would have meant blanket-suppressing it everywhere, which is worse than not enabling it.
- Wired `"lint": "eslint ."` in `package.json`, matching what `scripts/agent/lint.sh` / CI already invoke (`npm run lint`) — no harness/CI script changes needed.
- Fixed every unused-variable/import finding for free (dead `taskId` state in `ScraperControl.jsx`, unused `React`/`useRef`/`useSystemStatus` imports, unused `error`/`i`/`e` catch-and-map params) and one real stale-closure bug (`Dashboard.jsx`'s pipeline-history effect was missing `locale` in its deps, so time labels pushed by the live poll would silently keep formatting in the locale active when the effect first mounted).
- Added two more real dependency-array fixes in `ScraperControl.jsx` (`t`, `showToast`) — both come from memoized hooks (`useLocale`'s `t` is `useCallback`-wrapped on `[locale]`; `useToast`'s `showToast` is `useCallback`-wrapped on `[removeToast]`), so adding them is free (effect re-runs only on the rare locale/provider-identity change, not every render).
- Everything else the first `eslint .` run flagged was suppressed **narrowly, per-line, with an inline reason** rather than fixed or disabled repo-wide — per the ticket's "fix real issues where cheap, suppress narrowly where a rule doesn't fit" guidance:
  - `react-hooks/set-state-in-effect` in `Properties.jsx` (4 call sites) and one in `ScraperControl.jsx` — all are effects that either sync polled/route-derived external state into local state, or call an intentionally-unmemoized `load()` helper. `Properties.jsx`'s `load()` closes over ~15 filter fields; wrapping it in `useCallback` to satisfy this rule (and the paired `exhaustive-deps` warning on the same effects) is exactly the kind of effect restructuring the sibling ticket **BIN-141** (split `Properties.jsx`) is scoped to do — attempting it here, in a lint-tooling ticket, with no dedicated regression tests for the pagination/filter-reload behavior, was judged too risky.
  - `react-refresh/only-export-components` in `ToastProvider.jsx` and `LocaleContext.jsx` — both co-locate a `Context`/`Provider` with a companion hook (`useToast`, `useLocale`, `useT`), the standard React pattern; splitting them into separate files purely to satisfy Fast-Refresh purity was judged not worth the churn for a dev-only HMR nicety.
- `frontend/package-lock.json` turned out to already be committed (kept in sync by prior Dependabot bump commits) — verified with `git ls-files`, so that AC item required no action, only re-generating/updating it for the new `devDependencies` this ticket adds (`eslint`, `@eslint/js`, `eslint-plugin-react`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals`).

## Changes

Files touched:

```
 frontend/eslint.config.js                  | NEW — flat ESLint 9 config (React + hooks + refresh + globals)
 frontend/package.json                      | lint script now runs `eslint .`; new devDependencies
 frontend/package-lock.json                 | regenerated for the new devDependencies (already committed pre-ticket)
 frontend/src/components/ErrorBoundary.jsx  | drop unused `error` param on getDerivedStateFromError
 frontend/src/components/PropertyModal.jsx  | drop unused `i` index param in listings map
 frontend/src/components/ToastProvider.jsx  | narrow suppress: react-refresh/only-export-components on useToast
 frontend/src/hooks/useSystemStatus.js      | drop unused `useRef` import
 frontend/src/i18n/LocaleContext.jsx        | drop unused `React` import; narrow suppress on useLocale/useT
 frontend/src/pages/Dashboard.jsx           | drop unused useSystemStatus import; fix missing `locale` dep (real stale-closure fix)
 frontend/src/pages/Properties.jsx          | narrow suppress: set-state-in-effect / exhaustive-deps (BIN-141-scoped refactor)
 frontend/src/pages/ScraperControl.jsx      | remove dead `taskId` state, unused catch bindings; fix `t`/`showToast` deps; narrow suppress on status-mirroring effect
 docs/features/BIN-139-frontend-eslint-lockfile.md | NEW — this doc
```

## New Dependencies

`frontend/package.json` devDependencies added: `eslint@^9.39.5`, `@eslint/js@^9.39.1`, `eslint-plugin-react@^7.37.5`, `eslint-plugin-react-hooks@^7.0.1`, `eslint-plugin-react-refresh@^0.5.3`, `globals@^17.8.0`. No production/runtime dependencies changed.

## How to Test

1. Run lint directly:
   ```bash
   cd frontend && npm run lint
   ```
   Expect a clean run (0 errors, 0 warnings) — confirms the config finds nothing new without needing suppressions beyond what's documented above.
2. Confirm the lockfile installs reproducibly and the app still builds:
   ```bash
   cd frontend && npm ci && npm run build
   ```
3. Full gate (lint runs as part of `run_lint` in every scope):
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- **BIN-140** (frontend TypeScript decision) and **BIN-141** (split `Properties.jsx`) were both explicitly blocked on this ticket landing — real lint tooling now exists for both to build on.
- The `react-hooks/set-state-in-effect` suppressions in `Properties.jsx` are a deliberate marker for BIN-141: when that ticket splits the file into smaller hooks/components, `load()` should become a memoized `useCallback`, and these five suppressions should be revisited/removed as part of that refactor rather than carried forward indefinitely.
- `npm audit` reports 8 high-severity findings after this change — all in the new ESLint toolchain's own transitive dev dependencies (`minimatch`/`brace-expansion` ReDoS advisories pulled in by `eslint`/`eslint-plugin-react`) plus one pre-existing `react-router` advisory unrelated to this ticket. None are reachable from production runtime code (dev-only tooling); left as a follow-up rather than force-upgrading ESLint's own dependency tree in a lint-config ticket.
- Parent epic: BIN-128 (2026-07-29 technical debt remediation audit).
