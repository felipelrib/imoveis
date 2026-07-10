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

## Isolation & Setup (NON-NEGOTIABLE)

1. NEVER commit or edit files on the `main` branch.
   If `git rev-parse --abbrev-ref HEAD` says `main`, STOP and run
   `bash scripts/agent/setup-branch.sh <feature-slug>` first.

2. Ensure your dependencies are up to date by running `pip install -r requirements.txt` and `npm install` inside `frontend/`.
   Always start services via `docker-compose up -d` in the root directory before running tests or migrations.

## Workflow

3. PLAN BEFORE CODE. An `implementation_plan.md` must exist
   before you write any implementation code. Follow the plan.
   The plan MUST include a **testing strategy** section specifying what test types
   (unit/integration/contract/snapshot) cover which modules.

4. COMMIT FREQUENTLY to your feature branch with conventional messages
   (`feat:`, `fix:`, `test:`, `docs:`). Never leave the tree dirty for long.

5. VALIDATE before declaring done: `bash scripts/agent/validate.sh` must pass.
   When the feature is complete, use `bash scripts/agent/finish-feature.sh --pr` to
   push your branch and prepare for a Pull Request. Do not merge to main locally.
   Handle exit codes: 0 = done (ready for PR), 1 = fix + re-run.

6. SCOPE DISCIPLINE — do not refactor code beyond what the feature requires.
   The `implementation_plan.md` defines scope — stick to it.

## Safety

7. NEVER `git push --force`, delete another user's branch, or `docker system prune`.

8. Before every commit, verify:
   - Commit messages MUST use conventional format.
   - Check the diff for hardcoded ports (5432, 6379, 8000, 5173) or localhost URLs.
   - No API keys, passwords, tokens, or secrets in the diff.
   - The strings `imoveis_secret` and `dev-secret-key` are **forbidden** in any committed file.
   - No `.env.local` files being committed (should be in `.gitignore`).
   - Never commit directly to `main`. Always be on a feature branch.

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

13. When the user says "work on the next ticket", "run feature X", "work on the
    next task from Linear", or any similar pipeline-like request, your FIRST
    action MUST be `use_skill(skill_name="feature-pipeline")`. Do NOT manually
    replicate the skill's steps. Do NOT search Linear and pick an issue yourself.
    The skill handles milestone ordering, issue selection, branch setup, and
    the full lifecycle. Only after the skill is activated should you proceed
    with implementation.

## Validation discipline (NON-NEGOTIABLE)

14. NEVER skip, work around, or ignore validation failures. If `validate.sh`,
    `finish-feature.sh`, `npm ci`, `pytest`, `isort`, `flake8`, or any other
    validation tool fails, you MUST:
    1. **Diagnose the root cause** — read the error message carefully.
    2. **Fix the issue** — install missing tools, fix broken configs, resolve
       dependency problems, fix code errors.
    3. **Re-run validation** — confirm it passes.
    4. Only then proceed.
    If a tool is missing (e.g. `isort`, `flake8`, `pytest`), install it via
    `pip install` before running validation. If `npm ci` fails because
    `package-lock.json` is missing, investigate why and fix it — do NOT
    switch to `npm install` as a workaround.
    The only exception is using `--soft` mode on `validate.sh` for
    rules/docs-only changes that don't touch source code.

## Feature workflow

Features are tracked in **[Linear](https://linear.app/felipelrib/)** (team "Bino").
Use `linear_search_issues` MCP tool to find the next issue to work on.

### Milestone ordering (NON-NEGOTIABLE)

When selecting the next issue to work on, you MUST:

1. **Check milestones first.** Use `linear_get_project_milestones` to list all
   milestones for project `2b293958-ee46-48f1-98aa-6d54abba468d`.
2. **Work through milestones in order.** Start with the earliest uncompleted
   milestone (lowest `sortOrder` where `status != done`). Do NOT skip ahead to
   a later milestone.
3. **Within a milestone, pick the highest-priority unfinished issue.** Use
   `linear_search_issues` scoped to that milestone's issues. Lower priority
   number = higher priority (0 > 1 > 2 > 3 > 4).
4. **Only promote to the next milestone** when ALL issues in the current
   milestone are in "Done" state.

### Lifecycle

1. **Plan.** Read the Linear issue via MCP, then write `implementation_plan.md`
   (steps, files, tests, risks).
2. **Isolate workspace.** `bash scripts/agent/setup-branch.sh <feature-slug>`
   creates branch `feat/<slug>` and updates dependencies.
3. **Run services.** `docker-compose up -d`
4. **Implement + commit.** Small conventional commits. Pre-commit and pre-push
   hooks run automatically on each commit/push.
5. **Validate locally.** `bash scripts/agent/validate.sh all` — must pass
   before opening a PR. Runs lint, unit, integration, contract, frontend
   build, AND Playwright E2E.
6. **Open PR and wait for CI gate.** Use `bash scripts/agent/finish-feature.sh --pr`
   to push, open a PR, and block until all CI checks pass.
   - Exit 0 → pushed, validated, ready for PR.
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
