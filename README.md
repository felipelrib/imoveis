# Imoveis — Deal Tracker

> Real-estate ingestion pipeline: multi-platform scraping, heuristic deduplication, PostGIS-backed geospatial storage, local AI enrichment, and price tracking.

**Stack:** Python 3.11 FastAPI + Celery · PostgreSQL 17 + PostGIS + pgvector · Redis · React 19 / Vite 8 (TypeScript) · Ollama (local AI)

## What It Does

- **Scrapes** rental and sale listings from multiple platforms (QuintoAndar, OLX, ZapImóveis) with throttling, circuit breakers, retry logic, optional proxy rotation, and an opt-in FlareSolverr Cloudflare-bypass sidecar.
- **Deduplicates** listings across platforms using geospatial proximity + heuristic matching — one property, one record.
- **Tracks prices** over time as intervals, detecting drops and surfacing deals.
- **Enriches** listings with local AI models (Ollama): visual condition assessment, neighbourhood sentiment, deal verdicts, statistical valuation, and pgvector embeddings for semantic search. An optional cloud backfill path (Gemma via the Gemini API) covers the historical corpus.
- **Alerts** on price drops and high-value deals via a score-coloured dashboard with an interactive map.

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
| Task Queue  | Celery + Redis         | Async scraping, AI enrichment, periodic work (queues: `scrapers`, `ai`, `periodic`, one worker each; beat scheduler) |
| Database    | PostgreSQL 17 + PostGIS + pgvector | Geospatial + embedding storage |
| AI          | Ollama / LM Studio (local); Gemma via Gemini API (cloud backfill only) | VLM + text + embedding models |
| Frontend    | React 19 + Vite 8 + TypeScript (maplibre-gl, recharts) | Score-coloured property grid, map, dashboard |
| Config      | Pydantic + YAML        | Single source of truth (`configs/app_config.yaml`) |
| Migrations  | Alembic                | Schema versioning               |
| Gates       | `scripts/agent/` local + `.claude/hooks/` | `validate.py` = THE merge gate (tiered, stamp-enforced on push); GitHub Actions = docs deploy + nightly scraper canary/dependency audit only |
| Tracking    | BMad artifacts (`_bmad-output/`) | `epics.md` = plan of record; `sprint-status.yaml` = execution status |

```
src/
├── api/                          # FastAPI routers (properties, admin, system,
│                                 #   favourites, watchlist, saved searches)
├── adapters/                     # External integrations
│   ├── db/                       # SQLAlchemy ORM models, projections
│   ├── scrapers/                 # Platform scrapers (plugin registry pattern)
│   ├── ai/                       # LocalAIClient (Ollama, LM Studio), enrich pipeline
│   ├── queue/                    # Celery app, tasks, GPU semaphore, beat scheduler
│   ├── geo/ metrics/ notify/     # Geospatial loaders, scoring, alert channels
├── core/                         # Business logic (dedupe, entities, scoring,
│                                 #   backfill runner, geo allowlist, …)
├── infra/                        # Config loading, DB session, Redis, logging
└── tests/                        # pytest: unit / integration / contract + fixtures
frontend/                         # React 19 + Vite 8 SPA (Playwright e2e)
configs/app_config.yaml           # Runtime settings (all-local AI by default)
alembic/                          # DB migrations
scripts/                          # Day-to-day + agent gate scripts (see below)
deploy/systemd/                   # Cloud backfill supervisor unit template (ADR 0006)
```

For a detailed breakdown, see [Architecture](docs/architecture.md).

## Prerequisites

