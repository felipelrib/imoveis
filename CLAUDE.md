# Imoveis — Deal Tracker

Real-estate ingestion pipeline. Python **FastAPI** + **Celery**, **PostGIS**, **Redis**, **React/Vite**, local **Ollama** models.

## What this system does

Imoveis scrapes rental and sale listings from multiple platforms (QuintoAndar, OLX), deduplicates them across platforms using geospatial proximity + heuristic matching (one property, one record), tracks price history and surfaces drops, enriches listings with local AI models (Ollama: visual condition assessment, neighbourhood sentiment, statistical valuation), and presents everything as a score-coloured deal dashboard.

```
Scraper → Normalize → Dedupe → DB → Metrics → AI Enrich
                                          ↓
                                    Price History
                                          ↓
                                    Alerts / Dashboard
```

| Component   | Technology              | Purpose                          |
|-------------|--------------------------|-----------------------------------|
| API         | FastAPI                  | REST endpoints, admin controls    |
| Task Queue  | Celery + Redis           | Async scraping, AI enrichment     |
| Database    | PostgreSQL 17 + PostGIS + pgvector | Geospatial + embedding storage |
| AI          | Ollama / LM Studio       | Local VLM + text models           |
| Frontend    | React 19 + Vite 8        | Score-coloured property grid      |
| Config      | Pydantic + YAML          | Single source of truth            |
| Migrations  | Alembic                  | Schema versioning                 |
| CI/CD       | GitHub Actions           | Tests, lint, build, security      |
| Tracking    | BMad artifacts (`_bmad-output/`) | epics.md = plan of record; sprint-status.yaml = execution status (ADR 0005) |

Full docs: `docs/setup.md` (install/run), `docs/architecture.md` (data flow/components), `docs/api.md` (endpoints), `docs/features/` (per-feature notes), `docs/adr/` (architecture decisions).

## Planning & implementation

**BMad Method** owns product planning/solutioning (PRD, architecture spine, epics, readiness, sprint-status). Artifacts: `_bmad-output/`. BMad skills: `.agents/skills/bmad-*` (framework-native, not Cursor- or Claude-specific — invoke by name, e.g. `bmad-help`, `bmad-prd`). Bridge: [`.claude/skills/imoveis-planning-bridge/SKILL.md`](.claude/skills/imoveis-planning-bridge/SKILL.md) + `docs/adr/0003-bmad-planning-bridge.md`. Run each major BMad workflow in a **fresh chat/session**.

**The sprint file + this pipeline** own execution (Linear dropped 2026-08-05 — ADR 0005; the workspace is a read-only archive of `BIN-*` history). Plan of record: `_bmad-output/planning-artifacts/epics.md`. Status: `_bmad-output/implementation-artifacts/sprint-status.yaml`. After `bmad-create-story` (optional), implement via feature-pipeline gates — never skip `validate.sh` / `finish-feature.sh`.

**Ticket → ship is ALWAYS `feature-pipeline` — never a BMad dev-side skill.** BMad installs generic implementation loops (`bmad-dev-story`, `bmad-dev-auto`, `bmad-quick-dev`) whose trigger phrases ("implement the next story", "dev this story", "build/fix/tweak…") shadow this pipeline. Do **not** let them run for Imoveis ticket delivery: they bypass `validate.sh` / `finish-feature.sh` / the squash-merge gate and the contract/scraper/AI + docker-rebuild rules, and `bmad-dev-story` explicitly overrides the STOP-at-3-unexpected-files and Plan-Mode discipline this repo requires. BMad dev/review skills are opt-in *assists inside* the pipeline (a task checklist, an adversarial review pass) — they can never replace or short-circuit it.

Use **Plan Mode** for non-trivial work, then implement in the same session. An optional `implementation_plan.md` is fine for long tasks — not a dual-model handoff.

For "work on the next ticket", "run feature X", or the full pipeline: read and follow [`.claude/skills/feature-pipeline/SKILL.md`](.claude/skills/feature-pipeline/SKILL.md).

## Repository map

- `src/api/` — FastAPI app (`api.main:app`, `/health`).
- `src/adapters/` — scrapers, queue (Celery), AI clients, metrics.
- `src/core/` — business logic (dedup, entities, exceptions).
- `src/infra/` — config loading, DB session, Redis, logging.
- `src/tests/` — pytest suite (markers: unit/integration/e2e/slow).
- `frontend/` — React 19 + Vite 8.
- `configs/app_config.yaml` — single source of truth for all settings.
- `alembic/` — DB migrations.
- `scripts/agent/` — agent workflow tooling (branch setup, validation, finishing) — shared/committed, tool-agnostic.
- `docs/` — MkDocs Material site. `docs/features/` for feature implementation notes.
- `.claude/skills/` — local, Claude-specific workflow skills (gitignored; see harness section below).
- `.agents/skills/` — committed BMad Method skills (framework-native, shared across tools).

