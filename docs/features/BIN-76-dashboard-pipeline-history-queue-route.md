# dashboard-pipeline-history-queue-route — Route beat snapshots to a consumed queue

> Feature branch: `feat/dashboard-pipeline-history-queue-route` · Linear: `BIN-76` · Status: implemented

## Problem

Dashboard AI throughput and queue-depth charts only filled while the page was
open and reset on navigate away. BIN-61 already persists snapshots and the UI
loads `GET /system/pipeline/history` on mount, but history stayed empty because
Celery beat enqueued `tasks.snapshot_pipeline_metrics` onto the default
`celery` queue — and workers only consume `scrapers` and `ai`.

## Approach

- Route all always-on beat / maintenance tasks to the `scrapers` queue via
  `task_routes` (same pattern as `send_price_drop_alert`).
- Have `worker_scraper` also listen to `celery` so any leftover or future
  unrouted tasks are still drained.
- Unit regression asserts maintenance task routes.

## Changes

Files touched:

```
 src/adapters/queue/celery_app.py     | Route beat maintenance tasks → scrapers
 docker-compose.yml                   | worker_scraper --queues=scrapers,celery
 src/tests/unit/test_schedule.py      | BIN-76 route regression tests
 docs/features/BIN-76-dashboard-pipeline-history-queue-route.md | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Manual:

1. Rebuild/restart `beat` + `worker_scraper` so they pick up routes.
2. Wait ~1 minute, then `curl localhost:8000/system/pipeline/history?minutes=60`
   should return growing `points`.
3. Open Dashboard, leave, return — charts should still show history.

## Notes / Follow-ups

- Related: BIN-61 (persistence + history API). This ticket unblocks that path.
- After deploy, drain or let `worker_scraper` consume any backlog on Redis list
  `celery` left from before the route fix.
