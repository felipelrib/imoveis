# Beat Scheduler Redis-Override Crash Fix — stop Celery Beat crashing on a documented supported feature

> Feature branch: `fix/beat-scheduler-redis-crash` · Linear: `BIN-129` · Status: implemented

## Problem

`RedisAwareScheduler` (the production Celery Beat scheduler) used stdlib `import logging` instead of the project's structlog `get_logger`, then called `logger.info(...)` / `logger.warning(...)` with structured kwargs (`task=entry.name`, `reason=...`). Stdlib `Logger.info/warning()` does not accept arbitrary kwargs and raises `TypeError: Logger._log() got an unexpected keyword argument 'task'`. The scheduler's own `try/except` only caught `ValueError`, so this `TypeError` propagated out of `apply_entry` any time an operator set or changed a `scheduler:interval:<platform>` Redis override — a documented, supported feature — crashing/stalling Celery Beat and silently halting all scheduled scraping/AI jobs.

Six other files used the same unsafe stdlib `import logging` pattern (currently safe by luck, since none of them passed structured kwargs), meaning the unsafe pattern was one copy-paste away from reproducing the same crash elsewhere.

## Approach

- Standardize `redis_scheduler.py` (and the 6 other stdlib-`logging` files) on `infra.logging.get_logger`, which supports structured kwargs as LogRecord extras.
- Add regression test coverage for `RedisAwareScheduler`'s Redis-override path — there was none before this fix, which is why the crash went undetected.
- No behavior change intended beyond the logging call shape; scheduler semantics (skip on `disabled_via_redis`, warn on invalid override) are unchanged.

## Changes

Files touched:

```
src/adapters/queue/redis_scheduler.py     | FIX — get_logger instead of stdlib logging; root cause of the crash
src/adapters/queue/celery_app.py          | logging import standardized to get_logger
src/adapters/queue/gpu_semaphore.py       | logging import standardized to get_logger
src/adapters/geo/access_refresh.py        | logging import standardized to get_logger
src/adapters/geo/listing_claim_refresh.py | logging import standardized to get_logger
src/core/risk_overlay.py                  | logging import standardized to get_logger
src/core/safety_overlay.py                | logging import standardized to get_logger
src/infra/ui_locale.py                    | logging import standardized to get_logger
src/tests/unit/test_redis_scheduler.py    | NEW — regression coverage for the Redis-override path
src/tests/unit/test_schedule.py           | updated for get_logger-based assertions
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

`src/tests/unit/test_redis_scheduler.py` directly exercises the `disabled_via_redis` / invalid-override paths that previously raised `TypeError` and asserts no exception propagates.

## Notes / Follow-ups

- This was tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone), findings #1, #12, and #23 from the 2026-07-29 audit.
- Epic parent: BIN-128.
