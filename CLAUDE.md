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
| Gates       | `scripts/agent/` (local) | validate.sh is THE merge gate; GitHub Actions = docs deploy + nightly scraper drift canary only |
| Tracking    | BMad artifacts (`_bmad-output/`) | epics.md = plan of record; sprint-status.yaml = execution status (ADR 0005) |

Full docs: `docs/setup.md` (install/run), `docs/architecture.md` (data flow/components), `docs/api.md` (endpoints), `docs/features/` (per-feature notes), `docs/adr/` (architecture decisions).

## Planning & implementation

**BMad Method** owns both planning AND execution (ADR 0005 + v0.13-fu1 harness surgery). Artifacts: `_bmad-output/`. BMad skills: `.agents/skills/bmad-*` (framework-native — invoke by name, e.g. `bmad-help`, `bmad-prd`). Run each major BMad planning workflow (PRD, architecture, epics, sprint planning) in a **fresh chat/session**.

**Ticket → ship is the BMad story cycle constrained to the `scripts/agent` gates:**

- Epic stories: `bmad-create-story` → `bmad-dev-story` → `bmad-code-review` (or the bmad-loop orchestrator driving the same cycle).
- Freeform/small work: `bmad-quick-dev`.
- Project overrides in `_bmad/custom/` bind all dev skills to the gates: validation is **only** `validate.sh`, shipping is **only** `finish-feature.sh`, and the primary docker stack is untouchable. BMad skills call the gates — they never reimplement, replace, or skip them (ADR 0002).

Use **Plan Mode** for non-trivial work, then implement in the same session. An optional `implementation_plan.md` is fine for long tasks.

## Repository map

