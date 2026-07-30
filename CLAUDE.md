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
| Database    | PostgreSQL 15 + PostGIS + pgvector | Geospatial + embedding storage |
| AI          | Ollama / LM Studio       | Local VLM + text models           |
| Frontend    | React 19 + Vite 8        | Score-coloured property grid      |
| Config      | Pydantic + YAML          | Single source of truth            |
| Migrations  | Alembic                  | Schema versioning                 |
| CI/CD       | GitHub Actions           | Tests, lint, build, security      |
| Tracking    | Linear (team **Bino**)   | Feature queue, project board      |

Full docs: `docs/setup.md` (install/run), `docs/architecture.md` (data flow/components), `docs/api.md` (endpoints), `docs/features/` (per-feature notes), `docs/adr/` (architecture decisions).

## Planning & implementation

**BMad Method** owns product planning/solutioning (PRD, architecture spine, epics, readiness, sprint-status). Artifacts: `_bmad-output/`. BMad skills: `.agents/skills/bmad-*` (framework-native, not Cursor- or Claude-specific — invoke by name, e.g. `bmad-help`, `bmad-prd`). Bridge: [`.claude/skills/imoveis-planning-bridge/SKILL.md`](.claude/skills/imoveis-planning-bridge/SKILL.md) + `docs/adr/0003-bmad-planning-bridge.md`. Run each major BMad workflow in a **fresh chat/session**.

**Linear + this pipeline** own execution. Sprint file: `_bmad-output/implementation-artifacts/sprint-status.yaml`. After `bmad-create-story` (optional), implement via feature-pipeline gates — never skip `validate.sh` / `finish-feature.sh`.

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
6. **Update Linear** to Done via the Linear MCP server **after the PR is merged**. (Requires a Linear MCP connector configured for Claude — add it via `claude mcp add` or the Cowork connector picker if not already connected.) Then run [epic-completion](.claude/skills/epic-completion/SKILL.md) §A→§B→§C on a **fresh** sibling list (do not trust a kickoff "not last" note — parallel agents race that). Mark the parent Done only when close-ready.
7. **Report**: branch, **merged** PR URL, features delivered, epic close verdict (remaining siblings / close-ready / Epic marked Done / N/A), follow-ups.

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

## Linear integration

Team **Bino**. Use the Linear MCP server's tools (project-level MCP config, or a connector if running under Cowork).

| Entity | ID |
|--------|---|
| Project (Imoveis — Deal Tracker) | `2b293958-ee46-48f1-98aa-6d54abba468d` |
| State: In Progress | `7de50ed1-0de6-4f06-89f6-6816991f106f` |
| State: Done | `fa058318-6dde-441e-91cb-5939c33e4fb1` |

### Milestone ordering

Milestones are **versioned only** (`v0.1`, `v0.2`, …). Prefer **one large multi-story epic per numbered milestone**; thin single-ticket waves also get their own `v0.N`.

#### Milestone description standard (match v0.1–v0.4)

When creating or editing a Linear project milestone, use **only**:

1. A short prose paragraph stating **what work this milestone contains** (no status banners, no "active/next/deferred", no links to other milestones, no process/policy essays).
2. `**Theme:**` one line.
3. `**Exit criteria:**` concrete, testable outcomes for *this* milestone's work.

Do **not** put epic/ticket relationship graphs, "1:1 with BIN-…", "after v0.N", or harness policy in the milestone body — those live on issues / this file.

1. List milestones for the project; ignore any `DEPRECATED` leftover.
2. Work earliest uncompleted versioned milestone (lowest `sortOrder` among `v0.*` with open issues).
3. Within it, highest-priority unfinished issue (lower number = higher priority).
4. Advance only when ALL current milestone issues are Done (optional Low tickets may be explicitly parked/canceled per epic exit criteria).

### Epic refine / multi-ticket planning (NON-NEGOTIABLE)

Whenever you **refine an epic** and/or **create multiple Linear child tickets**, the wrap-up reply to the user **must** include a **Parallel work plan** — not only a flat ticket list.

Required shape:

1. **Waves** — group stories into sequential waves (Wave 1, Wave 2, …). Within each wave, name every ticket that can run **in parallel**.
2. **Gates** — for each wave, state what must be Done before the next wave starts (audit findings, foundation PR, schema, etc.).
3. **Start here** — call out the concrete first parallel set (usually Wave 1) with Linear IDs/links.
4. **Do not parallelize** — briefly note stories that look independent but must stay serial (shared files, same migration, preference API before UI catalog, etc.).

Wire Linear `blockedBy` to match the plan when practical. Skipping this section after multi-ticket epic work is a harness miss.

### Epic completion (parent issues)

Every versioned milestone (`v0.N`) is delivered as one or more Linear parent epics with numbered children — check the current milestone's epic via `list_milestones`/`list_issues` rather than assuming a fixed ID range (past ranges: v0.5 was BIN-19..23, v0.6 was BIN-85/BIN-86..95, v0.9 was BIN-104 — all Done; do not treat any of these as current). On every feature-pipeline ticket **with a parent**:

