# Imoveis — Deal Tracker

Real-estate ingestion pipeline. Multi-platform scraping, heuristic deduplication,
PostGIS-backed geospatial storage, local AI enrichment, and price tracking.

**Stack:** Python FastAPI + Celery · PostGIS (Postgres 15) · Redis · React/Vite · Ollama

## Quickstart

### Using Docker Compose (recommended)

```bash
bash scripts/agent/setup-worktree.sh <feature-slug>
cd .worktrees/<feature-slug>
bash scripts/agent/run-services.sh
# API: http://localhost:$API_PORT/health
# Frontend: http://localhost:$FRONTEND_PORT
```

### Manual setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
createdb realestate_dev && psql realestate_dev -c "CREATE EXTENSION postgis;"
cd alembic && alembic upgrade head && cd ..
uvicorn src.api.main:app --reload
celery -A src.adapters.queue.tasks.celery worker -Q scrapers -c 4
celery -A src.adapters.queue.tasks.celery worker -Q ai -c 1
```

## Architecture

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

**Data flow:** Scraper → Normalize → Dedupe → DB → Metrics → AI Enrich

## Working on Features

1. **Find next feature:** Check the [Linear board](https://linear.app/felipelrib/) — the source of truth for all features
2. **Tell Cline:** "Work on feature `<slug>` from Linear"
3. **Cline will:** read issue → plan → implement → commit → validate → merge → update Linear

### Key commands

| Task | Command |
|------|---------|
| Create worktree | `bash scripts/agent/setup-worktree.sh <slug>` |
| Start services | `bash scripts/agent/run-services.sh` |
| Validate | `bash scripts/agent/validate.sh [backend\|frontend\|all]` |
| Finish feature | `bash scripts/agent/finish-feature.sh [slug] [--validate-only]` |
| Dry run | `bash scripts/agent/finish-feature.sh --dry-run` |

## Documentation

Full documentation is published via MkDocs Material: [docs/](docs/)

| Doc | Description |
|-----|-------------|
| [Setup Guide](docs/setup.md) | Local environment setup |
| [Architecture](docs/architecture.md) | System design, Cline workflow |
| [API Reference](docs/api.md) | Endpoints and request/response formats |
| [Feature Docs](docs/features/) | Implementation notes per shipped feature |
| [Deployment](docs/deployment.md) | Production deployment guide |
| [Linear Board](https://linear.app/felipelrib/) | Feature queue, issues, backlog |

## Configuration

All settings are in `configs/app_config.yaml`. Environment variable overrides
use `${ENV}` syntax (e.g., `${DATABASE_URL}`, `${REDIS_URL}`).

## Development

### Commit conventions

Commit messages MUST use conventional format: `feat:`, `fix:`, `test:`, `docs:`,
`refactor:`, `chore:`.

### Testing

```bash
pytest src/tests/ -v                    # All tests
pytest src/tests/unit/ -v               # Unit only
bash scripts/agent/validate.sh backend  # Full backend validation
```

### Adding a new scraper

Implement `src/adapters/scrapers/base.py::BaseScraper`, register with
`@register("platform-name")`, add to `configs/app_config.yaml`.

## License

MIT