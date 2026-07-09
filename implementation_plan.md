# Implementation Plan: Scheduled Scrapes via Celery Beat

**Linear:** [BIN-8](https://linear.app/felipelrib/issue/BIN-8/recurring-scrapes-via-celery-beat)
**Feature slug:** `scheduled-scraping`

## Goal

Enable automatic, recurring scrapes via Celery Beat so the deal tracker collects fresh data without manual clicks.

## Current State

- `celery_app.py` creates a Celery app with no `beat_schedule`
- `configs/app_config.yaml` has platform configs (enabled, rate_limit) but no scrape interval
- `docker-compose.yml` has `worker_ai` and `worker_scraper` but no `beat` service
- `src/api/admin.py` has worker management but no schedule management
- `ScraperControl.jsx` shows live pipeline but no schedule info
- `src/infra/config.py` already has `CeleryConfig.beat_schedule` field and `PlatformConfig` model

## Steps

### 1. Config: Add `scrape_interval` to platform config

**Files:**
- `configs/app_config.yaml` — add `scrape_interval: 60` (minutes) to each platform
- `src/infra/config.py` — add `scrape_interval: int = 60` field to `PlatformConfig`

### 2. Celery beat schedule builder

**File:** `src/adapters/queue/celery_app.py`

- Import `get_config` and `get_redis`
- After creating the Celery app, iterate `cfg.scraping.platforms` and build `beat_schedule`:
  - Key: `"scrape-{platform_name}"`
  - Task: `"tasks.scrape_listings"`
  - Schedule: `crontab(minute="*/{interval}")` for each enabled platform
  - Args: `[platform_name]`
- Apply the built schedule to `celery_app.conf.beat_schedule`
- Read override intervals from Redis key `scheduler:interval:{platform}` if present, falling back to config

### 3. Write `last_run` timestamp on scrape completion

**File:** `src/adapters/queue/tasks.py`

- After `scrape_listings` completes successfully, write `pipeline:scraper:{platform_name}:last_run` to Redis with current timestamp

### 4. Docker beat service

**File:** `docker-compose.yml`

- Add `beat` service:
  ```yaml
  beat:
    build:
      context: .
      dockerfile: Dockerfile.worker
    restart: unless-stopped
    command: >
      celery -A adapters.queue.tasks beat
      --loglevel=info
    environment:
      DATABASE_URL: postgresql://imoveis:${POSTGRES_PASSWORD:-imoveis_local_dev}@postgres:5432/realestate
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./configs:/app/configs
  ```

### 5. Admin schedule API endpoints

**File:** `src/api/admin.py`

- `GET /admin/schedule` — returns per-platform schedule:
  - Read from Redis `scheduler:interval:{platform}` for overrides
  - Fall back to config `scrape_interval`
  - Also return `last_run` from `pipeline:scraper:{platform}:last_run`
  - Compute `next_run` based on last_run + interval

- `POST /admin/schedule` — update interval:
  - Body: `{platform: str, interval_minutes: int}` (0 to disable)
  - Persist to Redis key `scheduler:interval:{platform}`
  - Note: beat reads schedule at startup; interval changes take effect on beat restart

### 6. Frontend: schedule display and editing

**Files:**
- `frontend/src/api.js` — add `fetchSchedule()` and `updateSchedule(platform, interval)`
- `frontend/src/pages/ScraperControl.jsx` — add a "Scheduled Runs" section:
  - Table with columns: Platform | Interval | Last Run | Next Run | Actions (edit/save)
  - Show badge "beat running" or "manual only" based on schedule presence
  - Editable interval input with save button

### 7. Tests

- Unit test for `build_beat_schedule()` (testable pure function extracted)

## Acceptance Criteria

- [ ] Enabled platform is scraped automatically on its interval
- [ ] Changing interval via `POST /admin/schedule` takes effect (after beat restart)
- [ ] Disabled platforms (`enabled: false` or `interval: 0`) are skipped
- [ ] Live Pipeline panel shows last-run/next-run per platform
- [ ] `validate.sh` passes

## Risks

- Celery beat re-reads `beat_schedule` only at startup (or via `--autoreload`). Interval changes via API persist to Redis but require beat restart to take effect on the schedule. A future improvement could use `celery.beat.Scheduler` with Redis-backed schedule.
- For now, the frontend will note that changes take effect on next deployment restart.