- **Docker + Docker Compose v2** (the whole stack is compose-managed; on Windows use Docker Desktop with the WSL2 backend).
- **Python 3.11** (matches the API/worker images) with `venv` for host-side tooling and tests.
- **Node.js** (recent LTS) + npm for the frontend.
- **Ollama** on the GPU host with `qwen2.5vl:7b` (VLM) and `bge-m3` (embeddings) pulled — see [Setup Guide](docs/setup.md) for VRAM tuning (`OLLAMA_NUM_PARALLEL` must equal `gpu.semaphore_limit`).
- **WSL2 note:** when Ollama runs on the Windows host, start it with `OLLAMA_HOST=0.0.0.0:11434` so Docker/WSL can reach it (see [Setup Guide](docs/setup.md)); from WSL, tools resolve it via the default-route gateway IP (see [Development Guide](docs/development-guide.md)).

## Quick Start

### 1. First-time setup

```bash
git clone https://github.com/felipelrib/imoveis.git
cd imoveis
./scripts/setup.sh
```

This creates `.env.local` (if missing), installs frontend deps and builds/starts Docker services. It does not migrate the primary database: `start.sh` reports the schema state, and on a fresh install (or after a pull that carries a migration) you apply it with `bash scripts/agent/migrate-primary.sh`.

### 2. Set a local API key (required for the SPA)

Protected routes (favourites, watchlist, saved searches, admin) need an `API_KEY` on the API **and** the same value in the UI. Without it, those requests return **401/403**. Compose refuses to start the API without `API_KEY` at all — always start via the scripts or `docker compose --env-file .env.local …`, never a bare `docker compose up`.

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
| `./scripts/start.sh` | Start stack + background Vite on :5173 (`--no-frontend` for backend only; service names to start a subset). Never migrates the primary database: it reports the schema state and points at `bash scripts/agent/migrate-primary.sh` |
| `./scripts/stop.sh`  | Stop containers and background Vite                   |
| `./scripts/restart.sh`| Stop + start (`--build` to rebuild images)           |
| `./scripts/test.sh`  | Run tests (`unit`, `integration`, `e2e`, or `all`) — prefer `scripts/agent/validate.py` for the real gate |
| `./scripts/dev.sh`   | Same stack, Vite in the foreground (Ctrl+C = UI only) |
| `./scripts/clean.sh` | Stop stack; **never** deletes volumes (`--all` also drops rebuildable images/cache) |
| `python scripts/agent/validate.py` | The merge gate — tier chosen from the diff (`--tier X` forces; `--only scrapers\|ai\|harness`; `--down` removes the ephemeral test stack) |
| `python scripts/agent/ship.py` | Validate → squash-merge into `main` → push (refuses a dirty tree) |
| `bash scripts/ops/docker-cleanup.sh` | Occasional operator task: prune stopped containers + dangling/unused feature images + build cache (keeps `imoveis-*` + bases; never volumes) |

## Validation & Merge Gate

There is **no remote CI gate** — the merge gate is local and hook-enforced (`scripts/agent/` + `.claude/hooks/`, see [ADR 0007](docs/adr/0007-tiered-gate-and-hook-enforced-push.md)). GitHub Actions only deploys docs and runs a nightly scraper drift canary + advisory dependency audit. Never run raw `pytest` / `npm test`; use:

```bash
python scripts/agent/validate.py                  # tier chosen from the diff: docs | fast | frontend | backend | full
python scripts/agent/validate.py --tier backend   # force a tier
python scripts/agent/validate.py --only scrapers  # one domain gate: scrapers | ai | harness
```

Tiers: `docs` = `mkdocs build --strict`; `fast` = pre-commit (all files) + unit (xdist) — ≈ 75 s on the Windows host; `frontend` = + eslint + Vite build + Playwright e2e; `backend` = + ephemeral PostGIS/Redis stack + integration + contract + `alembic check`; `full` = everything. Any shell works (`.venv/Scripts/python.exe` on Windows); `bash scripts/agent/validate.sh [all|fast|…]` is a thin wrapper (`all` = `full`).

Validation runs against an **ephemeral test stack** (built by `validate.py` from `docker-compose.test.yml` — throwaway compose project `<COMPOSE_PROJECT_NAME>-test` with docker-assigned ports); the primary `imoveis` compose project is **never touched**, so validating is safe at any time, including during a live backfill.

