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

## Implementation Notes
- **API Key Security**: The `VITE_API_KEY` was removed from the SPA bundle to prevent exposure in DevTools. Admin endpoints rely on reverse-proxy level IP restrictions instead.
- **Resource Management**: Fixed generator leaks in the admin scoring endpoints by using the `SessionLocal` context manager directly, preventing connection exhaustion.
- **Schedule Limitations**: Changes via `POST /admin/schedule` currently require restarting the Celery beat process to take effect.
- **GPU Semaphore**: The `GPUSemaphore.scale()` logic correctly reads limits from Redis so it scales uniformly across all processes instead of relying on an isolated instance field.
