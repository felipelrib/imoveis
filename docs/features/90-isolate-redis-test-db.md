# Isolate Redis DB for integration test fixtures

> Feature branch: `feat/bin-117-isolate-redis-db` · Linear: `BIN-117` · Status: implemented

## Problem

Integration fixtures call Redis `flushdb()` against whatever `REDIS_URL` is set.
`validate.sh` previously derived `redis://localhost:${REDIS_PORT}/0` — the same
logical DB Compose Celery/API use. On a shared Redis that wiped broker/queue keys
mid-validate (follow-up noted in feature 50 / BIN-71).

## Approach

- Mirror BIN-71 Postgres isolation: Compose stays on **logical DB 0**; host pytest
  always uses **DB 15** (`REDIS_TEST_DB`, default `15`).
- Guard `flushdb` so DB 0 is refused unless `IMOVEIS_ALLOW_PRIMARY_REDIS_WIPE=1`.
- No separate Redis container; no docker-compose changes.

## Changes

Files touched:

```
 src/tests/redis_isolation.py                 | NEW — wipe-safe Redis URL helpers
 src/tests/unit/test_redis_isolation.py       | NEW — unit coverage for guards
 src/tests/integration/test_e2e.py            | assert wipe-safe before flushdb
 scripts/agent/validate.sh                    | Host pytest REDIS_URL → DB 15
 .github/workflows/ci.yml                     | integration/contract/scrapers → /15
 .github/workflows/nightly.yml                | integration → /15
 .env.local.example                           | Document REDIS_TEST_DB
 docs/setup.md                                | Testing note: DB 15 vs Compose 0
 docs/features/50-isolate-integration-test-db.md | Close Redis follow-up pointer
 docs/features/90-isolate-redis-test-db.md    | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. With Compose Redis on the primary stack, run:
   ```bash
   bash scripts/agent/validate.sh backend
   ```
   Host pytest must log `Host pytest REDIS_URL → DB 15 (Compose keeps 0)` and Celery
   queues on DB 0 must remain intact.
2. Pointing a flush fixture at DB 0 must fail:
   ```bash
   REDIS_URL=redis://localhost:${REDIS_PORT:-6379}/0 \
     PYTHONPATH=src pytest src/tests/integration/test_e2e.py -k mock_redis -q
   # expect RuntimeError: Refusing to flush Redis DB 0
   ```
   (Or call `assert_wipe_safe_redis_url` directly in a unit test — already covered.)

## Notes / Follow-ups

- Related: BIN-71 / feature 50 (Postgres `realestate_test`), BIN-117 (this fix).
- Redis key namespacing (prefix) is out of scope; logical DB isolation is enough for flushdb.
