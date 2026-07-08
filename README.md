# Imoveis — Deal Tracker

Real-estate ingestion pipeline. Multi-platform scraping, heuristic deduplication,
PostGIS-backed geospatial storage, local AI enrichment, and price tracking.

**Stack:** Python FastAPI + Celery · PostGIS (Postgres 15) · Redis · React/Vite · Ollama

## Quick Start

```bash
git clone https://github.com/felipelrib/imoveis.git
cd imoveis
./scripts/setup.sh          # builds images, starts stack, runs migrations
```

Then open:
- **Frontend:** http://localhost:5173
- **API:** http://localhost:8000
- **API docs:** http://localhost:8000/docs

## Day-to-Day Commands

| Script | What it does |
|--------|-------------|
| `./scripts/start.sh` | Start the stack (builds if needed, runs migrations) |
| `./scripts/stop.sh` | Stop containers (volumes preserved) |
| `./scripts/restart.sh` | Stop + start (`--build` to rebuild images) |
| `./scripts/test.sh` | Run tests (`unit`, `integration`, `e2e`, or `all`) |
| `./scripts/dev.sh` | Start backend + frontend dev server (hot-reload) |
| `./scripts/clean.sh` | Tear down + remove volumes (`--all` removes images too) |

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
scripts/                          # Project management scripts (see table above)
```

**Data flow:** Scraper → Normalize → Dedupe → DB → Metrics → AI Enrich

## Documentation

Full documentation is published via [GitHub Pages](https://felipelrib.github.io/imoveis/) (MkDocs Material):

| Doc | Description |
|-----|-------------|
| [Setup Guide](https://felipelrib.github.io/imoveis/setup/) | Local environment setup + deployment |
| [Architecture](https://felipelrib.github.io/imoveis/architecture/) | System design and data flow |
| [API Reference](https://felipelrib.github.io/imoveis/api/) | Endpoints and request/response formats |
| [Feature Docs](https://felipelrib.github.io/imoveis/features/) | Implementation notes per shipped feature |
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
./scripts/test.sh unit        # Unit tests only
./scripts/test.sh integration # Integration tests (needs running stack)
./scripts/test.sh all         # Everything
```

### Adding a new scraper

Implement `src/adapters/scrapers/base.py::BaseScraper`, register with
`@register("platform-name")`, add to `configs/app_config.yaml`.

## License

MIT