## Session lifecycle

### Start (NON-NEGOTIABLE)

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

### End of every task (MANDATORY)

1. **Commit** remaining changes with conventional messages.
2. **Validate**: `bash scripts/agent/validate.sh all`
3. **Push, PR, merge & cleanup**: `bash scripts/agent/finish-feature.sh --pr`
   - This must **squash-merge** the PR into `main` after CI green. Merge-ready ≠ finished.
   - Worktree: script runs `teardown.sh --remove`; then `cd` back into the **primary checkout** path (Claude Code's shell keeps a persistent working directory within a session — there is no Cursor-style "move agent to root" MCP tool; just `cd` to the primary repo path, e.g. via `git worktree list` to find it).
   - Primary: script returns checkout to `main`.
   - Always runs `scripts/agent/docker-cleanup.sh` (stopped containers + dangling/unused feat|wt images + build cache). Keeps primary `imoveis-*` + base images; never volumes.
4. **Babysit** if CI/merge stalls — follow [`.claude/skills/babysit-pr/SKILL.md`](.claude/skills/babysit-pr/SKILL.md) through **merge + cleanup**.
5. **Docker temps (required)** — if wrap-up did not go through `finish-feature.sh --pr` / `teardown.sh`, run `bash scripts/agent/docker-cleanup.sh` yourself before closing the session. Must free leftover `feat-*` / `fix-*` / `imoveis-wt-*` images; never delete the fixed local `imoveis-*` stack or named volumes.
6. **Update sprint-status.yaml** — set the story key to `done` **after the PR is merged** (never downgrade; prefer committing it on the feature branch before merge when possible). Then run [epic-completion](.claude/skills/epic-completion/SKILL.md) §A→§B→§C on a **fresh** re-read of sprint-status.yaml + epics.md (do not trust a kickoff "not last" note — parallel agents race that). Set `epic-N: done` only when close-ready.
7. **Report**: branch, **merged** PR URL, features delivered, epic close verdict (remaining sibling story keys / close-ready / epic-N done / N/A), follow-ups.

## Validation & finishing

NEVER run raw `pytest` or `npm test`. ALWAYS use:

```bash
bash scripts/agent/validate.sh fast      # lint + unit (<60s)
bash scripts/agent/validate.sh backend   # lint + unit + integration + contract
bash scripts/agent/validate.sh all       # full CI gate (before PR)
```

NEVER manually `git push` or `gh pr create`. ALWAYS use:

```bash
bash scripts/agent/finish-feature.sh --pr
```

If validation fails: diagnose → fix → re-run. Missing tools (`isort`, `flake8`, `pytest`): `pip install`.

Before `validate.sh backend`, rebuild the API image when tests **or Alembic migrations** changed (`docker compose build api`) — compose runs migrations from the image, not the host tree. Unset a stale host `DATABASE_URL` before validate if integration fails with password auth errors (validate derives URLs from `.env.local` ports).

Config tests must clear `get_config()`'s `lru_cache` via `autouse` fixture when `DATABASE_URL`/`REDIS_URL` are set by docker-compose.

**API response schemas:** keep Pydantic `response_model` types aligned with domain producers (AI scores are floats in `[0.0, 1.0]`, not ints). Contract tests must **not** treat every 500 as "DB down" when the properties schema is queryable — that hid BIN-56 `ResponseValidationError`. Prefer failing when the table exists; skip only when schema/infra is missing. Unit tests that hit rate-limited routes must bypass slowapi Redis (unit CI has none).

## Tracking (BMad artifacts — Linear dropped, ADR 0005)

**No external tracker.** Plan of record: `_bmad-output/planning-artifacts/epics.md`. Execution status: `_bmad-output/implementation-artifacts/sprint-status.yaml`. Story keys are `v<milestone>-s<epic>.<story>` (e.g. `v0.13-s1.1`); follow-ups without a story mint `v<milestone>-fu<N>` keys in sprint-status.yaml. Do **not** update Linear — the workspace is a read-only archive of pre-v0.13 `BIN-*` history (v0.13 leftovers there were canceled 2026-08-05).

### Milestone ordering

Milestones are **versioned only** (`v0.1`, `v0.2`, …), recorded in the PRD + epics.md (`planningTarget`). Prefer **one large multi-story epic per numbered milestone**; thin single-story waves also get their own `v0.N`.

When defining a milestone (PRD/epics frontmatter or prose), use **only**: a short prose paragraph of what the work contains, `**Theme:**` one line, `**Exit criteria:**` concrete testable outcomes. No status banners, cross-milestone links, or process essays.

1. Work the earliest milestone whose epics.md stories are not all `done` in sprint-status.yaml.
2. Within it, follow the sequencing gates in epics.md frontmatter (`tracking:` note) / the epic's parallel-work-plan; otherwise lowest story number first.
3. Advance only when ALL current-milestone stories are `done` (explicitly deferred/parked stories noted in epics.md per epic exit criteria).

### Epic refine / multi-story planning (NON-NEGOTIABLE)

Whenever you **refine an epic** and/or **add multiple stories** to epics.md, the wrap-up reply to the user **must** include a **Parallel work plan** — not only a flat story table:

1. **Waves** — group stories into sequential waves; within each wave, name every story key that can run **in parallel**.
2. **Gates** — what must be `done` before the next wave starts.
3. **Start here** — the concrete first parallel set, with story keys.
4. **Do not parallelize** — stories that look independent but must stay serial (shared files, same migration, foundation-before-consumer).

Record the sequencing gates in epics.md (frontmatter `tracking:` note or an epic-level note) so future sessions don't re-derive them. Skipping this section after multi-story epic work is a harness miss.

### Epic completion

Every versioned milestone is delivered as one or more epics.md epics whose stories are tracked as sprint-status.yaml keys. On every pipeline run that finishes a story **belonging to an epic**:

1. **After story `done` (mandatory):** re-read sprint-status.yaml + epics.md **fresh** ([epic-completion](.claude/skills/epic-completion/SKILL.md) §A). If no unfinished sibling story keys remain, run checklist §B then close gate §C. Set `epic-N: done` only when close-ready.
2. **Do not** rely on a start-of-feature "am I last?" check — parallel agents race that signal. Never leave a fully delivered epic un-closed; never mark `done` while leftovers remain (non-story follow-ups in feature docs, open `action_items`, deferred ACs).

## Commit & safety

- Conventional: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
- NEVER `git push --force`. NEVER delete another developer's branch.
- NEVER `docker system prune` / `docker volume rm` / `docker compose down -v` on the primary stack without user approval (see BIN-60 / feature 45).
- ALWAYS prune temps after wrap-up via `bash scripts/agent/docker-cleanup.sh` (or finish/teardown, which call it). Removes stopped containers, dangling images, unused feature/worktree tagged images, and build cache. Keeps primary `imoveis-*` (not `imoveis-wt-*`), third-party bases, and images for still-running Compose projects. Never touches named volumes / never `docker system prune --volumes`.
- NEVER hardcode passwords, API keys, or tokens. Defaults `""` or env vars.
- Forbidden in committed files: `imoveis_secret`, `dev-secret-key`.
- NEVER `eval()`/`exec()`/`os.system()` with user input; NEVER f-string SQL — parameterize.
- Secret scan before commit: `git grep -nP '(password|secret|api_key).*=.*["'"'"'][a-zA-Z0-9]' src/ frontend/src/`

## Scoping

- NEVER refactor outside feature scope. If touching >3 unexpected files, STOP and ask.
- Do not optimize code that isn't causing a measurable problem.

## Conventions

- All settings from `AppConfig` (YAML + env). Never `os.getenv()` outside `config.py`.
- Never hardcode ports/URLs — env or config.
- New feature = `docs/features/<story-key>-<slug>.md` (e.g. `v0.13-s1.1-…`) + README link when user-facing.
- **Bug fixes require a regression spec** (Playwright and/or pytest) that fails without the fix; do not ship `fix:` as code-only.
- Single-user for now — design tables with nullable `owner`.

### Testing discipline (AI agents)

Risk-tiered — not blanket 100% coverage or universal TDD:

| Surface | Approach |
|---|---|
| Pure domain (`src/core/`, filters, classifiers, scoring math) | **TDD**: failing unit tests first; aim high branch coverage on new code |
| Scrapers / availability / HTML-JSON drift | **Oracle-first**: live probe → fixture/cassette → tests → implement |
| Brownfield projection/SQL/dedupe behavior | **Characterization lock** (one assert encoding the invariant) before changing |
| Thin glue (Celery enqueue, admin POST wrappers, http_client) | One mocked happy/error path is enough — no theater coverage |

- Do **not** chase 100% line coverage on adapters/wiring; Sonar new-code gate (~80%) should come from domain + classifier branches.
- Multi-branch parsers: split helpers early (load → signal → fallback) to avoid Sonar S3776 mid-babysit.
- External 403/proxy failures are `unknown`, not product regressions — never treat Cloudflare blocks as parse failures.
- `get_logger` kwargs become LogRecord extras — never pass reserved keys (`name`, `msg`, `args`, `level`, …) or integration tests blow up with `KeyError: Attempt to overwrite 'name' in LogRecord` (BIN-87: use `neighbourhood_name`).
- Idempotent loaders (YAML/GeoJSON apply): unit-test update/skip/unknown with a mocked session so Sonar new-code coverage does not depend only on integration.

## Feature documentation (NON-NEGOTIABLE)

Every completed feature: `docs/features/<story-key>-<feature-slug>.md` using `docs/features/_template.md` verbatim (all sections mandatory). **The filename prefix is the BMad story key** (`v0.13-s1.1`, from epics.md / sprint-status.yaml) — unique by construction, so parallel PRs never collide (the same property the Linear-ID scheme had, which itself replaced racing `max(NN)+1` numbering). Keep the `Story: \`<story-key>\`` header field in sync with the filename. Include the key in the branch name (`feat/v0.13-s1.1-…`) so `gen-docs.sh` derives it.

- One doc per story. A follow-up/regression with no story of its own mints a **`v0.N-fu<N>` key in sprint-status.yaml** (one line, status + short description) and names the doc after it — do not reuse another story's key or fall back to a bare number.
- Legacy `BIN-<id>-*` and numeric-prefixed docs are history — keep their names; do not rename them to story keys.

Bugs found during review go only in **Notes / Follow-ups** as `**BUG (Severity)**: description — fix hint.`

## Domain validation hooks

After a change to one of these surfaces, run its gate before calling the work done:

- **Scraper change:** `bash scripts/agent/validate-scrapers.sh --require-live` (merge-blocking). On HTML drift, refresh cassettes via `python scripts/dev/record_scraper_cassettes.py` — never drop the CI gate.
- **AI prompt/client change:** `bash scripts/agent/validate-ai.sh` (from WSL set `OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434` when Ollama binds on Windows; keep host `OLLAMA_NUM_PARALLEL` equal to `gpu.semaphore_limit` — oversized parallel × `num_ctx` spills VRAM into system RAM). After concurrency/VRAM changes: `PYTHONPATH=src python scripts/dev/bench_ollama_vram.py --cases A,D`.
- **API schema change:** update/run `src/tests/contract/`.
- **DB schema change:** `alembic check`.

The incident-derived gotchas behind these surfaces — mass-scrape `0 processed`, OLX Flight/`__NEXT_DATA__` parsing & listing-type stamping, bare `docker compose up` / `API_KEY` 403, Celery beat `task_routes`, `max_price` `price_type` filtering (BIN-77), API-image rebuild after `src/api/` changes (BIN-79), `public_id` vs UUID resolution (BIN-82) — live in [`docs/harness-troubleshooting.md`](docs/harness-troubleshooting.md#domain-validation-hooks-scraper--ai--db--api). Read it when a symptom matches.

## Harness notes (Cursor → Claude translation)

This project's agent harness was originally written for Cursor (`.cursor/rules/`, `.cursor/skills/`). This file and `.claude/skills/` are the Claude-native equivalents, kept local/gitignored the same way (ADR 0002):

| Cursor construct | Claude equivalent |
|---|---|
| `.cursor/rules/*.mdc` (`alwaysApply: true`) | This file, `CLAUDE.md` (auto-loaded every session) |
| `.cursor/skills/<name>/SKILL.md` | `.claude/skills/<name>/SKILL.md` (same frontmatter/format, invoked the same way — by name or by description match) |
| `~/.cursor/rules/agent-hygiene.mdc` (global) | `~/.claude/CLAUDE.md` (global user memory) |
| Cursor Plan mode | Plan Mode |
| MCP tools `move_agent_to_root` / `SetActiveBranch` / `move_agent_to_cloned_root` (Cursor's worktree-agent orchestration) | No equivalent tool — `cd` to the target checkout path directly in the shell; the session's working directory persists across shell calls |
| `.agents/skills/bmad-*` (BMad Method) | Unchanged — framework-native skills, not tool-specific |

`.claude/skills/` stays local and gitignored, same as `.cursor/` was (per ADR 0002: shared/reviewable gates live in `scripts/agent/` and `.github/workflows/`, not in agent-tool config).
