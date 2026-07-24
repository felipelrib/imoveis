# Isolate integration tests onto separate Postgres DB — stop wiping scraped data

> Feature branch: `feat/isolate-integration-test-db` · Linear: `BIN-71` · Status: implemented

## Problem

`validate.sh` / `finish-feature.sh` pointed host pytest at the same Compose database (`realestate`) that scrapers use. Integration fixtures truncated **all** ORM tables after each test, deleting scraped properties whenever agents validated a feature.

## Approach

- Create/migrate a sibling database `realestate_test` on the same Postgres server (`ensure-test-db.sh`).
- `validate.sh` forces host `DATABASE_URL` to that test DB; Compose API/workers keep `/realestate`.
- Shared integration `conftest` refuses to run (or wipe) against primary DB name unless `IMOVEIS_ALLOW_PRIMARY_DB_WIPE=1`.
- CI/nightly use the same isolated DB name for symmetry.

## Changes

Files touched:

```
 scripts/agent/ensure-test-db.sh                 | NEW — create/migrate realestate_test
 scripts/agent/validate.sh                       | Host pytest → test DB; migrate both
 src/tests/db_isolation.py                       | NEW — wipe-safety helpers
 src/tests/integration/conftest.py               | NEW — shared wipe-safe session + guard
 src/tests/integration/test_*.py                 | Alias fixtures to wipe_safe_db_session
 src/tests/unit/test_db_isolation.py             | NEW — unit coverage for guards
 .github/workflows/ci.yml                        | integration + contract → realestate_test
 .github/workflows/nightly.yml                   | same
 .env.local.example                              | Document POSTGRES_TEST_DB / TEST_DATABASE_URL
 docs/features/50-isolate-integration-test-db.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Note primary count, run backend validate, confirm count unchanged:
   ```bash
   # count on realestate
   bash scripts/agent/validate.sh backend
   # count on realestate again — must match
   ```
2. Pointing pytest at primary must fail:
   ```bash
   DATABASE_URL=postgresql://imoveis:imoveis_local_dev@localhost:${POSTGRES_PORT}/realestate \
     pytest src/tests/integration/test_listings_e2e.py -q
   # expect RuntimeError: Refusing to wipe database 'realestate'
   ```

## Notes / Follow-ups

- Redis `flushdb` in some fixtures can still disturb Celery on a shared Redis — separate Redis DB index is a possible follow-up.
- Related: BIN-60 (preserve volumes), BIN-71 (this fix).