A green run on a clean tree writes a validation stamp (`.run/validated/<tree-sha>.<tier>`). Shipping is a single command:

```bash
python scripts/agent/ship.py
```

It merges `origin/main` into the branch, checks the feature doc on story-key branches, validates (auto tier), squash-merges into `main` locally, re-checks the stamp for the merged tree, **pushes `main` to origin immediately** and deletes the branch. No Docker teardown or image pruning. A red validation blocks the merge — and `.claude/hooks/guard.py` denies any `git push` to `main` whose tree carries no stamp, so there is no zero-gate path to `main`.

Domain gates are path-triggered inside `validate.py` (run one alone with `--only`):

- **Scraper changes:** cassette suite + live dry-run (merge-blocking; refresh cassettes with `python scripts/dev/record_scraper_cassettes.py` on HTML drift).
- **AI prompt/client changes:** live Ollama golden tests (`--only ai`; skipped loudly when Ollama is unreachable).
- **API schema changes:** update/run the contract suite (`src/tests/contract/`) — it runs in the `backend` tier.
- **DB schema changes:** migrations run on the ephemeral stack inside the gate; the primary DB is migrated only via the explicit operator step `bash scripts/agent/migrate-primary.sh` (mutually exclusive with a running backfill).
- **Harness/script changes:** the `harness`-marked tests (≈ 14 min serial; also in `full`).

## Configuration

All settings live in [`configs/app_config.yaml`](configs/app_config.yaml) (loaded through `AppConfig`; never `os.getenv()` outside `config.py`). Any leaf can be overridden with `IMOVEIS_<SECTION>__<KEY>` env vars. Common env keys (durable local values go in `.env.local`, which is git-ignored):

```bash
API_KEY=local-dev-api-key          # required for SPA personalization + admin
DATABASE_URL=…                     # primary DB (Docker default: realestate)
REDIS_URL=…                        # default redis://localhost:6379/0
OLLAMA_HOST=http://localhost:11434 # maps to ai.ollama_url (docker uses host.docker.internal)
```

`docker-compose.yml` passes `API_KEY` / `JWT_SECRET` into the API container from the host env / `.env.local`. The committed YAML routes **all AI task classes to local backends** (pinned by a unit test); cloud backfill is enabled per host via `IMOVEIS_AI__ENRICHMENT_ROUTING__{VISUAL,SENTIMENT,DEAL_VERDICT}=gemma` in `.env.local` — never by editing the committed YAML.

### Cloud backfill runner (optional)

The multi-day corpus backfill (Gemma via the Gemini API, free-tier paced) runs as a host-side **systemd** service — never a compose service ([ADR 0006](docs/adr/0006-backfill-runner-hosting.md)). Install/inspect with `bash scripts/install-backfill-runner.sh [--check|--status|--print|--uninstall]`; it renders `deploy/systemd/imoveis-backfill-serve.service.in`, preflights the `.env.local` contract (`GEMINI_API_KEY`, `DATABASE_URL`, routing overrides), and manages the unit. The admin dashboard's backfill Start button only records a request — the supervisor consumes it.

## Testing

Risk-tiered, not blanket coverage (see `CLAUDE.md` for the full table): TDD on pure domain logic, recorded fixtures/cassettes for scrapers, characterization tests before changing existing invariants, minimal mocked paths for thin glue. Every bug fix ships a regression test.

- Backend: pytest under `src/tests/{unit,integration,contract}` (markers: `unit`, `integration`, `e2e`, `slow`); host tests isolate to `realestate_test` + Redis DB 15, never the primary data.
- Frontend: Playwright e2e under `frontend/tests/e2e` (`npm run test:e2e` — but run it via the `frontend`/`full` tier of `validate.py`).
- Lint: `pre-commit run --all-files` (isort, flake8, secrets, hygiene fixers) — the fixer hooks modify files on failure; commit their edits. `pre-commit install` once so they also run on every commit.
- Dependency audit: `bash scripts/ops/audit-deps.sh` (`pip-audit` + `npm audit`) is advisory and runs in the nightly GitHub workflow, never in the merge path; act on findings with a deliberate bump.