- `src/api/` — FastAPI app (`api.main:app`, `/health`).
- `src/adapters/` — scrapers, queue (Celery), AI clients, metrics.
- `src/core/` — business logic (dedup, entities, exceptions).
- `src/infra/` — config loading, DB session, Redis, logging.
- `src/tests/` — pytest suite (markers: unit/integration/e2e/slow).
- `frontend/` — React 19 + Vite 8.
- `configs/app_config.yaml` — single source of truth for all settings.
- `alembic/` — DB migrations.
- `scripts/agent/` — agent workflow tooling (branch setup, validation, finishing) — shared/committed, tool-agnostic. **This is the enforcement layer.**
- `deploy/systemd/` — host-side systemd unit templates (cloud backfill supervisor); installed by `scripts/install-backfill-runner.sh`, never a compose service (ADR 0006). Cloud backfill is enabled **per host** via `IMOVEIS_AI__ENRICHMENT_ROUTING__{VISUAL,SENTIMENT,DEAL_VERDICT}=gemma` in the git-ignored `.env.local` — **all three classes on the same cloud backend** (`--serve` drives one client and has no local mode: a partial or `gemma`+`gemini` split scope makes it refuse at startup and the unit restart forever) — never by editing the committed `configs/app_config.yaml`, which must stay all-local (NFR-1) and is pinned by a unit test.
- `docs/` — MkDocs Material site. `docs/features/` for feature implementation notes.
- `.agents/skills/` — committed BMad Method skills (framework-native, shared across tools).
- `_bmad/custom/` — committed per-skill BMad overrides (gate bindings).

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
git fetch origin main --quiet
pip install -r requirements.txt
(cd frontend && npm install)
```

(Feature branches are local-only now. On `main`, update with `git pull --ff-only origin main`. Do **not** auto-merge `origin/main` into a resumed feature branch — if you choose to sync one, run the merge deliberately and resolve conflicts before touching anything else; the finish gate re-checks against `main` anyway.)

### End of every task (MANDATORY)

1. **Commit** remaining changes with conventional messages.
2. **Validate**: `bash scripts/agent/validate.sh all`
3. **Finish**: `bash scripts/agent/finish-feature.sh`
   - This validates, **squash-merges locally into `main`**, and **pushes `main` to origin immediately** (origin is the backup of record, not a gate). A red validation blocks the merge — fix and re-run. Validated ≠ finished; **merged-and-pushed is finished.**
   - Run it backgrounded or with a high timeout — full validation takes minutes.
   - Worktree: the script tears the worktree down (`teardown.sh --remove`); afterwards `cd` back into the primary checkout path (find it with `git worktree list`).
   - Primary: the script leaves the checkout on `main`.
   - Cleanup is automatic: ephemeral test stack down + `docker-cleanup.sh` (stopped containers, dangling/unused feat|wt images, build cache; keeps primary `imoveis-*` + base images; never volumes).
4. **Docker temps (required)** — if wrap-up did not go through `finish-feature.sh` / `teardown.sh`, run `bash scripts/agent/docker-cleanup.sh` yourself before closing the session.
5. **Update sprint-status.yaml** — set the story key to `done` **after the merge is pushed** (never downgrade; prefer committing it on the feature branch before merge when possible). Then run the epic-completion check (below) on a **fresh** re-read of sprint-status.yaml + epics.md.
6. **Report**: branch, merged commit on `main` (pushed), features delivered, epic close verdict (remaining sibling story keys / close-ready / epic-N done / N/A), follow-ups.

## Validation & finishing

NEVER run raw `pytest` or `npm test`. ALWAYS use:

```bash
bash scripts/agent/validate.sh fast      # lint (pre-commit, all files) + unit
bash scripts/agent/validate.sh backend   # fast + integration + contract
bash scripts/agent/validate.sh all      # full gate (before merge)
```

NEVER merge manually. ALWAYS use:

```bash
bash scripts/agent/finish-feature.sh
```

**Exception — bmad-loop branches:** `bmad-loop/<run>/<story>` worktree branches are merged by the bmad-loop **orchestrator** after its review pass; `finish-feature.sh` refuses them by design (two merge machineries must never race on one branch). In a bmad-loop session, finishing = commit + `validate.sh all` green + end the session. Never merge such a branch by hand and never add `bmad-loop` to `VALID_BRANCH_TYPES`.

`all` ends with an **advisory** dependency audit (`scripts/agent/audit-deps.sh`: `pip-audit` + `npm audit`) — it never affects the verdict, missing tools/offline degrade to a visible `[WARN]` skip, and a real finding is resolved by a deliberate dependency bump, never by muting the tool.

If validation fails: diagnose → fix → re-run. Missing tools (`pre-commit`, `isort`, `flake8`, `pytest`): `pip install`.

The lint stage's pre-commit fixer hooks (whitespace, end-of-file, isort) **modify files** when they fail — that's the fix. Commit the hook's edits and re-run; never `git checkout --` them away and never reach for `--skip-validate` (which is docs-only-branches only — there is no zero-gate path to `main`).

### Primary stack is inviolable

- `validate.sh` and `finish-feature.sh` **never touch the primary compose project `imoveis`** — no container create/recreate/restart/stop, no `realestate` schema or data changes. Safe to run at any time, **including during a live backfill**.
- Test DB/Redis come from the **ephemeral test stack**: `bash scripts/agent/test-stack.sh [up|env|down|status]` — compose project `<workspace>-test`, docker-assigned ports (never hardcoded), throwaway volumes, image parity with primary.
- `validate.sh` / `finish-feature.sh` read `.env.local` through a **default-deny allowlist** (`scripts/agent/lib.sh::load_workspace_env`), never `set -a; source`: it is also the backfill runner's `EnvironmentFile=`, so nothing else **in that file** — the cloud key, the primary `DATABASE_URL`, any `IMOVEIS_*` config override — reaches pytest (DW-33). It filters the file, not your shell: an `IMOVEIS_*` you exported yourself still arrives, which is why `src/tests/conftest.py` strips that channel suite-wide regardless of origin.
- Migrating the **primary** `realestate` DB is an explicit operator step: `bash scripts/agent/migrate-primary.sh`. It takes `backfill:gemma:migrating` (held for the whole upgrade, released on exit) *before* refusing on the backfill runner's live heartbeat `backfill:gemma:active` — set-then-check on both sides, so a runner and a migration can never both proceed. Both keys self-clear on their TTLs — never delete either manually.
- `teardown.sh` fails closed: it refuses when the compose project identity is ambiguous (no `COMPOSE_PROJECT_NAME` in `.env.local`) or resolves to the primary project (operator override: `--primary`; primary volumes are never wiped).
- Never run any `docker compose` command against the primary project yourself. A stuck primary stack is the operator's call, not the agent's.

Config tests must clear `get_config()`'s `lru_cache` via `autouse` fixture when `DATABASE_URL`/`REDIS_URL` are set by the environment.

**API response schemas:** keep Pydantic `response_model` types aligned with domain producers (AI scores are floats in `[0.0, 1.0]`, not ints). Contract tests must **not** treat every 500 as "DB down" when the properties schema is queryable — that hid BIN-56 `ResponseValidationError`. Prefer failing when the table exists; skip only when schema/infra is missing. Unit tests that hit rate-limited routes must bypass slowapi Redis (unit runs have none).

## Tracking (BMad artifacts — ADR 0005)

**No external tracker.** Plan of record: `_bmad-output/planning-artifacts/epics.md`. Execution status: `_bmad-output/implementation-artifacts/sprint-status.yaml`. Story keys are `v<milestone>-s<epic>.<story>` (e.g. `v0.13-s1.1`); follow-ups without a story mint `v<milestone>-fu<N>` keys in sprint-status.yaml. Pre-v0.13 `BIN-*` ids in old docs are historical names only.

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

### Epic completion (inline discipline)

On every run that finishes a story **belonging to an epic**:

1. **After story `done` (mandatory):** re-read sprint-status.yaml + epics.md **fresh** — never trust a kickoff-time "am I last?" note; parallel agents race that signal.
2. If no unfinished sibling story keys remain, check for untracked leftovers before closing: open `action_items`, follow-up notes in the epic's feature docs, deferred ACs noted in epics.md.
3. Set `epic-N: done` only when every sibling is finished (done/canceled/explicitly deferred) **and** no leftovers remain. Never leave a fully delivered epic un-closed; never close one with leftovers.

## Commit & safety

- Conventional: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
- NEVER `git push --force`. NEVER delete another developer's branch.
- `main` advances **only** via `finish-feature.sh` local squash-merge; every merge is pushed to origin immediately.
- NEVER `docker system prune` / `docker volume rm` / `docker compose down -v` on the primary stack without user approval (see BIN-60 / feature 45).
- ALWAYS prune temps after wrap-up via `bash scripts/agent/docker-cleanup.sh` (or finish/teardown, which call it). Removes stopped containers, dangling images, unused feature/worktree tagged images, and build cache. Keeps primary `imoveis-*` (not `imoveis-wt-*`), third-party bases, and images for still-running Compose projects. Never touches named volumes / never `docker system prune --volumes`.
- NEVER hardcode passwords, API keys, or tokens. Defaults `""` or env vars.
- Forbidden in committed files: `imoveis_secret`, `dev-secret-key`.
- NEVER `eval()`/`exec()`/`os.system()` with user input; NEVER f-string SQL — parameterize.
- Secret scan before commit: `git grep -nP '(password|secret|api_key).*=.*["'"'"'][a-zA-Z0-9]' src/ frontend/src/`

## Scoping

- NEVER refactor outside feature scope. If touching >3 unexpected files, STOP and ask.
- Do not optimize code that isn't causing a measurable problem.
- After finishing a nontrivial task, fold durable lessons (repeated corrections, rediscovered commands, missing gates) into this file or the relevant BMad override — skip one-off trivia.

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

- Do **not** chase 100% line coverage on adapters/wiring; meaningful coverage comes from domain + classifier branches.
- Multi-branch parsers: split helpers early (load → signal → fallback) — deep nesting is a maintenance smell.
- External 403/proxy failures are `unknown`, not product regressions — never treat Cloudflare blocks as parse failures.
- `get_logger` kwargs become LogRecord extras — never pass reserved keys (`name`, `msg`, `args`, `level`, …) or integration tests blow up with `KeyError: Attempt to overwrite 'name' in LogRecord` (BIN-87: use `neighbourhood_name`).
- Idempotent loaders (YAML/GeoJSON apply): unit-test update/skip/unknown with a mocked session so coverage does not depend only on integration.

## Feature documentation (NON-NEGOTIABLE)

Every completed feature: `docs/features/<story-key>-<feature-slug>.md` using `docs/features/_template.md` verbatim (all sections mandatory). **The filename prefix is the BMad story key** (`v0.13-s1.1`, from epics.md / sprint-status.yaml) — unique by construction, so parallel branches never collide. Keep the `Story: \`<story-key>\`` header field in sync with the filename. Include the key in the branch name (`feat/v0.13-s1.1-…`) so `gen-docs.sh` and the finish gate derive it — `finish-feature.sh` refuses to merge a story-key branch without its feature doc.

