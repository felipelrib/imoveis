# Imoveis — Master Rules

Real-estate ingestion pipeline. Python **FastAPI** + **Celery**, **PostGIS**, **Redis**, **React/Vite**, local **Ollama** models.

## Dual-Model Protocol

This project uses a **Planner** (strong model) and an **Implementer** (cheap/fast model).

### Planner Role
- Read the Linear issue and codebase to understand scope.
- Write a detailed `implementation_plan.md` (see format below).
- The plan is the **contract** — it must be complete enough that the Implementer can execute without architectural questions.
- Include exact file paths, function signatures, and test names.
- NEVER write implementation code — only the plan.

### Implementer Role
- Read `implementation_plan.md` and execute it step by step.
- Follow the plan EXACTLY. Do not refactor, optimize, or redesign beyond what the plan specifies.
- If you encounter an ambiguity, STOP and ask — do not guess.
- If you touch >3 files not listed in the plan, STOP and flag it.
- Commit after each meaningful step.
- Run validation before declaring done.

### `implementation_plan.md` Format (MANDATORY)

Every plan must have these sections:

```markdown
# Implementation Plan: <Feature Name> (<Linear ID>)

## Goal
One paragraph. What this feature does and why.

## Affected Areas
| File | Change |
|------|--------|
| `path/to/file.py` | What changes in this file |

## Step-by-Step Implementation
### Step 1 — <title>
Exact description of what to do. Include function signatures,
class names, and which existing code to modify.

### Step 2 — <title>
...

## Data / Schema Changes
Alembic migrations needed? New columns? None?

## Testing Strategy
| Test Type | File | What It Covers |
|-----------|------|---------------|
| Unit | `src/tests/unit/test_X.py` | ... |
| Integration | `src/tests/integration/test_Y.py` | ... |

## Validation Plan
Exact commands to run and expected outcomes.

## Risks
Bullet list of what could go wrong and mitigations.
```

## Repository Map

- `src/api/` — FastAPI app (`api.main:app`, `/health`).
- `src/adapters/` — scrapers, queue (Celery), AI clients, metrics.
- `src/core/` — business logic (dedup, entities, exceptions).
- `src/infra/` — config loading, DB session, Redis, logging.
- `src/tests/` — pytest suite (markers: unit/integration/e2e/slow).
- `frontend/` — React 18 + Vite.
- `configs/app_config.yaml` — single source of truth for all settings.
- `alembic/` — DB migrations.
- `scripts/agent/` — agent workflow tooling (branch setup, validation, finishing).
- `docs/` — MkDocs Material site. `docs/features/` for feature implementation notes.

## Session Lifecycle

### Start of Every Session (NON-NEGOTIABLE)

**FIRST action — before ANY file reads or exploration:**

```bash
git rev-parse --abbrev-ref HEAD
```

| Current branch | Action |
|---|---|
| `main` | **STOP.** Run `bash scripts/agent/setup-branch.sh "<task-slug>"` before any edits. |
| Feature branch from a past session | Verify it matches the current task via `git log --oneline -3`. If it doesn't match, STOP and ask. |
| Feature branch matching the task | Proceed, but sync first (see below). |

After confirming the correct branch:
```bash
git pull origin "$(git rev-parse --abbrev-ref HEAD)"
pip install -r requirements.txt
(cd frontend && npm install)
```

If resuming, read `implementation_plan.md` and `git log --oneline -5` for context.

### End of Every Task (MANDATORY)

1. **Commit** all remaining changes with conventional messages.
2. **Validate**: `bash scripts/agent/validate.sh all`
3. **Push & PR**: `bash scripts/agent/finish-feature.sh --pr`
4. **Update Linear** to Done via MCP (see below).
5. **Report**: branch pushed, features delivered, files changed, follow-ups.

## Validation & Finishing

NEVER run raw `pytest` or `npm test`. ALWAYS use:

```bash
bash scripts/agent/validate.sh fast      # lint + unit (<60s, for bug fixes)
bash scripts/agent/validate.sh backend   # lint + unit + integration + contract
bash scripts/agent/validate.sh all       # full CI gate (before PR)
```

NEVER manually `git push` or `gh pr create`. ALWAYS use:

```bash
bash scripts/agent/finish-feature.sh --pr
```

Exit codes: 0 = ready for PR, 1 = fix + re-run.

### Validation Discipline (NON-NEGOTIABLE)

NEVER skip, work around, or ignore validation failures. If any tool fails:
1. Diagnose the root cause — read the error.
2. Fix the issue.
3. Re-run validation — confirm it passes.
4. Only then proceed.

If a tool is missing (`isort`, `flake8`, `pytest`), install it via `pip install`.

### Docker Validation

