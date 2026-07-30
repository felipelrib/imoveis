# Celery Redis AppConfig Routing — stop Celery silently using a different Redis instance than the rest of the app

> Feature branch: `fix/celery-redis-appconfig` · Linear: `BIN-130` · Status: implemented

## Problem

`celery_app.make_celery()` read `REDIS_URL` via a bare `os.environ.get("REDIS_URL", "redis://localhost:6379/0")`, bypassing `AppConfig` entirely — a direct violation of the project convention that all settings come from `AppConfig` (never `os.getenv()` outside `config.py`). Every other Redis consumer (`infra.redis_client.get_redis()`) resolves the URL from `cfg.redis.url`, built from YAML `redis.host/port/password` fields, only falling back to `REDIS_URL` if explicitly set.

When Redis was configured via YAML fields only (the documented AppConfig-first convention, no `REDIS_URL` env var set), Celery's broker/backend silently fell back to `redis://localhost:6379/0` — a different Redis instance than the rest of the app uses for checkpoints, circuit breakers, and scheduler overrides (including the `RedisAwareScheduler` fixed in BIN-129). Tasks enqueued into that mismatched Redis DB would silently vanish or duplicate depending on what was actually running at `localhost:6379/0`.

## Approach

- `make_celery()` now builds `broker_url`/`result_backend` from `get_config().redis.url` — the exact same resolution path `get_redis()` already uses — instead of reading `os.environ` directly.
- Regression tests assert (a) Celery's broker/backend match AppConfig's resolved URL when only YAML fields are set (no `REDIS_URL`), and (b) a `REDIS_URL` env var present in the process does **not** leak into Celery unless AppConfig itself resolved through it — proving delegation is complete, not partial.

## Changes

Files touched:

```
src/adapters/queue/celery_app.py       | FIX — broker_url/result_backend now resolve via get_config().redis.url
src/tests/unit/test_celery_app.py      | NEW — regression coverage: AppConfig-resolution and no-os-environ-leak
src/tests/unit/test_schedule.py        | existing make_celery tests updated to mock get_config instead of REDIS_URL env var
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

`src/tests/unit/test_celery_app.py::TestMakeCeleryRedisResolution` directly locks the AppConfig-first resolution behavior.

## Notes / Follow-ups

- This was tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone), finding #2 from the 2026-07-29 audit — one of two Critical, live-production bugs in that audit (the other being BIN-129's Beat scheduler crash, which this ticket's fix complements: both were rooted in Redis-adjacent code bypassing AppConfig).
- Epic parent: BIN-128.
