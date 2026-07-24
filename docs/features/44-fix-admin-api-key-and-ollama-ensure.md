# fix-admin-api-key-and-ollama-ensure — SPA admin 403s + missing ollama ensure

> Feature branch: `fix/admin-schedule-403` · Linear: `BIN-59` · Status: implemented

## Problem

Scraper Control and Dashboard admin calls failed in two ways:

1. `GET /admin/schedule` and `POST /admin/scoring/recalculate` (and any `/admin/*`) returned **403** `Admin API key not configured` when the API container was started without `API_KEY` (bare `docker compose` without `--env-file .env.local`), while the SPA still sent `X-API-Key` from sessionStorage.
2. Dashboard `ensureOllama()` called `POST /system/ollama/ensure`, which was documented but never implemented → **404**.

## Approach

- Require `API_KEY` at Compose interpolate time (`${API_KEY:?…}`) so a missing env fails loud instead of blanking the secret.
- Implement admin-gated `POST /system/ollama/ensure`: probe first; optionally `ollama serve` only when the binary is on PATH; otherwise return a host-start error (Ollama runs outside Docker).
- Gate Scraper Control schedule polling on `hasApiKey()` and show a clear empty state / one auth toast.

## Changes

Files touched:

```
 docker-compose.yml                                  | Require API_KEY (?:) — fail loud when unset
 docs/setup.md                                       | Document compose --env-file / start.sh requirement
 src/api/system.py                                   | ADD POST /system/ollama/ensure (admin-gated, host-aware)
 frontend/src/pages/ScraperControl.jsx               | Poll schedule only with credential; empty-state copy
 src/tests/unit/test_auth.py                         | ADD schedule + recalculate 403 when server key empty
 src/tests/unit/test_system_ollama_ensure.py         | NEW — ensure auth + already_running / error / started
 frontend/tests/e2e/helpers/apiMocks.js              | Mock ensure; mockAdminSchedule helper
 frontend/tests/e2e/dashboard.spec.js                | Schedule poll skipped without key; key attached when set
 docs/features/44-fix-admin-api-key-and-ollama-ensure.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Ensure `.env.local` has `API_KEY=local-dev-api-key`, then:
   ```bash
   ./scripts/restart.sh api
   curl -s -H "X-API-Key: local-dev-api-key" http://localhost:8000/admin/schedule
   curl -s -X POST -H "X-API-Key: local-dev-api-key" http://localhost:8000/system/ollama/ensure
   ```
2. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Rebuild/recreate the API after this change so the container image picks up `system.py` (src is not bind-mounted).
- Starting `ollama serve` inside the API container cannot start the Windows/host daemon; the ensure endpoint returns a clear host instruction when the binary is missing.
- Related: [BIN-59](https://linear.app/felipelrib/issue/BIN-59/spa-admin-403s-empty-api-key-missing-post-systemollamaensure).