Before `validate.sh backend`, rebuild if test files changed:
```bash
docker compose build api
```

Config tests must clear `get_config()`'s `lru_cache` via `autouse` fixture when `DATABASE_URL`/`REDIS_URL` env vars are set by docker-compose.

## Linear Integration

Features are tracked in **Linear** (team "Bino"). Use MCP tools:

- `linear_search_issues` — find issues.
- `linear_get_project_milestones` — check milestones.
- `linear_bulk_update_issues` — update status.

### Key IDs

| Entity | ID |
|--------|---|
| Project (Imoveis — Deal Tracker) | `2b293958-ee46-48f1-98aa-6d54abba468d` |
| State: In Progress | `7de50ed1-0de6-4f06-89f6-6816991f106f` |
| State: Done | `fa058318-6dde-441e-91cb-5939c33e4fb1` |

### Milestone Ordering (NON-NEGOTIABLE)

1. Use `linear_get_project_milestones` to list all milestones.
2. Work through milestones **in order** (lowest `sortOrder` where `status != done`).
3. Within a milestone, pick the highest-priority unfinished issue (lower number = higher priority).
4. Only advance to the next milestone when ALL current milestone issues are Done.

### Skill Usage

When the user says "work on the next ticket", "run feature X", or similar:
- Your FIRST action MUST be `use_skill(skill_name="feature-pipeline")`.
- Do NOT manually replicate the skill's steps.

## Commit & Safety

- Conventional format: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
- One logical change per commit.
- NEVER `git push --force`.
- NEVER delete another developer's branch.
- NEVER run `docker system prune` or `docker volume rm` without user approval.

### Security (NON-NEGOTIABLE)

- NEVER hardcode passwords, API keys, or tokens. Defaults must be `""` or from env vars.
- The strings `imoveis_secret` and `dev-secret-key` are **forbidden** in committed files.
- NEVER use `eval()`, `exec()`, or `os.system()` with user-supplied strings.
- NEVER use f-strings for SQL queries — always parameterize.
- Run secret scan before committing:
  ```bash
  git grep -nP '(password|secret|api_key).*=.*["'"'"'][a-zA-Z0-9]' src/ frontend/src/
  ```

## Scoping

- NEVER refactor code outside the feature scope.
- If you touch >3 files not in the plan, STOP and update the plan first.
- Do not optimize code that isn't causing a measurable problem.

## Conventions

- All settings from `AppConfig` (Pydantic, loaded from YAML + env). Never `os.getenv()` outside `config.py`.
- Never hardcode ports/URLs — read from env or config.
- New feature = numbered doc in `docs/features/` (see below) + README link.
- Single-user for now (no auth) — design tables with nullable `owner`.

## Feature Documentation (NON-NEGOTIABLE)

Every completed feature must have **one numbered markdown file** in `docs/features/`.

### Naming convention

```
docs/features/<NN>-<feature-slug>.md
```

`<NN>` is the next sequential two-digit number. Determine it with:

```bash
ls docs/features/ | grep -E '^[0-9]' | sort | tail -1
```

### Required template

**Every doc must use `docs/features/_template.md` verbatim.** All six sections are
mandatory — do not omit or rename any of them:

1. **Title line** — `# <feature-name> — <one-line description>`
2. **Header quote** — branch, Linear ID, status
3. **## Problem** — 2–4 sentences: what user pain or technical gap this addresses.
4. **## Approach** — bullet list only; explain *why* not just *what*.
5. **## Changes** — pipe-table of every file touched. Mark new files `NEW —`.
6. **## New Dependencies** — list packages added or write `None`.
7. **## How to Test** — numbered steps or a single test command.
8. **## Notes / Follow-ups** — ALL bugs found during review go here, formatted as:
   `**BUG (Severity)**: description — fix hint.`

### Rules

- Do **NOT** write freeform narrative docs.
- Do **NOT** create unnumbered files (e.g. `config-yaml-loader.md`).
- Do **NOT** omit any section — write `None` or `N/A` if not applicable.
- Bugs found during review belong **only** in the feature doc `Notes / Follow-ups`
  section — not in separate files.

## Scraper Validation

After ANY scraper change: `python scripts/dev/test_scraper_dryrun.py`
After parser logic change: `pytest src/tests/unit/test_olx.py -v`
Circuit breaker changes: `pytest src/tests/unit/test_cb.py -v`

## AI Output Validation

After prompt/client changes in `src/adapters/ai/`: `bash scripts/agent/validate-ai.sh`
Golden-file tests: score deviations ≤ 0.15 from baseline.

## Contract Tests

API schema changes: update and run `src/tests/contract/`.
DB schema changes: `alembic check` to verify models match schema.
