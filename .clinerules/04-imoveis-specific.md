# IMOVEIS-SPECIFIC RULES — Do NOT copy to other projects

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

## Isolation (NON-NEGOTIABLE)

1. NEVER commit, edit files, or run `docker compose up` on the `main` branch or in
   the primary checkout. You MUST be inside a git worktree under `.worktrees/`.
   If `git rev-parse --abbrev-ref HEAD` says `main`, STOP and run
   `bash scripts/agent/setup-worktree.sh <feature-slug>` first.

2. NEVER use default ports (5432, 6379, 8000, 5173) or `docker compose` without
   `--env-file .env.local -p "$COMPOSE_PROJECT_NAME"`. Always start services via
   `bash scripts/agent/run-services.sh`, which uses your worktree's unique ports.

## Workflow

3. PLAN BEFORE CODE. An `implementation_plan.md` must exist in your worktree
   before you write any implementation code. Follow the plan.
   The plan MUST include a **testing strategy** section specifying what test types
   (unit/integration/contract/snapshot) cover which modules.

4. COMMIT FREQUENTLY to your feature branch with conventional messages
   (`feat:`, `fix:`, `test:`, `docs:`). Never leave the tree dirty for long.

5. VALIDATE before declaring done: `bash scripts/agent/validate.sh` must pass.
   When the feature is complete, use `bash scripts/agent/finish-feature.sh` to
   merge into main, validate post-merge, tear down the worktree, and clean up.
   Handle exit codes: 0 = done, 1 = fix + re-run, 2 = resolve conflicts + re-run.

6. SCOPE DISCIPLINE — do not refactor code beyond what the feature requires.
   The `implementation_plan.md` defines scope — stick to it.

## Safety

7. NEVER `git push --force`, delete another branch/worktree, or `docker system prune`.

8. Before every commit, verify:
   - Commit messages MUST use conventional format.
   - Check the diff for hardcoded ports (5432, 6379, 8000, 5173) or localhost URLs.
   - No API keys, passwords, tokens, or secrets in the diff.
   - The strings `imoveis_secret` and `dev-secret-key` are **forbidden** in any committed file.
   - No `.env.local` files being committed (should be in `.gitignore`).
   - Never commit directly to `main`. Always be on a `feat/*` branch inside `.worktrees/`.

## Docker validation

9. Before running `bash scripts/agent/validate.sh backend`, ensure the Docker
   image is up to date with: `docker compose build api` (or `--no-cache` if
   test files changed). Stale images cause phantom test failures.

10. Config tests (`test_config.py`) must clear `get_config()`'s `lru_cache` in
    an `autouse` fixture when running inside Docker containers where
    `DATABASE_URL` and `REDIS_URL` env vars are set by docker-compose.
    The fixture must call `get_config.cache_clear()` AND remove those env
    vars via `monkeypatch.delenv`.

## Test discipline

11. NEVER dismiss test failures as "pre-existing" without confirming. Before
    merging, run `validate.sh backend` on a FRESH Docker volume (`docker
    compose -p <project> down -v` first) to eliminate stale data. If tests
    fail, investigate the root cause.

12. Integration test fixtures MUST clean up after themselves. Every `test_db`
    or `session` fixture that creates a database session must truncate all
    tables in its teardown.

## Skill usage

13. When the user says "work on the next ticket", "run feature X", or similar
    pipeline-like requests, you MUST use the `feature-pipeline` skill via
    `use_skill(skill_name="feature-pipeline")`. Do not attempt to manually
    replicate the skill's steps.

## Feature workflow

Features are tracked in **[Linear](https://linear.app/felipelrib/)** (team "Bino").
Use `linear_search_issues` MCP tool to find the next issue to work on.

### Lifecycle

1. **Plan.** Read the Linear issue via MCP, then write `implementation_plan.md`
   in the worktree (steps, files, tests, risks).
2. **Isolate workspace.** `bash scripts/agent/setup-worktree.sh <feature-slug>`
   creates `.worktrees/<slug>` on branch `feat/<slug>`.
3. **Run services.** `bash scripts/agent/run-services.sh`
4. **Implement + commit.** Small conventional commits.
5. **Validate.** `bash scripts/agent/validate.sh [backend|frontend|all]`.
6. **Finish.** `bash scripts/agent/finish-feature.sh [<slug>]`.
   - Exit 0 → merged, validated, cleaned up.
   - Exit 2 → merge conflicts — resolve, commit, re-run.
   - Exit 1 → validation failed — fix, commit, re-run.
7. **Update Linear.** Set the issue status to Done via Linear MCP.
8. **Document.** Generate feature docs via `gen-docs.sh`.

### Dispatching from Cline CLI

- `"Work on feature <slug> from Linear"` — full pipeline
- `"Plan feature <slug>"` — creates `implementation_plan.md`
- `"Implement feature <slug>"` — codes from the plan
- `"Validate the current feature"` — runs `validate.sh`

## Feature tracking

- **Linear board** — https://linear.app/felipelrib/ — primary source of truth.
- **docs/features/** — implementation notes per shipped feature.
- `done-state-id` for Bino team: `fa058318-6dde-441e-91cb-5939c33e4fb1`
- `projectId` for "Imoveis — Deal Tracker": `2b293958-ee46-48f1-98aa-6d54abba468d`

## Scraper validation

- After ANY scraper change, run: `python scripts/dev/test_scraper_dryrun.py`
- After parser logic change, run: `pytest src/tests/unit/test_olx.py -v`
- Circuit breaker changes: run `pytest src/tests/unit/test_cb.py -v`

## AI output validation (see testing.md)

- After prompt/client changes in `src/adapters/ai/`: run `scripts/agent/validate-ai.sh`
- Golden-file tests must pass: score deviations ≤ 0.15 from baseline

## Contract tests

- API schema changes: update and run contract tests in `src/tests/contract/`
- DB schema changes: run `alembic check` to verify models match schema

## Conventions

- Backend tests: `pytest` (markers: unit/integration/e2e/slow).
- Never hardcode ports/URLs — read from env or config.
- New feature = a doc in `docs/features/` + a README link.
- Single-user for now (no auth) — but design tables with nullable `owner` for future auth.