# scrape-activity-summary — Scrape finish lines in the Scraper Control Activity Log

> Feature branch: `feat/scrape-activity-summary` · Linear: `BIN-58` · Status: implemented

## Problem

When a scrape finished, Scraper Control’s Activity Log only showed the enqueue line. The live
pipeline panel flipped to idle with no summary of how many listings were processed, skipped, or
failed — so completed (and beat-triggered) runs felt abrupt.

## Approach

- Mirror AI enrichment telemetry: on scrape complete/fail, LPUSH a run summary to Redis
  `pipeline:scraper:telemetry` (capped at 100), then keep deleting the live status key in `finally`.
- Expose `recent_scrape_runs` on `GET /system/pipeline`.
- Scraper Control polls every 3s, dedupes by `run_id` (localStorage), and appends Activity Log
  lines for recent unseen runs (≤1h) with processed / skipped / failed counts.

## Changes

Files touched:

```
 src/adapters/queue/tasks.py                          | `_record_scrape_run` + call on success/failure
 src/api/schemas.py                                   | `PipelineResponse.recent_scrape_runs`
 src/api/system.py                                    | Read Redis scrape telemetry into pipeline API
 frontend/src/pages/ScraperControl.jsx                | Poll runs → Activity Log with seen-id dedupe
 src/tests/unit/test_scrape_run_telemetry.py          | NEW — unit coverage for telemetry + failure path
 docs/features/43-scrape-activity-summary.md          | NEW — this feature doc
```

## New Dependencies

None.

## How to Test

1. Start the stack and open Scraper Control.
2. Trigger a scrape for a platform; when it finishes, the Activity Log should show e.g.
   `✔ olx scrape finished — N processed, M skipped, K failed`.
3. Confirm `GET /system/pipeline` includes `recent_scrape_runs` with matching counters.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Activity Log remains browser-local (`scraperLogs`); Redis holds the durable run summaries the UI
  consumes. No `AdminAudit` rows for scrape finishes (out of scope for BIN-58).
- Counters are the existing task totals (`processed` / `skipped` / `errors`); created vs updated vs
  noop are not broken out.
- Celery retries can emit a `failed` summary per failed attempt before a later `completed` run.
