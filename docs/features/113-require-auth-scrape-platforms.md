# Require authentication on POST /scrape and GET /platforms

> Feature branch: `feat/require-auth-scrape-platforms` · Linear: `BIN-149` · Status: implemented

## Problem

Found during the 2026-07-29 technical debt audit follow-up pass (epic BIN-128), confirmed still
open post-BIN-131/132 merge: those tickets hardened `/auth/*` defaults and fixed the 500-body
exception leak, but did not add authorization to the ingestion-triggering surface.

`POST /scrape` and `GET /platforms` (`src/api/main.py`) had no `Depends(verify_admin_access)` or
API-key check at all — unlike `/admin/*` (router-level `verify_admin_access`) and the properties
export route (`verify_api_key_if_configured`). Any caller reaching the API — unauthenticated —
could enqueue arbitrary scrape jobs against QuintoAndar/OLX/ZapImóveis for any registered
platform: resource abuse, and risk of tripping the target platforms' own rate limits/Cloudflare
blocks from unsanctioned traffic.

## Approach

- `POST /scrape` is now gated with `dependencies=[Depends(verify_admin_access)]` — the same
  edge-guard dependency used by the `/admin` router and `POST /system/ollama/ensure`. Missing
  credentials return `401`; an invalid API key or JWT returns `403`, matching every other
  admin-gated route. Added `401`/`403` to the route's `responses=` for OpenAPI/Sonar.
- `GET /platforms` is **intentionally left unauthenticated**, confirmed rather than assumed: it's
  read-only (registered platform names + enabled/rate-limit config, no PII/secrets), and
  `frontend/src/api.ts::fetchPlatforms()` calls it with a bare `fetch(...)` — no `X-API-Key` — on
  `ScraperControl` mount, before any credential is entered. This mirrors the BIN-46 credential-gate
  split already in place for other page loads (e.g. platform dropdown loads before login, same as
  the Dashboard's proxy-health card). Gating it with `verify_api_key_if_configured` would 403 that
  initial dropdown populate for every visitor once `auth.api_key` is set in production — confirmed
  by the existing contract test `test_platforms_returns_list`, which already asserts `200` with no
  headers even though the contract test suite sets `API_KEY` via env. A docstring on
  `list_platforms` records this decision so a future pass doesn't "fix" it by guessing.
- Frontend `triggerScrape()` now goes through the existing `apiFetch()` helper (attaches the
  session-stored `X-API-Key`) instead of a bare unauthenticated `fetch`, matching
  `enrichMissing`/`triggerAvailabilityRecheck`. `ScraperControl`'s `handleScrape` gates on
  `hasApiKey()` first and shows a toast (`scraper.toastAuthScrape`, both locales) instead of
  firing a request that the server will now reject — the same UX pattern already used for
  `handleAvailabilityRecheck`.

## Changes

Files touched:

```
 src/api/main.py                              | POST /scrape gated with Depends(verify_admin_access); /platforms docstring documents the intentional no-auth decision
 frontend/src/api.ts                          | triggerScrape() routed through apiFetch() (attaches stored X-API-Key) instead of a bare fetch
 frontend/src/pages/ScraperControl.jsx        | handleScrape() gates on hasApiKey() before calling triggerScrape, mirroring handleAvailabilityRecheck
 frontend/src/i18n/locales/en.json            | NEW key scraper.toastAuthScrape
 frontend/src/i18n/locales/pt-BR.json         | NEW key scraper.toastAuthScrape (PT translation)
 src/tests/contract/test_api_contract.py      | NEW TestScrapeEndpoint — regression: 401 missing cred, 403 invalid cred, 200 valid cred (mocked delay), 400 unknown platform still surfaces post-auth
 frontend/tests/e2e/dashboard.spec.js         | "shows platforms and triggers scrape" rewritten to require + attach a credential before asserting the enqueue toast (BIN-149)
 docs/features/113-require-auth-scrape-platforms.md | NEW — this file
```

## New Dependencies

None.

## How to Test

1. Automated regression suite:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Targeted backend tests:
   ```bash
   PYTHONPATH=src pytest src/tests/contract/test_api_contract.py -k "Scrape or Platforms" -v
   ```
3. Targeted e2e:
   ```bash
   cd frontend && npx playwright test tests/e2e/dashboard.spec.js -g "Scraper control"
   ```
4. Manual check — `curl -X POST http://localhost:<api_port>/scrape -H 'Content-Type: application/json' -d '{"platform":"olx"}'` with no `X-API-Key` returns `401`; with the wrong key returns `403`; with the configured `API_KEY` returns `200 {"task_id": ..., "status": "queued"}`. `curl http://localhost:<api_port>/platforms` with no header still returns `200` (unchanged).

## Notes / Follow-ups

- `/platforms` staying open is a deliberate, documented trade-off (see docstring + this doc), not
  an oversight — re-litigate only if the platform list itself starts carrying sensitive data
  (e.g. internal-only platforms, credentials in `rate_limit` config).
- No change to `/admin/schedule`, `/admin/availability/recheck`, or any other already-gated admin
  route — this ticket scoped strictly to the two routes named in BIN-149.