## Documentation

Full documentation is published via MkDocs Material (auto-deployed to GitHub Pages on push to `main`):

| Page | Description |
|------|-------------|
| [Setup Guide](docs/setup.md) | Installation, prerequisites, AI model setup, production deployment |
| [Architecture](docs/architecture.md) | Data flow, components, tech decisions |
| [API Reference](docs/api.md) | Endpoints, parameters, examples |
| [Harness Troubleshooting](docs/harness-troubleshooting.md) | Accumulated agent-workflow gotchas (validation, Playwright, scrapers, compose) |
| [Development Guide](docs/development-guide.md) | Generated dev-workflow reference (branch/validate/ship) |
| [Deployment Guide](docs/deployment-guide.md) | Generated deployment reference (incl. backfill runner) |
| [Add a locale](docs/i18n/add-a-locale.md) | i18n catalog / synonym / lexicon checklist |
| [Features](docs/features/) | Implementation notes per shipped story (`BIN-*` historical, `v0.N-*` current) |
| [ADRs](docs/adr/) | Architecture Decision Records (0001–0007) |

Preview docs locally: `pip install mkdocs-material && mkdocs serve`

## Product Planning (BMad Method)

Imoveis uses [BMad Method](https://docs.bmad-method.org/tutorials/getting-started/) v6 for planning **and** execution ([ADR 0005](docs/adr/0005-drop-linear-bmad-artifacts-sole-tracker.md)). Planning artifacts land in `_bmad-output/`; skills are framework-native under `.agents/skills/` (e.g. `bmad-help`, `bmad-prd`), with per-tool mirrors managed by the installer.

- Orientation: invoke **`bmad-help`**.
- Plan of record: `_bmad-output/planning-artifacts/epics.md`; execution status: `_bmad-output/implementation-artifacts/sprint-status.yaml`. Story keys look like `v0.13-s1.1`; follow-ups mint `v0.13-fu<N>` keys.
- Shipping: the BMad story cycle (`bmad-create-story` → `bmad-dev-story` → `bmad-code-review`, or `bmad-quick-dev` for small work, or the bmad-loop orchestrator) is bound to the `scripts/agent/` gates via `_bmad/custom/` overrides — no workflow bypasses them.
- Installed modules: `core`, `bmm`, `bmad-loop`, `tea`, `bmb`, `cis`, `wds` (targets: Cursor + Claude Code). Update with `npx bmad-method@<installed-version> install` re-using the recorded answers — check `_bmad/_config/manifest.yaml` first.

## Development Workflow

1. **Branch** — `git switch -c feat/<slug>`. Story branches embed the key: `feat/v0.14-s1.2-…` (that is what drives the feature-doc check).
2. **Implement** — risk-tiered TDD with conventional commits (`feat:`, `fix:`, `docs:`, …).
3. **Validate** — `python scripts/agent/validate.py` (tier from the diff).
4. **Document** — every story ships `docs/features/<story-key>-<slug>.md` (`bash scripts/agent/gen-docs.sh <slug> "<Title>" [story-key]` scaffolds it); `ship.py` refuses story-key branches without one.
5. **Ship** — `python scripts/agent/ship.py` (merge main in → validate → local squash-merge → push → branch deleted).
6. **Track** — set the story key to `done` in sprint-status.yaml **after** the merge is pushed.

**Parallel agents:** no worktree tooling in the repo — bmad-loop creates its own worktrees and Claude Code has native `--worktree`; each linked worktree gets its own ephemeral test project (hash-suffixed), so concurrent validation does not collide ([ADR 0007](docs/adr/0007-tiered-gate-and-hook-enforced-push.md)).

## License

Private repository. All rights reserved.
