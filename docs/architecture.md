# Architecture

## Overview

Imoveis is a local-first real-estate deal-finding pipeline. The system scrapes multiple platforms, deduplicates listings, tracks prices, enriches with AI, and alerts users to deals.

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Cline (Development Hub)                │
│  Reads Linear via MCP  ·  Edits code + docs in repo     │
│  Runs validate.sh / finish-feature.sh                   │
└──────────┬────────────────────┬──────────────────────────┘
           │                    │
           ▼                    ▼
    ┌─────────────┐    ┌──────────────────┐
    │  Linear      │    │  GitHub Repo     │
    │  (issues,    │    │  - src/          │
    │   project,   │    │  - docs/         │
    │   status)    │    │  - scripts/      │
    └──────────────┘    │  - configs/      │
                        └──────────────────┘
```

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
frontend/                         # React 18 + Vite
configs/app_config.yaml           # Single source of truth for all settings
scripts/agent/                    # Workflow tooling (worktree, services, validate)
```

## Worktree Isolation

Each feature branch gets its own isolated workspace:

1. **Git worktree** — separate working directory with its own branch
2. **Docker containers** — unique ports and compose project name
3. **Database + Redis** — separate named volumes per worktree
4. **No port conflicts** — deterministic port allocation via `.worktrees/registry.tsv`

This means multiple features can be developed in parallel without interference.

## Feature Development Flow

1. **Linear** — feature is tracked as an issue with spec, status, and labels
2. **Worktree** — `setup-worktree.sh` creates isolated workspace
3. **Implementation** — Cline writes code and commits to the feature branch
4. **Validation** — `validate.sh` runs tests and checks
5. **Merge** — `finish-feature.sh` merges to main, cleans up
6. **Docs** — `gen-docs.sh` scaffolds feature documentation
7. **Linear** — issue status updated to Done

## Key Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API | FastAPI | REST endpoints, admin controls |
| Task Queue | Celery + Redis | Async scraping, AI enrichment |
| Database | PostgreSQL 15 + PostGIS | Geospatial property storage |
| AI | Ollama / LM Studio | Local VLM + text models |
| Frontend | React 18 + Vite | Score-coloured property grid |
| Config | Pydantic + YAML | Single source of truth |
| Migrations | Alembic | Schema versioning |
| CI/CD | GitHub Actions | Tests, lint, build |
| Issue Tracking | Linear | Feature queue, project management |