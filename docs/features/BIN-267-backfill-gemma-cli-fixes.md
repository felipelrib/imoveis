# Backfill Gemma CLI fixes — keyless dry-run + honored `--limit`

> Feature branch: `feat/bin-fix-backfill-dryrun-keyless` · Linear: `BIN-267` · Status: implemented

## Problem

Two bugs surfaced running the BIN-248 runner (`scripts/dev/backfill_gemma.py`) against the real DB:

1. **`--dry-run` demanded `GEMINI_API_KEY`.** `_run()` built the Gemma client eagerly before the dry-run
   branch, so a plan-only run — which makes no API calls and no writes — failed with
   `GEMINI_API_KEY is not set`.
2. **`--limit N` was not a real processing cap.** It only bounded the SQL over-fetch (`limit*5` in
   `fetch_candidate_rows`), so `--limit 2` could enrich up to ~10 properties and spend ~30 requests —
   surprising for a "small trial" and a waste of free-tier quota + unintended DB writes.

(Also: the DB-connection error the user first hit was environmental — the script uses the app
`SessionLocal`, which needs `DATABASE_URL` pointed at the running stack; now documented in the usage.)

## Approach

- **Defer client construction**: `client = None if args.dry_run else _build_client(cfg)`, and only open the
  HTTP `session_context()` for a real run. Dry-run needs neither a key nor a client.
- **Honor `--limit` in the loop**: `run_backfill` gained a `limit` param that caps the number of
  properties *attempted* this run (skipped already-enriched rows don't count), so a small `--limit`
  touches exactly that many.
- **Document `DATABASE_URL`** in the CLI docstring so the DB-connection requirement is discoverable.

## Changes

Files touched:

```
 scripts/dev/backfill_gemma.py             | dry-run builds no client / opens no session; pass limit; document DATABASE_URL
 src/core/backfill_runner.py               | run_backfill gains limit= (caps attempted properties)
 src/tests/unit/test_backfill_runner.py    | + limit cap / dry-run+limit / skip-not-counted regression tests
 src/tests/unit/test_backfill_gemma_cli.py | NEW — dry-run builds no client & needs no key; real run w/o key exits
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Manual (against the running stack; `--dry-run`/`--status` need only `DATABASE_URL`):

```bash
export DATABASE_URL="postgresql://<user>:<pass>@localhost:<port>/realestate"   # primary Postgres, e.g. 5433
PYTHONPATH=src python scripts/dev/backfill_gemma.py --dry-run --limit 5   # would_process == 5, no key needed
```

## Notes / Follow-ups

- `--limit` counts *attempted* properties; on an enrich error the runner still moves on and a later row
  is attempted to reach the cap (limit = attempts, not guaranteed successes).
- Related: `BIN-248` (the runner this fixes).
