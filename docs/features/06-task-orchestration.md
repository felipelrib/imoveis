# Task Orchestration — Celery-based pipeline with GPU gating, retry logic, and telemetry

> Feature branch: `feat/task-orchestration` · Linear: `BIN-XX` · Status: implemented

## Problem

The ingestion pipeline has multiple stages (scrape → normalize → dedup → persist → score → AI enrich) that must be coordinated asynchronously. GPU-intensive VLM inference should be throttled to prevent OOM. Failed tasks need automatic retry with exponential backoff.

## Approach

- **Celery task chain**: The `scrape_listings` task handles scraping, normalization, dedup, DB persistence, and metrics scoring. It then chains to `ai_enrich` tasks for each new/updated property.
- **GPU semaphore** (`GPUSemaphore`): A Redis-backed distributed semaphore that limits concurrent VLM inferences. Uses `SETNX`-based locking with TTL. Default concurrency: 2.
- **Worker pause/resume**: A Redis flag `workers:ai:paused` gates AI enrichment. When set, `ai_enrich` retries after a delay instead of proceeding.
- **Circuit breaker integration**: `scrape_listings` checks the platform's circuit breaker before starting. If the breaker is open, the task is retried after the cooldown period.
- **Telemetry**: Each AI enrichment records `{duration, timestamp}` to a Redis list (`pipeline:ai:telemetry`) capped at 1000 entries. The `/system/pipeline` endpoint aggregates this for dashboard charts.
- **Retry strategy**: `scrape_listings` retries up to 3 times with exponential backoff (60s, 120s, 240s). `ai_enrich` retries up to 5 times with 30s backoff.

## Changes

Files touched:

```
 src/adapters/queue/tasks.py         | scrape_listings + ai_enrich Celery tasks
 src/adapters/queue/celery_app.py    | Celery app configuration
 src/adapters/queue/gpu_semaphore.py | Redis-backed GPU concurrency limiter
```

## New Dependencies

- `celery[redis]` — Task queue with Redis broker/backend.

## How to Test

1. Start Celery workers:
   ```bash
   celery -A adapters.queue.celery_app worker -l info -Q scrapers,ai
   ```
2. Trigger a scrape (which chains to AI enrichment):
   ```bash
   curl -X POST http://localhost:8000/scrape \
     -H 'Content-Type: application/json' \
     -d '{"platform": "quintoandar", "scrape_type": "rent"}'
   ```
3. Monitor with:
   ```bash
   celery -A adapters.queue.celery_app inspect active
   ```
4. Run schedule tests:
   ```bash
   pytest src/tests/unit/test_schedule.py -v
   ```

## Notes / Follow-ups

### Bugs Found

- **[FIXED] BUG (Critical): `cfg.platforms` does not exist** (tasks.py L67-70): The task accesses `cfg.platforms.get(platform_name)` but `AppConfig` has `cfg.scraping.platforms`. Additionally, `dataclasses.asdict(platform_cfg)` will fail because `PlatformConfig` is a Pydantic model, not a dataclass. Use `platform_cfg.model_dump()`.

- **[FIXED] BUG (Critical): `await` in sync function** (tasks.py L317): `verdict_result = await client.summarize_deal(...)` — `ai_enrich` is a sync Celery task. `await` outside an async function is a `SyntaxError`.

- **[FIXED] BUG (Moderate): Scraper status published but never cleaned up** (tasks.py L86): The task sets `pipeline:scraper:{name}:status` in Redis but never deletes it on completion. Stale status data will persist indefinitely.

- **[FIXED] BUG (Moderate): `telemetry_data` JSON stored as bytes** (tasks.py L300): Redis `LPUSH` receives JSON string, but `LTRIM` index is 999 (cap at 1000). The telemetry list grows unbounded if LTRIM fails.

### Tech Debt

- **No task result storage** — Tasks use `ignore_result=True` equivalent, making it impossible to query task outcomes programmatically.
- **Hardcoded queue names** — "scrapers" and "ai" are string literals scattered throughout; should be constants.
- **No dead letter queue** — Tasks that exhaust retries are silently dropped.
- **GPU semaphore uses SETNX without proper Redlock** — Fine for single-Redis setups but would need Redlock for multi-node Redis.
