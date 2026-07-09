# Imoveis — Project Context

Real-estate ingestion pipeline. Python **FastAPI** + **Celery** backend, **PostGIS**
(Postgres 15) storage, **Redis** broker, **React/Vite** frontend, local **Ollama**
models for AI enrichment.

## Repository map

- `src/api/` — FastAPI app (`api.main:app`, `/health`).
- `src/adapters/` — scrapers, queue (Celery `adapters.queue.tasks`), AI clients.
- `src/core/`, `src/infra/` — domain logic, DB/session, config loading.
- `src/tests/` — pytest suite (`pytest.ini`, testpaths `src/tests`).
- `frontend/` — React 18 + Vite (port & API target are env-driven).
- `configs/app_config.yaml` — platforms, Redis, DB, `gpu.semaphore_limit`.
- `alembic/` — DB migrations. `docker-compose.yml` — the stack.
- `scripts/` — project management scripts (`start.sh`, `stop.sh`, `test.sh`, etc.).
- `scripts/agent/*.sh` — agent-specific workflow tooling (worktree isolation, validation pipeline).
- `docs/` — published via MkDocs Material to GitHub Pages.
- `docs/features/` — implementation notes per shipped feature (agentic validation).

## Feature workflow (single-agent Cline CLI)

Features are tracked in **[Linear](https://linear.app/felipelrib/)** (team "Bino").
Use `linear_search_issues` MCP tool to find the next issue to work on.

Work through the shell scripts for each feature. The scripts handle port
isolation and docker project names so parallel worktrees don't conflict.

### Lifecycle

1. **Plan.** Read the Linear issue via MCP, then write `implementation_plan.md`
   in the worktree (steps, files, tests, risks). No implementation code before
   the plan exists.
2. **Isolate workspace.** `bash scripts/agent/setup-worktree.sh <feature-slug>`
   creates `.worktrees/<slug>` on branch `feat/<slug>` with unique ports in
   `.env.local`. Then `cd` into that worktree. Never work on `main`.
3. **Run services isolated.** `bash scripts/agent/run-services.sh` (whole stack) or
   pass service names for part of it. Uses your private ports + compose project.
4. **Implement + commit often.** Small conventional commits on your branch.
5. **Validate.** `bash scripts/agent/validate.sh [backend|frontend|all]` must pass.
6. **Finish the feature.**
   `bash scripts/agent/finish-feature.sh [<slug>]` — merges the feature branch
   into main, runs post-merge validation, tears down the worktree/containers,
   and deletes the feature branch. Handles exit codes:
   - **Exit 0** → merged, validated, cleaned up — done.
   - **Exit 2** → merge conflicts — resolve, commit, re-run.
   - **Exit 1** → validation failed after merge — fix, commit, re-run.

   Flags: `--validate-only` (sync + validate without merging), `--skip-docs` (skip gen-docs), `--dry-run` (preview).

7. **Update Linear.** Set the issue status to Done via Linear MCP.
8. **Document.** Generate feature docs in `docs/features/` via `gen-docs.sh`.

### Pausing and switching features

Because worktrees are isolated, you can pause work on one feature and switch
to another without conflicts:

```bash
# Pause feature A (just leave the worktree as-is)
cd ~/workfolder/imoveis

# Start feature B
bash scripts/agent/setup-worktree.sh feature-b
cd .worktrees/feature-b
# ... work on B ...

# Return to feature A
cd .worktrees/feature-a
# ... resume ...
```

### Dispatching from Cline CLI

To work a feature, say:
- `"Work on feature <slug> from Linear"` — triggers the full workflow
- `"Plan feature <slug>"` — creates the implementation plan
- `"Implement feature <slug>"` — starts coding from the plan
- `"Validate the current feature"` — runs validation only

You can also use skills: `/feature-pipeline`, `/validate-feature`, `/finish-feature`.

## Feature tracking

- **Linear board** — https://linear.app/felipelrib/ — the primary source of truth
  for features, docs, and infrastructure tasks. All feature specs, statuses, and
  dependencies live here. Use the Linear MCP to read issues and update statuses.
- **docs/features/** — implementation notes per shipped feature (useful for
  agentic validation and reference).

### Tiers (for reference, not used as Linear milestones)

- **Foundation** (config, DB, dedup, price history) — do first, serially.
- **Core Product** (scrapers, alerts, saved searches) — after foundation.
- **AI & Insights** (model config, deal summaries) — after config is stable.
- **UX Polish** (map, charts, toasts) — mostly frontend, parallel-safe.
- **Robustness** (circuit breakers, skip unchanged AI) — after the code they optimize.
- **Future** (backlog ideas) — not yet prioritized.

## Conventions

- Backend tests: `pytest` (markers: unit/integration/e2e/slow). Keep new code tested.
- Never hardcode ports/URLs — read them from env (`API_PORT`, `DATABASE_URL`, `REDIS_URL`).
- New feature = a doc in `docs/features/` + a README link.
- Commit messages: conventional format (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`).
- Single-user for now (no auth) — but design tables with nullable `owner` for future auth.

## Rule files

| File | Scope |
|------|-------|
| `guardrails.md` | Quick-reference summary (this file's rules, condensed) |
| `01-universal.md` | Portable — commit discipline, safety, security, TDD |
| `02-python-backend.md` | Portable — SQLAlchemy, FastAPI, Pydantic, Python testing |
| `03-react-frontend.md` | Portable — React patterns, Playwright, frontend security |
| `04-imoveis-specific.md` | Project — worktree isolation, Docker, feature pipeline, Linear |
| `testing.md` | Project — test pyramid, AI validation, scraper validation, contract tests |
| `ci.md` | Portable + project — pre-commit, GitHub Actions, security scanning |