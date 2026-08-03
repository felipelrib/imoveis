# Backfill `--concurrency` — parallel enrichment + observed-throughput ETA

> Feature branch: `feat/bin-269-backfill-concurrency` · Linear: `BIN-269` · Status: implemented

## Problem

The BIN-248 runner is sequential: each property is ~3 sequential Gemma calls (~67s) plus the default
pacing sleep, so throughput is ~1,000 properties/day and a full backfill is **~24–30 days**, not the ~6
the RPD budget implies. Observed request rate is ~2/min — far below the 30 RPM / 14,400 RPD limits, so the
bottleneck is **wall-clock API latency, not quota**. The `--status` ETA compounded the confusion by
computing days from the *request budget* (assuming the RPD cap is the limit) rather than reality.

## Approach

- **`--concurrency N`** (config `backfill.concurrency`, default 1): `run_backfill` enriches up to N
  properties in parallel via an `asyncio.Semaphore`, preserving the budget (RPD) gate, `--limit`,
  force/skip idempotency, checkpointing, and per-row error isolation. Since each property is latency-bound,
  parallelism is what lifts throughput toward the rate-limit ceilings.
- **RPM launch gate** replaces the old "spread budget over 24h" pace: launches are spaced by
  `60 * requests_per_property / rpm_limit` (6s at 30 RPM / 3 req), so the request rate stays under the
  per-minute cap regardless of N. `--min-interval` overrides; new `backfill.rpm_limit` (default 30).
- **TPM safety**: the 16K TPM ceiling (image-heavy visual calls) will throttle before RPM at higher N; the
  client's existing exponential backoff on 429 absorbs it, so concurrency degrades gracefully rather than
  failing. Start conservative (`--concurrency 4`) and watch `rate_limit_hits` in the progress logs.
- **Observed-throughput ETA**: `--status` now derives the ETA from the *actual* recent enrichment rate
  (enrichments in the last hour × 24) and shows it, falling back to the budget ceiling only when idle.

## Changes

Files touched:

```
 src/core/backfill_runner.py               | run_backfill: concurrency (semaphore) + launch_interval gate; launch_interval_for_rpm(); dry-run split into _run_dry
 scripts/dev/backfill_gemma.py             | --concurrency; RPM-based launch interval; observed-rate ETA in --status; usage docs
 src/infra/config.py + configs/app_config.yaml | backfill.rpm_limit (30) + backfill.concurrency (1)
 src/tests/unit/test_backfill_runner.py    | concurrency bound / counts / limit+budget; launch-gate + launch_interval_for_rpm tests
 src/tests/unit/test_backfill_gemma_cli.py | --concurrency passthrough; _observed_rate_per_day
 src/tests/unit/test_config.py             | rpm_limit / concurrency defaults
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
GEMINI_API_KEY=... PYTHONPATH=src python scripts/dev/backfill_gemma.py --continuous --concurrency 4
PYTHONPATH=src python scripts/dev/backfill_gemma.py --status   # ETA now reflects observed rate
```

## Notes / Follow-ups

- Effective throughput at concurrency N ≈ `min(N / per-property-latency, rpm_limit / rpp)` properties/min,
  and is further capped by TPM for image-heavy properties. On free-tier Gemma, `--concurrency 4–6` is a
  reasonable starting range; higher mostly trades into 429/backoff.
- The launch gate protects RPM globally; TPM protection is reactive (client backoff), not proactive — a
  proactive token-budget limiter could be a future refinement if 429s prove costly.
- Related: `BIN-248` (runner), `BIN-268` (continuous mode).
