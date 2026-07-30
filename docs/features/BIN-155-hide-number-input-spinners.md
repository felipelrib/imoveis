# Hide number-input spinners — remaining numeric fields (BIN-79 regression class)

> Feature branch: `feat/bin-155-hide-number-input-spinners` · Linear: `BIN-155` · Status: implemented

## Problem

[BIN-79](https://linear.app/felipelrib/issue/BIN-79) removed the native number-spinner arrows from the Properties max-price/limit inputs by switching them to `type="text"` + `inputMode="numeric"` (CSS alone does not hide the steppers in all browsers). The 2026-07-29 tech-debt audit found two more inputs still using plain `<input type="number">`, so they kept rendering spinner arrows:

- `frontend/src/components/PropertyModal.jsx` — `dropPct` (watchlist price-drop-alert %).
- `frontend/src/pages/ScraperControl.jsx` — `editInterval` (schedule-interval edit).

## Approach

- Apply the same pattern already proven in `PropertiesFilterBar.jsx`: `type="text"` + `inputMode="numeric"` + `pattern="[0-9]*"`, stripping non-digits in `onChange` (`value.replace(/[^\d]/g, '')`).
- `editInterval` was already a string state parsed with `parseInt` at save, so no state-type change was needed.
- `dropPct` was a `number` state; converted to a digit-string state (default `'5'`) and coerced back with `Number(dropPct) || 5` at the watchlist-add call, preserving the previous numeric submit semantics.
- Added `data-testid`s (`modal-drop-pct-input`, `schedule-interval-input`) so the regression can assert the input type directly (mirrors `max-price-input`).

## Changes

Files touched:

```
 frontend/src/components/PropertyModal.jsx          | dropPct → text+numeric, digit-string state, coerce at submit
 frontend/src/pages/ScraperControl.jsx              | editInterval → text+numeric, strip non-digits
 frontend/tests/e2e/numeric-input-spinners.spec.js  | NEW — regression: both inputs are type=text + inputMode=numeric
```

## New Dependencies

None.

## How to Test

1. Automated regression:
   ```bash
   bash scripts/agent/validate.sh all
   ```
   (`numeric-input-spinners.spec.js` fails against the old `type="number"` inputs and passes after the fix.)
2. Manual: open a property modal (not yet watched) — the "alert at __% drop" field shows no up/down spinner arrows and rejects non-digits. On Scraper Control (with an API key set), click **Edit** on a schedule row — the interval field behaves the same.

## Notes / Follow-ups

- Closes the BIN-79 regression class for the two remaining numeric inputs. A lint rule forbidding `<input type="number">` in favour of the shared pattern could prevent recurrence but is out of scope here.
- Part of epic [BIN-128](https://linear.app/felipelrib/issue/BIN-128) (v0.10 — Technical debt remediation).
