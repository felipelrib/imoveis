# admin-control-panel — Authenticated admin API for worker management, GPU scaling, scoring recalculation, and schedule editing

> Feature branch: `feat/admin-panel` · Linear: `BIN-XX` · Status: implemented

## Problem

Operating the ingestion pipeline required direct Redis/DB access or re-deploying config
files. There was no safe, authenticated way to:
- Pause AI enrichment workers during low-resource periods without stopping scraping.
- Adjust the number of concurrent GPU jobs at runtime.
- Recalculate property scores after tuning the stat/AI weight ratio.
- Change per-platform scrape intervals without restarting Celery beat.

## Approach

All admin endpoints are grouped under the `/admin` prefix with a **single `X-API-Key`
header guard** (`api.auth.verify_api_key`). The key is read from the `API_KEY` environment
variable. If unset, all requests are rejected with 403.

### Worker Management

- `GET /admin/workers/status` — returns `{"ai_workers_paused": bool}` by checking
  `r.exists("workers:ai:paused")` (fixed from the original broken `r.get() is not None`).
- `POST /admin/workers/pause` — sets `workers:ai:paused = "1"` in Redis.
- `POST /admin/workers/resume` — deletes `workers:ai:paused` from Redis.
- The `ai_enrich` Celery task checks this key at the start of every execution and calls
  `self.retry(countdown=60)` if paused, effectively queueing jobs without losing them.

### GPU Resource Control

- `POST /admin/gpu/scale` — calls `GPUSemaphore.scale(new_limit)` which atomically
  updates `semaphore:gpu` in Redis using `WATCH`/`MULTI`/`EXEC`. New tasks respect
  the new limit immediately without a restart.

### Scoring Recalculation

- `POST /admin/scoring/recalculate` — two-phase operation:
  1. `compute_neighborhood_stats(session)` — SQL window functions computing per-neighbourhood
     mean, median, stddev, z-score, percentile rank. Stored in `metrics_scoring`.
  2. `recalculate_all_combined_scores(session, weights)` — single `UPDATE metrics_scoring SET combined_score = ...` across all rows. O(1) memory regardless of table size.
  Optional `ScoringWeights` body overrides the YAML defaults for this recalculation.
- `POST /admin/scoring/weights` — persists new weights to `scoring:weights` Redis key
  for fast retrieval without a config reload.

### Schedule Management

- `GET /admin/schedule` — returns per-platform `{interval_minutes, last_run, next_run}`
  by merging YAML config with Redis overrides (`scheduler:interval:<platform>`).
- `POST /admin/schedule` — writes a Redis override for a platform's interval. The change
  takes effect when Celery beat next restarts (since beat reads the schedule at startup).

## Changes

Files touched:

```
 src/api/admin.py             | NEW — all admin endpoints (workers, GPU, scoring, schedule)
 src/api/auth.py              | NEW — X-API-Key header guard (verify_api_key dependency)
 src/api/main.py              | Registered admin router
 src/adapters/queue/gpu_semaphore.py | GPUSemaphore.scale() for runtime GPU limit adjustment
 src/adapters/metrics/scoring.py    | compute_neighborhood_stats(), recalculate_all_combined_scores(), score_single_property()
 src/core/entities.py         | ScoringWeights Pydantic model
 frontend/src/api.js          | pauseWorkers(), resumeWorkers(), recalculateScores(), fetchSchedule(), updateSchedule()
 frontend/src/pages/ScraperControl.jsx | Worker pause/resume toggle, schedule edit UI
```

## New Dependencies

None.

## How to Test

```bash
# Set admin key
export API_KEY=dev-secret

# Pause AI workers
curl -X POST http://localhost:8000/admin/workers/pause \
  -H 'X-API-Key: dev-secret'

# Check status
curl http://localhost:8000/admin/workers/status -H 'X-API-Key: dev-secret'
# {"ai_workers_paused": true}

# Resume workers
curl -X POST http://localhost:8000/admin/workers/resume -H 'X-API-Key: dev-secret'

# Scale GPU to 2 concurrent jobs
curl -X POST http://localhost:8000/admin/gpu/scale \
  -H 'Content-Type: application/json' -H 'X-API-Key: dev-secret' \
  -d '{"limit": 2}'

# Recalculate scores with custom weights
curl -X POST http://localhost:8000/admin/scoring/recalculate \
  -H 'Content-Type: application/json' -H 'X-API-Key: dev-secret' \
  -d '{"stat_weight": 0.4, "ai_weight": 0.6}'

# View / update schedule
curl http://localhost:8000/admin/schedule -H 'X-API-Key: dev-secret'
curl -X POST http://localhost:8000/admin/schedule \
  -H 'Content-Type: application/json' -H 'X-API-Key: dev-secret' \
  -d '{"platform": "olx", "interval_minutes": 120}'
```

## Notes / Follow-ups

- **BUG (API key exposed in SPA)**: The frontend reads `VITE_API_KEY` from `.env.development`
  and embeds it in the JS bundle at build time. Any user who opens browser DevTools can
  read the key. Admin endpoints should be protected at the reverse-proxy level (e.g.
  nginx `allow <trusted_ip>; deny all`) and not require client-side key embedding.
- **BUG (`recalculate_scores` calls `next(get_session())` without proper generator management)**:
  `session = next(get_session())` creates a generator but never fully exhausts it.
  The generator's cleanup code (which closes the session) only runs if `StopIteration` is
  raised. Use the standard `with contextlib.contextmanager` pattern or switch to
  `SessionLocal()` directly.
- **BUG (Schedule changes require beat restart)**: The `POST /admin/schedule` response
  includes `"note": "Changes take effect when the beat process restarts."` — this is a
  significant operational limitation. Beat should be made to re-read the schedule
  periodically (e.g. using `celery beat --schedule-filename` with a custom scheduler class
  that reads Redis).
- **`GPUSemaphore.scale()` updates `max_concurrent` in-process only**: `scale()` sets
  `self.max_concurrent = new_limit` on the current instance but each Celery worker
  creates its own `GPUSemaphore()` instance. The Redis counter is updated correctly,
  but `self.max_concurrent` is stale in other worker processes. The `acquire()` method
  uses the Redis counter directly (not `self.max_concurrent`) for the comparison, so
  this is functionally correct but misleading. Remove or document the instance field.
- **No audit log**: Admin actions (pause, scale, recalculate) are logged via structlog
  but there is no persistent audit trail. Consider writing to a dedicated `admin_audit`
  table for compliance.
