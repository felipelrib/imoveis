# Architecture

## Overview

Imoveis is a local-first real-estate deal-finding pipeline. The system scrapes multiple platforms, deduplicates listings, tracks prices, enriches with AI, and alerts users to deals.

## Data Flow

```
Scraper → Normalize → Dedupe → DB → Metrics → AI Enrich
                                          ↓
                                    Price History
                                          ↓
                                    Alerts / Notifications
```

## Source Layout

```
src/
├── api/                          # FastAPI routers, admin endpoints
├── adapters/                     # External integrations
│   ├── db/                       # SQLAlchemy ORM models
│   ├── scrapers/                 # Platform scrapers (add-on pattern)
│   ├── ai/                       # LocalAIClient abstraction (Ollama, LM Studio)
│   ├── queue/                    # Celery tasks + GPU semaphore
│   └── metrics/                  # Statistical scoring
├── core/                         # Business logic (dedup, entities)
├── infra/                        # Config, DB, Redis, logging
└── tests/                        # pytest suite (unit + integration)
frontend/                         # React 19 + Vite 8
configs/app_config.yaml           # Single source of truth for all settings
scripts/                          # Project management scripts
```

## Key Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API | FastAPI | REST endpoints, admin controls |
| Task Queue | Celery + Redis | Async scraping, AI enrichment |
| Database | PostgreSQL 17 + PostGIS + pgvector | Geospatial + embedding storage |
| AI | Ollama / LM Studio | Local VLM + text models |
| Frontend | React 19 + Vite 8 | Score-coloured property grid |
| Config | Pydantic + YAML | Single source of truth |
| Migrations | Alembic | Schema versioning |
| CI/CD | GitHub Actions | Tests, lint, build |
| Issue Tracking | BMad artifacts (`_bmad-output/`) | epics.md = plan of record; sprint-status.yaml = execution status (ADR 0005) |

## Components

### API Layer (`src/api/`)

FastAPI application with routers for properties, scraper control, admin endpoints, and system health. Interactive docs at `/docs` when running.

### Scrapers (`src/adapters/scrapers/`)

Plugin-based scraper architecture. Each platform implements `BaseScraper` and registers via `@register("platform-name")`. Currently supports QuintoAndar and OLX.

### AI Enrichment (`src/adapters/ai/`)

Local AI pipeline using Ollama (primary) or LM Studio (fallback). Enriches listings with visual condition assessment, neighbourhood sentiment, and statistical valuation. GPU concurrency controlled by a semaphore to prevent OOM.

### Task Queue (`src/adapters/queue/`)

Celery work is split into three queues, each consumed by its own worker service (`docker-compose.yml`). The names are defined once, in `src/adapters/queue/celery_app.py`:

| Queue | Worker service | Tasks |
|---|---|---|
| **scrapers** | `worker_scraper` (concurrency 2; also drains the default `celery`) | `tasks.scrape_listings` and the operator-triggered `tasks.backfill_listing_costs` only. A scrape can hold a slot for hours. |
| **ai** | `worker_ai` (GPU-bound, concurrency 2, serial generates per property) | `tasks.ai_enrich`, `tasks.embed_property`, behind the GPU semaphore. The only GPU path. |
| **periodic** | `worker_periodic` (concurrency 2) | every other task: queue monitor, pipeline metrics snapshot, watchlist and saved-search alerts, digests, price-drop alerts, availability recheck, neighbourhood refresh jobs. |

Rules (pinned by `src/tests/unit/test_queue_layout.py`):

- Every task has a `task_routes` entry. A new task is routed to `periodic` unless it is a scrape or GPU work. No scheduled task other than a scrape shares the queue of `scrape_listings`, and `periodic` and `scrapers` are never consumed by the same worker.
- An idempotent beat entry carries `expires` equal to its own interval, so a worker that was down or is behind discards the missed ticks. The hourly alert sender, the digests and the scrapes carry none: they must not be lost.
- A scrape is single-flight per platform and scope (`src/adapters/queue/scrape_single_flight.py`): the beat and `POST /scrape` publish nothing while one is queued or running, and a duplicate that is delivered anyway returns `skipped`. Both leases expire by TTL.
- `GET /system/pipeline`, the queue monitor and the metrics snapshot report all three queues; `GET /system/status` reports a routed queue that no worker consumes.

Details and operator steps: `docs/features/v0.14-s1.18-periodic-tasks-not-blocked-by-scrapes.md`.

### Frontend (`frontend/`)

React 19 + Vite 8 application with a dark-themed property grid. Properties are scored and colour-coded by deal quality. Includes a dashboard with system status, scraper controls, and price history charts.