- One doc per story. A follow-up/regression with no story of its own mints a **`v0.N-fu<N>` key in sprint-status.yaml** (one line, status + short description) and names the doc after it — do not reuse another story's key or fall back to a bare number.
- Legacy `BIN-<id>-*` and numeric-prefixed docs are history — keep their names; do not rename them to story keys.

Bugs found during review go only in **Notes / Follow-ups** as `**BUG (Severity)**: description — fix hint.`

## Domain validation hooks

After a change to one of these surfaces, run its gate before calling the work done:

- **Scraper change:** `bash scripts/agent/validate-scrapers.sh --require-live` (merge-blocking). On HTML drift, refresh cassettes via `python scripts/dev/record_scraper_cassettes.py` — never drop the gate. The nightly GitHub drift canary watches the live portals between sessions.
- **AI prompt/client change:** `bash scripts/agent/validate-ai.sh` (from WSL set `OLLAMA_HOST=http://$(ip route show default | awk '/default/{print $3}'):11434` when Ollama binds on Windows; keep host `OLLAMA_NUM_PARALLEL` equal to `gpu.semaphore_limit` — oversized parallel × `num_ctx` spills VRAM into system RAM). After concurrency/VRAM changes: `PYTHONPATH=src python scripts/dev/bench_ollama_vram.py --cases A,D`.
- **API schema change:** update/run `src/tests/contract/`.
- **DB schema change:** `alembic check` (runs against the ephemeral test DB inside `validate.sh backend`); primary migration only via `migrate-primary.sh`.

The incident-derived gotchas behind these surfaces — mass-scrape `0 processed`, OLX Flight/`__NEXT_DATA__` parsing & listing-type stamping, bare `docker compose up` / `API_KEY` 403, Celery beat `task_routes`, `max_price` `price_type` filtering (BIN-77), API-image rebuild after `src/api/` changes (BIN-79), `public_id` vs UUID resolution (BIN-82) — live in [`docs/harness-troubleshooting.md`](docs/harness-troubleshooting.md). Read it when a symptom matches.

## Harness notes

The agent harness is **BMad skills (committed, `.agents/skills/`) + `_bmad/custom/` gate bindings + `scripts/agent/` + this file**. Cursor and Claude share all of it; the only tool-specific surfaces left are thin mirrors — `.cursor/rules/imoveis-core.mdc` for Cursor. **Keep the mirror in sync when editing either** (silent drift between the two is a known failure mode).

- No worktree-orchestration MCP tools here — `cd` to the target checkout path directly; the session's working directory persists across shell calls.
- `.claude/skills/` holds only framework skills (BMad, WDS); project workflow discipline lives in this file, the `_bmad/custom/` overrides, and the `scripts/agent/` gates — not in per-tool skills.
