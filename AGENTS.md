# Imoveis — agent instructions

Local-first Brazilian real-estate decision engine (Belo Horizonte): scrapers → dedupe → price history → local AI enrichment → score-coloured React UI, with an AI agent (Claude Code) as the primary query client. Python 3.11 **FastAPI** + **Celery**, **PostgreSQL 17 + PostGIS + pgvector**, **Redis**, **React 19 / Vite 8**, host **Ollama**. Full docs: `docs/setup.md`, `docs/architecture.md`, `docs/api.md`, `docs/features/`, `docs/adr/`. Invariants: `_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md` (AD-1..19).

## Layout

- `src/api/` FastAPI (`api.main:app`) · `src/core/` pure domain (never imports `adapters`/`api`) · `src/adapters/` scrapers, db, ai, geo, queue, notify, metrics · `src/infra/` config, db session, redis, logging · `src/tests/` pytest (`unit` / `integration` / `contract`; markers `slow`, `harness`) · `frontend/` React + Playwright e2e · `configs/app_config.yaml` the only settings source (`AppConfig`; `os.getenv` only inside `config.py`) · `alembic/` migrations · `scripts/agent/` the gate (`validate.py`, `ship.py`, `migrate-primary.sh`) · `scripts/ops/` operator tasks · `scripts/dev/` one-off data scripts.
- Planning and tracking are BMad artifacts only: `_bmad-output/planning-artifacts/epics.md` (plan of record) and `_bmad-output/implementation-artifacts/sprint-status.yaml` (status; keys `epic-N`, `N-M-slug`; story ids `v0.N-sE.S`, follow-ups `v0.N-fu<N>` under `followups:`). Statuses only move forward; `done` only after the merge is pushed.

## Three enforced rules (hooks in `.claude/hooks/`, not prose)

1. **Push to `main` needs a validation stamp.** `guard.py` denies `git push` to main unless HEAD's tree carries `.run/validated/<tree-sha>.<tier>` for the tier the diff requires; force pushes are always denied.
2. **The primary Docker project `imoveis` is operator-owned.** `docker compose` lifecycle commands against it, `docker system prune`, `docker volume rm` are denied. Validation uses the ephemeral `<workspace>-test` stack only. Primary DB migration is the operator step `bash scripts/agent/migrate-primary.sh` (Redis lock + backfill heartbeat guard; never delete those keys).
3. **`.env.local` and `configs/anchors.local.yaml` are the operator's.** Never edited by agents; the gate reads `.env.local` through an allowlist (workspace identity only — never `DATABASE_URL`, `GEMINI_API_KEY`, `IMOVEIS_*`).

## Working a change

```bash
git switch -c feat/<slug>            # story work: feat/v0.14-s1.2-<slug> (drives the feature-doc check)
python scripts/agent/validate.py     # tier from the diff: docs | fast | frontend | backend | full (+scrapers/ai/harness when those paths change)
python scripts/agent/ship.py         # validate → squash-merge into main → push (hook re-checks the stamp)
```

- Windows: use `.venv/Scripts/python.exe`; no Git Bash needed for the gate. Stop a running Vite dev server before the frontend/full tier (`npm ci` cannot replace a locked native module).
- Never run raw `pytest` / `npm test` to *validate*; `validate.py` sets the isolated env. Running a single test file while developing is fine.
- Measured on the Windows host (2026-10-07): docs ≈ 11 s · fast ≈ 75 s (lint 17 + unit 55, xdist) · backend ≈ fast + ~60 s · frontend ≈ fast + ~40 s · harness-marked script tests ≈ 14 min serial (only when `scripts/`, `.claude/` or the gate tests change, or in the full tier).
- A `Stop` hook pushes `main` when it is clean, ahead of origin and stamped, so origin never lags.
- `bmad-loop/<run>/<story>` branches are merged by the orchestrator (`.bmad-loop/policy.toml` runs the backend tier as `[verify]`); never `ship` them — commit, validate, end the session.
- Domain gates run automatically by path: scrapers (`src/adapters/scrapers/`) → cassette suite + live dry-run (refresh cassettes with `python scripts/dev/record_scraper_cassettes.py` on HTML drift; a 403/Cloudflare block is availability `unknown`, not a parse failure); AI prompts/clients → Ollama golden tests (skipped loudly when Ollama is down); `alembic/` → alembic check (PostGIS system tables are expected drift). API schema changes keep `src/api/schemas.py` and `src/tests/contract/` in sync.

## Conventions

- Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`). Every `fix:` ships a regression test that fails without it. Squash-merged, linear `main`.
- Feature doc per story: `docs/features/<story-key>-<slug>.md` from `docs/features/_template.md` (all sections); legacy `BIN-*` docs keep their names. Review-found bugs go under Notes / Follow-ups as `**BUG (Severity)**: … — fix hint.`
- Testing is risk-tiered: TDD for `src/core/` and scoring/classifier math; oracle-first (live probe → cassette) for scrapers; a characterization lock before changing brownfield SQL/dedupe/projection; one happy + one error path for thin glue. No coverage theater.
- AI scores are floats in [0, 1]; `response_model` types match domain producers. `get_logger` kwargs become LogRecord extras — never pass reserved keys (`name`, `msg`, `args`, `level`). Never f-string SQL; never `eval`/`exec`/`os.system` on user data; no secrets in the repo (`imoveis_secret`, `dev-secret-key` are forbidden strings).
- Celery: every beat task is listed in `task_routes` (`scrapers` vs `ai` queues); GPU work only on `ai` through the GPU semaphore; keep host `OLLAMA_NUM_PARALLEL` equal to `gpu.semaphore_limit`. Cloud AI (Gemini/Gemma free tier) is backfill-only under the single Redis pacer `backfill:gemma`; the committed routing map stays all-local (unit-pinned) — opt a host in via `IMOVEIS_AI__ENRICHMENT_ROUTING__*` in `.env.local`.
- Scope: stay inside the story; if a change needs more than 3 unexpected files, stop and ask. Don't optimize what isn't measured.
- Incident-derived gotchas (mass-scrape `0 processed`, OLX Flight parsing, bare `docker compose up` breaking `API_KEY`, `max_price` filtering, `public_id` vs UUID, API-image rebuild after `src/api/` changes) live in `docs/harness-troubleshooting.md` — read it when a symptom matches.

## BMad

Planning: `bmad-prd`, `bmad-architecture`, `bmad-create-epics-and-stories`, `bmad-sprint-planning` (each in a fresh session). Implementation: `bmad-build` (interactive) / `bmad-build-auto` under bmad-loop; `bmad-code-review` for review. Project bindings live in `_bmad/custom/*.toml` and say exactly the three rules above. Epic close: re-read sprint-status.yaml + epics.md fresh after the last story's push; mint leftovers as tracked keys before closing. After multi-story planning, the wrap-up must include a Parallel work plan (waves, gates, start-here set, do-not-parallelize list) and the gates go into epics.md.
