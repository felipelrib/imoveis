# Imoveis — Deal Tracker

> Real-estate ingestion pipeline: multi-platform scraping, heuristic deduplication, PostGIS-backed geospatial storage, local AI enrichment, and price tracking.

**Stack:** Python FastAPI + Celery · PostGIS (Postgres 15) · Redis · React/Vite · Ollama

## What It Does

- **Scrapes** rental and sale listings from multiple platforms (QuintoAndar, OLX) with throttling, circuit breakers, and retry logic.
- **Deduplicates** listings across platforms using geospatial proximity + heuristic matching — one property, one record.
- **Tracks prices** over time, detecting drops and surfacing deals.
- **Enriches** listings with local AI models (Ollama): visual condition assessment, neighbourhood sentiment, statistical valuation.
- **Alerts** users to price drops and high-value deals via a score-coloured dashboard.

## Architecture

```
Scraper → Normalize → Dedupe → DB → Metrics → AI Enrich
                                          ↓
                                    Price History
                                          ↓
                                    Alerts / Dashboard
```

| Component   | Technology             | Purpose                         |
|-------------|------------------------|---------------------------------|
| API         | FastAPI                | REST endpoints, admin controls  |
| Task Queue  | Celery + Redis         | Async scraping, AI enrichment   |
| Database    | PostgreSQL 15 + PostGIS| Geospatial property storage     |
| AI          | Ollama / LM Studio     | Local VLM + text models         |
| Frontend    | React 18 + Vite        | Score-coloured property grid    |
| Config      | Pydantic + YAML        | Single source of truth          |
| Migrations  | Alembic                | Schema versioning               |
| CI/CD       | GitHub Actions         | Tests, lint, build, security    |
| Tracking    | Linear                 | Feature queue, project board    |

```
src/
├── api/                          # FastAPI routers, admin endpoints
├── adapters/                     # External integrations
│   ├── db/                       # SQLAlchemy ORM models
│   ├── scrapers/                 # Platform scrapers (plugin pattern)
│   ├── ai/                       # LocalAIClient (Ollama, LM Studio)
│   ├── queue/                    # Celery tasks + GPU semaphore
│   └── metrics/                  # Statistical scoring
├── core/                         # Business logic (dedup, entities)
├── infra/                        # Config, DB, Redis, logging
└── tests/                        # pytest suite (unit + integration)
frontend/                         # React 18 + Vite
configs/app_config.yaml           # Runtime settings
scripts/                          # Management scripts (see below)
```

For a detailed architecture breakdown, see [Architecture](docs/architecture.md).

## Quick Start

```bash
git clone https://github.com/felipelrib/imoveis.git
cd imoveis
./scripts/setup.sh
```

Then open:

| Service       | URL                          |
|---------------|------------------------------|
| Frontend      | http://localhost:5173         |
| API           | http://localhost:8000         |
| API Docs      | http://localhost:8000/docs    |

## Day-to-Day Commands

| Script               | What it does                                          |
|----------------------|-------------------------------------------------------|
| `./scripts/start.sh` | Start the stack (builds if needed, runs migrations)   |
| `./scripts/stop.sh`  | Stop containers (volumes preserved)                   |
| `./scripts/restart.sh`| Stop + start (`--build` to rebuild images)           |
| `./scripts/test.sh`  | Run tests (`unit`, `integration`, `e2e`, or `all`)    |
| `./scripts/dev.sh`   | Start backend + frontend dev server (hot-reload)      |
| `./scripts/clean.sh` | Tear down + remove volumes (`--all` removes images)   |

## Configuration

All settings live in [`configs/app_config.yaml`](configs/app_config.yaml). Environment variable overrides:

```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/realestate_dev
export REDIS_URL=redis://localhost:6379/0
export OLLAMA_BASE_URL=http://localhost:11434
```

See the full [Setup Guide](docs/setup.md) for manual installation, AI model setup, and production deployment.

## Documentation

Full documentation is published via MkDocs Material:

| Page | Description |
|------|-------------|
| [Setup Guide](docs/setup.md) | Installation, prerequisites, production deployment |
| [Architecture](docs/architecture.md) | Data flow, components, tech decisions |
| [API Reference](docs/api.md) | Endpoints, parameters, examples |
| [Features](docs/features/) | Implementation notes per shipped feature |
| [ADRs](docs/adr/) | Architecture Decision Records |

Preview docs locally: `pip install mkdocs-material && mkdocs serve`

## Product planning (BMad Method)

Imoveis uses [BMad Method](https://docs.bmad-method.org/tutorials/getting-started/) for PRD / architecture / epics. Planning artifacts land in `_bmad-output/`. Cursor skills are under `.agents/skills/` (e.g. `bmad-help`, `bmad-prd`).

- Orientation: invoke **`bmad-help`** (see `_bmad-output/planning-artifacts/bmad-help-session.md`).
- Bridge to shipping: [ADR 0003](docs/adr/0003-bmad-planning-bridge.md) — BMad plans; Linear + `scripts/agent/` execute. Local skill: `.cursor/skills/imoveis-planning-bridge`.
- Re-install / update: `npx bmad-method install --yes --modules bmm --tools cursor --action update`

## Development Workflow

Features are tracked in [Linear](https://linear.app/felipelrib/) (team "Bino").

**Feature / merge-bound work:**

1. **Plan** — Prefer BMad PRD/epics for product scope; Cursor Plan mode for ticket-level design.
2. **Branch** — `bash scripts/agent/setup-branch.sh <feature-slug>`.
3. **Implement** — TDD with conventional commits.
4. **Validate** — `bash scripts/agent/validate.sh all`.
5. **PR** — `bash scripts/agent/finish-feature.sh --pr`.
6. **Babysit** — Watch CI until green.
7. **Linear Done** + numbered `docs/features/` doc.
8. **Harness retrospect** — update local Cursor rules/skills if the session exposed a gap.

**Punctual asks** (small fixes, harness tweaks, questions): no PR unless you ask for one.

### Code Quality

- Pre-commit hooks: `pre-commit install && pre-commit install --hook-type pre-push`
- Linting: isort, flake8 (backend), eslint (frontend)
- Tests: pytest (unit/cassettes/integration/contract), Playwright (E2E)
- CI jobs (`lint`, `unit`, `integration`, `contract`, `scrapers`, `e2e`, `security-scan`) run **in parallel**; all required checks must still pass to merge.
- Scraper fixtures: `src/tests/fixtures/scrapers/` — refresh with `python scripts/dev/record_scraper_cassettes.py` on live HTML drift.
- Scraper gate: `bash scripts/agent/validate-scrapers.sh --require-live` (CI job `scrapers`).

Agent rules/skills are **local** (`.cursor/`, gitignored). Shared gates live in `scripts/agent/`. See [ADR 0002](docs/adr/0002-cursor-single-agent-workflow.md).

## License

Private repository. All rights reserved.
