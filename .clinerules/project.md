# Imoveis — Parallel Agent Workflow

Real-estate ingestion pipeline. Python **FastAPI** + **Celery** backend, **PostGIS**
(Postgres 15) storage, **Redis** broker, **React/Vite** frontend, local **Ollama**
models for AI enrichment. See `docs/local_agent_architecture.md` for the full agent
setup and `.clinerules/guardrails.md` for the hard rules (always injected).

## Repository map

- `src/api/` — FastAPI app (`api.main:app`, `/health`).
- `src/adapters/` — scrapers, queue (Celery `adapters.queue.tasks`), AI clients.
- `src/core/`, `src/infra/` — domain logic, DB/session, config loading.
- `src/tests/` — pytest suite (`pytest.ini`, testpaths `src/tests`).
- `frontend/` — React 18 + Vite (port & API target are env-driven).
- `configs/app_config.yaml` — platforms, Redis, DB, `gpu.semaphore_limit`.
- `alembic/` — DB migrations. `docker-compose.yml` — the stack.
- `scripts/agent/*.sh` — the workflow tooling below.

## The lifecycle — follow it in order for EVERY feature

Work through the shell scripts; they handle all port/isolation math so you don't have to.

1. **Plan.** Write `implementation_plan.md` in the worktree (steps, files, tests, risks).
   No implementation code before the plan exists.
2. **Isolate workspace.** `bash scripts/agent/setup-worktree.sh <feature-slug>`
   creates `.worktrees/<slug>` on branch `feat/<slug>` with unique ports in
   `.env.local`. Then `cd` into that worktree. Never work on `main`.
3. **Run services isolated.** `bash scripts/agent/run-services.sh` (whole stack) or
   pass service names for part of it. Uses your private ports + compose project.
4. **Implement + commit often.** Small conventional commits on your branch.
5. **Validate.** `bash scripts/agent/validate.sh [backend|frontend|all]` must pass.
6. **Sync with main (only when finished).** `bash scripts/agent/merge-revalidate.sh`
   — merges latest `main`, then re-validates. Exit 2 = resolve conflicts, commit,
   re-run. Exit 1 = fix feature, re-run. Exit 0 = ready.
7. **Document.** `bash scripts/agent/gen-docs.sh <slug> "<Title>"` scaffolds
   `docs/features/<slug>.md` and wires the README/index links; fill in the prose,
   then commit docs.
8. **Teardown when done.** `bash scripts/agent/teardown.sh` (add `--remove` to drop
   the worktree) to free ports and containers.

## Models (20 GB VRAM — one resident at a time)

- Planning/architecture → `deepseek-r1:14b`. Implementation → `devstral:24b`.
- Plan ALL features first, then implement — avoids model thrashing. Ollama is a
  single shared server; more agents means more inference throughput.
- When using Cline in Cursor, use the model you have available but respect the
  same principle: separate planning from implementation when possible.

## Conventions

- Backend tests: `pytest` (markers: unit/integration/e2e/slow). Keep new code tested.
- Never hardcode ports/URLs — read them from env (`API_PORT`, `DATABASE_URL`, `REDIS_URL`).
- New feature = a doc in `docs/features/` + a README link (step 7 does the wiring).
- Commit messages: conventional format (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`).
- Single-user for now (no auth) — but design tables with nullable `owner` for future auth.