1. **After story Done (mandatory):** re-detect last-ticket on a fresh sibling list ([epic-completion](.claude/skills/epic-completion/SKILL.md) §A). If `remaining == 0`, run checklist §B then close gate §C. Mark the **parent** Done in Linear and `epic-N: done` in `sprint-status.yaml` only when close-ready.
2. **Do not** rely on a start-of-feature "am I last?" check — concurrent agents often all see siblings still open at kickoff and would skip the close gate. Never leave a fully delivered epic stuck in Backlog; never mark Done while leftovers remain.

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
- New feature = `docs/features/BIN-<id>-<slug>.md` (Linear-ID-prefixed) + README link when user-facing.
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

Every completed feature: `docs/features/BIN-<id>-<feature-slug>.md` using `docs/features/_template.md` verbatim (all sections mandatory). **The filename prefix is the Linear issue ID** (`BIN-<id>`) — unique by construction, so parallel PRs never collide (this replaced the old `max(NN)+1` sequential numbering, which raced; see the BIN-146…BIN-147 v0.10 batch). Keep the `Linear: \`BIN-<id>\`` header field in sync with the filename.

- One doc per ticket. A follow-up/regression with no ticket of its own needs a **placeholder Linear issue** (create it, then name the doc after it) — do not reuse another ticket's ID or fall back to a number.
- Legacy numeric-prefixed docs (`docs/features/<NN>-*.md`) were migrated to `BIN-<id>-*` in bulk; if you touch one that somehow still has a numeric prefix, rename it to its Linear ID at the same time.

Bugs found during review go only in **Notes / Follow-ups** as `**BUG (Severity)**: description — fix hint.`

## Domain validation hooks

- After scraper change: `bash scripts/agent/validate-scrapers.sh --require-live` (merge-blocking). On HTML drift, refresh cassettes via `python scripts/dev/record_scraper_cassettes.py` — never drop the CI gate.
- After AI prompt/client change: `bash scripts/agent/validate-ai.sh` (from WSL set `OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434` when Ollama binds on Windows; keep host `OLLAMA_NUM_PARALLEL` equal to `gpu.semaphore_limit` — oversized parallel × `num_ctx` spills VRAM into system RAM). After concurrency/VRAM changes: `PYTHONPATH=src python scripts/dev/bench_ollama_vram.py --cases A,D`.
- API schema changes: update/run `src/tests/contract/`
- DB schema changes: `alembic check`
- Mass scrape `0 processed / N errors` with successful HTTP: check `AppConfig` still exposes every YAML section `tasks.scrape_listings` reads (e.g. `cfg.dedup`) and worker logs for `scrape_persist_error` / `AttributeError`. Rebuild `worker_scraper` after config/scraper fixes.
- OLX `olx_no_listing_payload` / missing `__NEXT_DATA__`: parse Flight (`__next_f.push`) ads; intermittent Cloudflare 403 is environmental (proxy pool), not a parse regression.
- OLX detail URLs often omit `/venda|/aluguel` — stamp `_olx_listing_type` from the search window and prefer path segments (not substring `venda`, which matches `venda-nova`). `locationDetails` is often the **seller/region**, not the property: run `core.olx_location` reconcile before geo allowlist; backfill with `scripts/dev/fix_olx_listings.py`.
- Never recreate the API with bare `docker compose up` — always `compose_cmd` / `./scripts/start.sh` / `--env-file .env.local`. Empty `API_KEY` makes SPA admin calls (`/admin/schedule`, recalculate, …) return **403 Admin API key not configured**.
- Celery beat tasks must be in `task_routes` for a queue workers consume (`scrapers` or `ai`). Unrouted tasks land on default `celery` and never run (BIN-76: empty Dashboard `/system/pipeline/history`). After adding a beat entry, assert the route in `test_schedule.py` and rebuild `beat` + the consuming worker.
- Properties `max_price` must filter `property_listings` by `price_type` (`rent`|`sale`), not decisioning `p.price` (lowest listing, rent-preferred) — otherwise sale budgets match dual-listed homes on cheap rent (BIN-77). Hide number steppers on typed amount inputs (`type="text"` + `inputMode="numeric"`; CSS alone is not enough — BIN-79).
- API image does **not** bind-mount `src/` — after `src/api/` filter/route changes, `docker compose --env-file .env.local build api && docker compose --env-file .env.local up -d api` before trusting local UI against Docker (BIN-79 stale-image miss).
- Deep links use sequential `public_id` in URLs; UUID remains the PK. Any endpoint that stores `property_id` (favourites, watchlist, …) must resolve via `api.property_refs.resolve_property_uuid` — digit-only refs are `public_id`, not UUID (BIN-82 / #85 UUID cast 500).

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
