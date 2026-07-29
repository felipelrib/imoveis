# Locale-aware money/date formatters

> Feature branch: `feat/bin-116-locale-aware-moneydate-formatters` · Linear: `BIN-116` · Status: implemented

## Problem

Feature 77 (`BIN-98`) left a follow-up that money/date helpers were still hardcoded `pt-BR`. Ticket `BIN-116` tracked that gap, but the helpers were already centralized on the active UI locale during the full catalog migration (`BIN-99` / feature 79). The backlog ticket and stale Notes line risked re-implementing shipped behaviour.

## Approach

- **Reconcile, do not re-implement:** audit `frontend/src/i18n/format.js` and call sites — all pass `locale` from `useLocale()`; amounts stay BRL; only digit grouping and date order follow `en` / `pt-BR`.
- Lock acceptance with Playwright: pure helper asserts (comma vs period grouping, MDY vs DMY) plus Properties card smoke for both locales.
- Refresh stale follow-ups on features 77 and 79 so the Notes trail matches main.

## Changes

Files touched:

```
 frontend/src/i18n/format.js                         | comment — BIN-99/BIN-116
 frontend/tests/e2e/locale-formatters.spec.js        | NEW — helper + card regression
 docs/features/90-locale-aware-moneydate-formatters.md | NEW — this doc
 docs/features/77-locale-foundation.md               | follow-up → shipped / BIN-116
 docs/features/79-full-ui-string-catalog.md          | Notes — BIN-116 reconcile
```

## New Dependencies

None.

## How to Test

1. Full gate (includes Playwright locale formatter specs):
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: Language → English → property card shows `R$ 3,500`-style grouping; switch to Português (Brasil) → same amount uses period grouping (`R$ 3.500`). Scraped BRL amounts are not converted to another currency.

## Notes / Follow-ups

- Implementation lives with BIN-99 (`format.js`); this ticket is documentation + regression coverage.
- No currency conversion / FX — display locale only (acceptance criterion).
- Map popup mid-session locale switch still may need remount (same note as feature 79).
