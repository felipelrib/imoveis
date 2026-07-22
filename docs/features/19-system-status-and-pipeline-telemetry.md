# system-status-and-pipeline-telemetry — Live health dashboard and AI throughput metrics for the scraper control panel

> Feature branch: `feat/system-telemetry` · Linear: `BIN-XX` · Status: implemented

## Problem

Running a background pipeline with multiple moving parts (DB, Redis, Ollama, Celery workers,
multiple scrapers) made it impossible to know at a glance:
- Which components are healthy vs. broken.
- How many tasks are queued or actively running.
- How fast the AI enrichment pipeline is processing properties.
- When each platform last ran and when it will run next.

## Approach

Two complementary endpoints under `/system` expose real-time telemetry that the frontend
polls:

### `GET /system/status`

Aggregates health of all components in a single response:
- `database` — executes `SELECT 1` via SQLAlchemy; returns `{status: "ok"}` or error detail.
- `redis` — calls `redis.ping()`; returns `{status: "ok"}` or error detail.
- `ollama` — `GET {ollama_url}/api/tags` with 3-second timeout; returns status + list of
  loaded model names.
- `ai_workers_paused` — `r.exists("workers:ai:paused")` boolean.
- `stats.total_properties` — `SELECT COUNT(*) FROM properties`.
- `stats.enriched_properties` — `SELECT COUNT(*) FROM metrics_scoring WHERE ai_score > 0`.

Used by:
- `useSystemStatus(intervalMs)` hook (frontend) — polls every 5 seconds.
- `Dashboard.jsx` — shows coloured status indicators.
- `ScraperControl.jsx` — gates the "Run Scraper" button on `database.status === "ok"`.

### `GET /system/pipeline`

Returns live ingestion pipeline data from Redis:
- **Queue depths**: `r.llen("scrapers")` and `r.llen("ai")` — Celery default queue lengths.
- **Per-platform scraper status**: scans `pipeline:scraper:*:status` Redis keys (written
  every item by the `scrape_listings` task) — returns `{processed, skipped, errors, status}`.
- **AI telemetry**: reads `pipeline:ai:telemetry` Redis list (written by `ai_enrich` on
  completion). Computes:
  - `avg_duration_sec` — mean of all recorded durations.
  - `throughput_per_min` — count of completions in the last 5 minutes ÷ 5.
  - `total_recorded` — total items in the list.

### `POST /system/ollama/ensure` (admin-gated)

Attempts to start `ollama serve` as a subprocess (`subprocess.Popen`) if the Ollama HTTP
server is not responding. Returns `"already_running"`, `"started"`, or `"error"`.

## Changes

Files touched:

```
 src/api/system.py                     | NEW — /system/status, /system/pipeline, /system/ollama/ensure
 src/api/main.py                       | Registered system router
 frontend/src/hooks/useSystemStatus.js | NEW — polling hook for system status
 frontend/src/pages/ScraperControl.jsx | Live pipeline panel (queue depths, AI metrics, schedule)
 frontend/src/pages/Dashboard.jsx      | Status indicator cards fed by useSystemStatus
 frontend/src/api.js                   | fetchStatus(), fetchPipeline()
```

## New Dependencies

- `httpx` — used in `_check_ollama()` for the Ollama health probe (already a transitive
  dependency; no new `requirements.txt` entry needed).

## How to Test

1. Start the stack: `bash scripts/start.sh`
2. Query system status:
   ```bash
   curl http://localhost:8000/system/status
   # {"database": {"status": "ok"}, "redis": {"status": "ok"}, "ollama": {...}, ...}
   ```
3. Stop Postgres and re-query → `database.status` should be `"error"` with detail.
4. Trigger a scrape and query pipeline status:
   ```bash
   curl -X POST http://localhost:8000/scrape -d '{"platform":"olx"}'
   curl http://localhost:8000/system/pipeline
   # {"queues": {"scrapers": 1, "ai": 0}, "scrapers_status": {"olx": {...}}, ...}
   ```
5. In the frontend — **Scraper Control** page should show live queue counts updating every 3 seconds.

## Notes / Follow-ups

- **BUG (`_check_ollama` uses a synchronous `httpx.get`)**: `httpx.get` with a 3-second
  timeout blocks the FastAPI event loop (which is async). Replace with `httpx.AsyncClient`
  and `await` in an async route handler, or push the check to a thread pool via
  `asyncio.to_thread()`.
- **BUG (N+1 DB connections in `system_status`)**: `_check_db()`, `_count_properties()`,
  and `_count_enriched()` each call `SessionLocal()` independently — three separate
  connection pool checkouts per `/system/status` request. Combine into a single session
  with multiple queries.
- **BUG (`pipeline:ai:telemetry` list grows without bound between trim calls)**:
  `ai_enrich` calls `r.lpush(...)` then `r.ltrim(0, 999)` — these are two separate
  commands, not atomic. Under concurrent workers, the list can momentarily exceed 1000
  entries. Use a `MULTI`/`EXEC` pipeline or Lua script for atomicity.
- **`GET /system/pipeline` scans Redis with `scan_iter`**: `scan_iter("pipeline:scraper:*:status")`
  is a full keyspace scan. On large Redis instances with many keys this is slow. Use a
  fixed platform list from the config to construct explicit key names instead.
- **Schedule `next_run` assumes `last_run` + interval**: If the Celery beat process drifts
  or was restarted with a different schedule, `next_run` may be inaccurate. Mark it as
  an estimate in the API response.
- **`subprocess.Popen` for Ollama startup is a security risk**: The `ensure_ollama`
  endpoint launches a child process from the FastAPI server process. In containerised
  deployments, the API container typically does not have `ollama` on PATH, and the
  `Popen` leaks a handle if the process fails to start. Consider removing this endpoint
  and handling Ollama startup in Docker Compose or a separate init container.
- **Logs persist in `localStorage` across sessions**: `ScraperControl.jsx` saves up to
  200 log entries to `localStorage`. The log content can include task IDs and error
  messages — consider clearing on logout when authentication is implemented.
