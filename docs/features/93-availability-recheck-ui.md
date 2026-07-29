# availability-recheck-ui — Scraper Control button for listing availability recheck

> Feature branch: `feat/bin-123-scraper-control-availability-recheck` · Linear: `BIN-123` · Status: implemented

## Problem

BIN-80 shipped `POST /admin/availability/recheck` and a Celery beat task, but operators
had to curl the admin API. Scraper Control had no button to enqueue a one-off
availability recheck batch.

## Approach

- Add `triggerAvailabilityRecheck` in `api.js` (admin-authenticated `apiFetch`).
- Place a Worker Management row on Scraper Control with toast success/error.
- Gate the action on `hasApiKey()` before any network call (same credential model as schedules).
- No batch-size UI — server uses `availability_recheck.batch_size` from config.

## Changes

Files touched:

```
 frontend/src/api.js                              | NEW triggerAvailabilityRecheck helper
 frontend/src/pages/ScraperControl.jsx            | Recheck button + API-key gate + toasts
 frontend/src/i18n/locales/en.json                | scraper.* recheck strings
 frontend/src/i18n/locales/pt-BR.json             | Portuguese recheck strings
 frontend/tests/e2e/dashboard.spec.js             | Auth-gate + POST success e2e (BIN-123)
 docs/features/59-listing-availability-recheck.md | Follow-up marked shipped via BIN-123
 docs/features/93-availability-recheck-ui.md      | this doc
```

## New Dependencies

None.

## How to Test

1. E2E (mocked admin):
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: paste API credential, open Scraper Control, click **Recheck now**, confirm toast
   and Celery scrapers queue receives `tasks.recheck_listing_availability`.

## Notes / Follow-ups

- Closes the deferred UI bullet from feature 59 / BIN-80.
- Parent epic: BIN-104 (v0.9 follow-up backlog).
