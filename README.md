# Imoveis — Deal Tracker

> Real-estate ingestion pipeline: multi-platform scraping, heuristic deduplication, PostGIS-backed geospatial storage, local AI enrichment, and price tracking.

**Stack:** Python FastAPI + Celery · PostGIS (Postgres 17) · Redis · React/Vite · Ollama

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
| Database    | PostgreSQL 17 + PostGIS| Geospatial property storage     |
| AI          | Ollama / LM Studio     | Local VLM + text models         |
| Frontend    | React 19 + Vite 8      | Score-coloured property grid    |
| Config      | Pydantic + YAML        | Single source of truth          |
| Migrations  | Alembic                | Schema versioning               |
| Gates       | `scripts/agent/` local | validate.sh = the merge gate; GitHub Actions = docs deploy + nightly scraper drift canary |
| Tracking    | BMad artifacts (`_bmad-output/`) | epics.md = plan of record; sprint-status.yaml = status |

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
frontend/                         # React 19 + Vite 8
configs/app_config.yaml           # Runtime settings
scripts/                          # Management scripts (see below)
```

For a detailed architecture breakdown, see [Architecture](docs/architecture.md).

## Quick Start

### 1. First-time setup

```bash
git clone https://github.com/felipelrib/imoveis.git
cd imoveis
./scripts/setup.sh
```

This creates `.env.local` (if missing), builds/starts Docker services, runs migrations, and installs frontend deps.

### 2. Set a local API key (required for the SPA)

Protected routes (favourites, watchlist, saved searches, admin) need an `API_KEY` on the API **and** the same value in the UI. Without it, those requests return **401/403**.

Add a local-only key to `.env.local` (never commit real secrets):

```bash
# .env.local
API_KEY=local-dev-api-key
```

Restart so the API container picks it up (also starts Vite on :5173):

```bash
./scripts/restart.sh
```

Open http://localhost:5173 — or use `./scripts/dev.sh` if you want Vite logs in the terminal.

### 3. Run day-to-day

`./scripts/start.sh` / `./scripts/restart.sh` start the backend **and** background Vite.
Use `./scripts/dev.sh` when you want the Vite process attached to your terminal (hot-reload logs; Ctrl+C stops only the UI).

```bash
./scripts/start.sh   # Detached stack + Vite
# or
./scripts/dev.sh     # Same stack, Vite in the foreground
```

Then open:

| Service       | URL                          |
|---------------|------------------------------|
| Frontend      | http://localhost:5173         |
| API           | http://localhost:8000         |
| API Docs      | http://localhost:8000/docs    |

### 4. Paste the key in the UI

In the sidebar, find **API credential** → paste the same value as `API_KEY` (e.g. `local-dev-api-key`) → **Save**.

That stores it in `sessionStorage` for the browser tab and sends it as `X-API-Key`. Status should show **set**. Clear/re-paste after closing the tab if needed.

**curl example:**

```bash
curl -s -H "X-API-Key: local-dev-api-key" http://localhost:8000/admin/health
```

## Day-to-Day Commands

| Script               | What it does                                          |
|----------------------|-------------------------------------------------------|
| `./scripts/start.sh` | Start stack + background Vite on :5173 (migrations)   |
| `./scripts/stop.sh`  | Stop containers and background Vite                   |
| `./scripts/restart.sh`| Stop + start (`--build` to rebuild images)           |
| `./scripts/test.sh`  | Run tests (`unit`, `integration`, `e2e`, or `all`)    |
| `./scripts/dev.sh`   | Same stack, Vite in the foreground (Ctrl+C = UI only) |
| `./scripts/clean.sh` | Stop stack; keeps volumes by default (`--volumes` / `--all` wipe data) |
| `bash scripts/agent/docker-cleanup.sh` | Prune stopped containers + dangling/unused feat|wt images + build cache (keeps `imoveis-*` + bases; never volumes) |

Backend-only (no Vite): `./scripts/start.sh --no-frontend`. Stop everything: `./scripts/stop.sh`.

## Configuration

All settings live in [`configs/app_config.yaml`](configs/app_config.yaml). Common env overrides (put durable local values in `.env.local`):

```bash
API_KEY=local-dev-api-key          # required for SPA personalization + admin
export DATABASE_URL=postgresql://user:pass@localhost:5432/realestate_dev
export REDIS_URL=redis://localhost:6379/0
export OLLAMA_BASE_URL=http://localhost:11434
```

`docker-compose.yml` passes `API_KEY` / `JWT_SECRET` into the API container from the host env / `.env.local`.

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

Imoveis uses [BMad Method](https://docs.bmad-method.org/tutorials/getting-started/) for PRD / architecture / epics. Planning artifacts land in `_bmad-output/`. BMad skills are framework-native (not Cursor- or Claude-specific) under `.agents/skills/` (e.g. `bmad-help`, `bmad-prd`).

- Orientation: invoke **`bmad-help`** (see `_bmad-output/planning-artifacts/bmad-help-session.md`).
- Sprint tracker: `_bmad-output/implementation-artifacts/sprint-status.yaml`.
- Shipping: BMad owns execution too ([ADR 0003](docs/adr/0003-bmad-planning-bridge.md) as amended, [ADR 0005](docs/adr/0005-drop-linear-bmad-artifacts-sole-tracker.md)) — the BMad story cycle (`bmad-create-story` → `bmad-dev-story` → `bmad-code-review`, or `bmad-quick-dev`) bound to the `scripts/agent/` gates via `_bmad/custom/` overrides.
- Re-install / update: `npx bmad-method install --yes --modules bmm --tools cursor --action update`

## Development Workflow

Features are tracked in BMad artifacts: `_bmad-output/planning-artifacts/epics.md` (plan of record) + `_bmad-output/implementation-artifacts/sprint-status.yaml` (execution status). Story keys look like `v0.13-s1.1`; follow-ups mint `v0.13-fu<N>`.

**Feature / merge-bound work:**

1. **Plan** — Prefer BMad PRD/epics for product scope; Plan mode (Cursor or Claude Code) for ticket-level design.
2. **Workspace** — `bash scripts/agent/setup-workspace.sh <feature-slug>` (solo on idle primary, or sibling worktree if primary is busy). See [ADR 0004](docs/adr/0004-parallel-agent-workspaces.md).
3. **Implement** — TDD with conventional commits.
4. **Validate** — `bash scripts/agent/validate.sh all`.
5. **Finish** — `bash scripts/agent/finish-feature.sh` (validate → local squash-merge into `main` → mandatory `git push origin main` → cleanup: worktree teardown or primary back on `main`, ephemeral test stack down, `docker-cleanup.sh` — keeps the primary `imoveis-*` stack, never volumes).
6. **Story done** — set the story key to `done` in sprint-status.yaml **after** the merge is pushed + `docs/features/<story-key>-<slug>.md` doc (the finish gate refuses story-key branches without one).
7. **Harness retrospect** — fold durable lessons into `CLAUDE.md` / `.cursor/rules/` if the session exposed a gap.

**Parallel agents:** run `bash scripts/agent/workspace-status.sh`. If `primary_idle=no`, the next agent gets a worktree under `../imoveis-wt-<slug>` with private Compose ports.

**Punctual asks** (small fixes, harness tweaks, questions): no PR unless you ask for one.

### Code Quality

- Pre-commit hooks: `pre-commit install && pre-commit install --hook-type pre-push`
- Linting: isort, flake8 (backend), eslint (frontend)
- Tests: pytest (unit/cassettes/integration/contract), Playwright (E2E)
- CI jobs (`lint`, `unit`, `integration`, `contract`, `scrapers`, `e2e`, `security-scan`) run **in parallel**; all required checks must still pass to merge.
- Scraper fixtures: `src/tests/fixtures/scrapers/` — refresh with `python scripts/dev/record_scraper_cassettes.py` on live HTML drift.
- Scraper gate: `bash scripts/agent/validate-scrapers.sh --require-live` (CI job `scrapers`).

Agent rules/skills are **local** (`.cursor/` for Cursor, `.claude/` for Claude Code — both gitignored). Shared gates live in `scripts/agent/`. See [ADR 0002](docs/adr/0002-cursor-single-agent-workflow.md).

## License

Private repository. All rights reserved.
