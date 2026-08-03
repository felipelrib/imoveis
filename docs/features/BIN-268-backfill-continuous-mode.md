# Backfill `--continuous` mode — auto-wait for RPD reset & resume

> Feature branch: `feat/bin-268-backfill-continuous` · Linear: `BIN-268` · Status: implemented

## Problem

The BIN-248 Gemma backfill runner stops when the daily request budget is spent and relies on the operator
re-invoking it each day for ~6 days. That's tedious and easy to forget. It should be able to run
unattended: spend the day's budget, wait for the quota to reset, and resume — all in one invocation.

The subtlety: free-tier **RPD resets on the provider's calendar day** (an unknown, changeable clock), so
naïvely sleeping "until local midnight" risks waking into a wall of 429s.

## Approach

- **Rolling 24h budget window.** `DailyBudget` now tracks a counter + window-start in a Redis hash; the
  window opens on the first reserved request and closes 24h later. Because the budget (14,000) is below
  the RPD cap (14,400), staying under it in *any* rolling 24h is automatically under any calendar-day cap —
  **safe regardless of when the provider resets**. It also makes the wait exact:
  `DailyBudget.seconds_until_reset()` is just the time left in the window (so the wait is
  `24h − time already spent`, matching real elapsed work, not a flat day).
- **`--continuous` loop.** Run a pass; if properties remain and the budget is exhausted, sleep
  `seconds_until_reset() + --reset-margin` (default 120s) and resume; finish when no un-enriched rows
  remain. If a pass makes no progress with budget left, it stops rather than spin. Checkpointed, so a
  killed/restarted process resumes without double-processing (Ctrl-C-safe).
- At the default pace (budget spread over ~24h) a continuous run mostly flows across day boundaries with
  near-zero idle; a faster `--min-interval` spends the budget sooner and then waits out the window.

## Changes

Files touched:

```
 src/core/backfill_runner.py               | DailyBudget → rolling 24h window (hash) + seconds_until_reset()
 scripts/dev/backfill_gemma.py             | --continuous / --reset-margin; _run_continuous loop; usage docs
 src/tests/unit/test_backfill_runner.py    | rolling-window reset / still-active / seconds_until_reset tests
 src/tests/unit/test_backfill_gemma_cli.py | --continuous waits-then-completes / no-progress-stop / dry-run guard
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Manual (against the running stack):

```bash
export DATABASE_URL="postgresql://<user>:<pass>@localhost:<port>/realestate"
GEMINI_API_KEY=... PYTHONPATH=src python scripts/dev/backfill_gemma.py --continuous
```

Recommended under `tmux` / `nohup` / a systemd unit so it survives a closed terminal.

## Notes / Follow-ups

- `--continuous` ignores `--limit` (it runs to completion) and rejects `--dry-run`.
- Client-side exponential backoff still absorbs transient per-minute 429s; the rolling window prevents
  hitting the daily cap in the first place.
- Cron (one bounded pass/day) remains a valid alternative to a long-lived process.
- Related: `BIN-248` (runner), `BIN-267` (CLI fixes).
