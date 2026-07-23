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
| Database | PostgreSQL 15 + PostGIS + pgvector | Geospatial + embedding storage |
| AI | Ollama / LM Studio | Local VLM + text models |
| Frontend | React 19 + Vite 8 | Score-coloured property grid |
| Config | Pydantic + YAML | Single source of truth |
| Migrations | Alembic | Schema versioning |
| CI/CD | GitHub Actions | Tests, lint, build |
| Issue Tracking | Linear | Feature queue, project management |

## Components

### API Layer (`src/api/`)

FastAPI application with routers for properties, scraper control, admin endpoints, and system health. Interactive docs at `/docs` when running.

### Scrapers (`src/adapters/scrapers/`)

Plugin-based scraper architecture. Each platform implements `BaseScraper` and registers via `@register("platform-name")`. Currently supports QuintoAndar and OLX.

### AI Enrichment (`src/adapters/ai/`)

Local AI pipeline using Ollama (primary) or LM Studio (fallback). Enriches listings with visual condition assessment, neighbourhood sentiment, and statistical valuation. GPU concurrency controlled by a semaphore to prevent OOM.

### Task Queue (`src/adapters/queue/`)

Celery workers split into two queues:
- **scrapers** (I/O-bound, higher concurrency) — platform scraping tasks
- **ai** (GPU-bound, concurrency=1) — AI enrichment tasks

### Frontend (`frontend/`)

React 19 + Vite 8 application with a dark-themed property grid. Properties are scored and colour-coded by deal quality. Includes a dashboard with system status, scraper controls, and price history charts.
