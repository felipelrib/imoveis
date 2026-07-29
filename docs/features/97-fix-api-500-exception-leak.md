# Stop leaking internal exception details on API 500 responses

> Feature branch: `fix/api-500-exception-leak` · Linear: `BIN-132` · Status: implemented

## Problem

~17 call sites across the API caught a broad `Exception` and returned the raw
exception string as the HTTP 500 `detail` field:
`src/api/watchlist.py`, `src/api/favourites.py`, `src/api/saved_searches.py`,
`src/api/admin.py`, `src/api/main.py`.

A DB connection error, SQLAlchemy `StatementError`, or Redis error would leak
internal details — table/column names, connection strings, stack fragments —
directly in the API response body to any caller, including unauthenticated
ones on endpoints gated only by an optional API key. This was a consistent,
repo-wide pattern, not an isolated slip (found via the 2026-07-29 technical
debt audit, epic BIN-128).

## Approach

- Added a single shared helper, `api.errors.raise_api_error(logger, event,
  exc, *, status_code=500, detail=None, **log_fields)`, instead of a global
  FastAPI exception handler. A helper was chosen over
  `app.add_exception_handler` because several call sites need to roll back
  the SQLAlchemy session and/or emit extra structured log fields (e.g.
  `search_id=...`) right at the catch site — a global handler can't see that
  context, only the final exception.
- The helper always logs the **full** exception server-side via the
  caller's own `get_logger(__name__)` instance (so log entries keep the
  original module name, e.g. `api.watchlist`), then raises `HTTPException`
  chained with `from exc` (preserves the traceback for server-side
  debugging/log correlation).
- For `status_code >= 500` the response `detail` is **always** the fixed
  string `"Internal server error"` — a `detail=` override is ignored for
  5xx, so a call site can't accidentally re-introduce a leak.
- For `status_code < 500` (deliberate `ValueError` raised by our own
  validation code — e.g. `admin.py`'s `enrichment_rerun`/`enrich_missing`
  mapping bad params to 400), the raw exception message is preserved as
  `detail` (or an explicit `detail=` override), because those are
  application-controlled, caller-facing validation messages, not leaked
  internals.
- Migrated all 17 grep-verified call sites
  (`grep -rn 'detail=str(exc)' src/api/`) across `watchlist.py`,
  `favourites.py`, `saved_searches.py`, `main.py`, and `admin.py` to use the
  helper.

## Changes

Files touched:

```
 src/api/errors.py                                  | NEW — shared raise_api_error() helper
 src/api/watchlist.py                                | 2 call sites migrated (add/remove)
 src/api/favourites.py                                | 2 call sites migrated (add/remove)
 src/api/saved_searches.py                            | 3 call sites migrated (create/delete/update)
 src/api/main.py                                      | 1 call site migrated (trigger_scrape)
 src/api/admin.py                                     | 9 call sites migrated (recalculate_scores,
                                                       | enrichment_rerun, enrich_missing,
                                                       | recompute_verdicts, backfill_embeddings,
                                                       | load_neighbourhood_quality)
 src/tests/unit/test_api_errors.py                    | NEW — unit tests for the helper itself
 src/tests/unit/test_watchlist_error_handling.py      | NEW — regression: watchlist 500s hide exc text
 src/tests/unit/test_admin_neighbourhood_quality_load.py | UPDATED — assertion no longer expects the
                                                       | (now-fixed) leaked "bad yaml" detail text
```

## New Dependencies

None.

## How to Test

1. Unit tests:
   ```bash
   PYTHONPATH=src pytest src/tests/unit/test_api_errors.py src/tests/unit/test_watchlist_error_handling.py src/tests/unit/test_admin_neighbourhood_quality_load.py -m unit
   ```
   or the full gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual check: force a DB/Redis error against any of the migrated
   endpoints (e.g. stop Postgres and call `POST /watchlist`) and confirm the
   response body is `{"detail": "Internal server error"}` while the
   original exception text appears in the server logs (`docker compose logs
   api`).

## Notes / Follow-ups

- `admin.py`'s two `ValueError -> 400` sites (`enrichment_rerun`,
  `enrich_missing`) intentionally keep the raw validation message as
  `detail` — those are app-raised, caller-facing messages (e.g.
  "stale_before is required..."), not internal leaks, so changing them
  would regress useful client-facing error feedback.
- Follow-up (optional, not in this ticket's scope): consider a global
  FastAPI exception handler for any *unhandled* exception that bypasses a
  route's own `try/except` entirely, as defense-in-depth on top of this
  per-call-site helper.
- Linear: `BIN-132` (parent epic `BIN-128`).
