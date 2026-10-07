---
project_name: 'imoveis'
user_name: 'Felipe'
date: '2026-10-07'
status: 'complete'
optimized_for_llm: true
derived_from: 'AGENTS.md (single source of truth for agent rules) + ADR 0007'
---

# Project Context for AI Agents

The rules an agent must follow in this repo live in **`AGENTS.md`** at the repo root (read natively by Claude Code, Codex, Cursor and Copilot). This file is the BMad-facing digest; when the two disagree, `AGENTS.md` wins and this file is regenerated from it.

## Stack

Python 3.11 FastAPI + Celery (Redis broker), SQLAlchemy 2 + GeoAlchemy2 + pgvector, PostgreSQL 17 + PostGIS 3.5 (in-repo image), Alembic, React 19 / Vite 8 / TypeScript strict, maplibre-gl 6, Playwright e2e, host Ollama (`qwen2.5vl:7b`, `bge-m3`) with optional LM Studio-compatible local server; Gemini/Gemma cloud assist is backfill-only. Deps pinned via pip-compile (`requirements.in` → `requirements.txt`; `requirements-windows.txt` on Windows) and `package-lock.json`.

## Enforced rules (hooks, see ADR 0007)

1. `git push` to `main` requires a validation stamp for HEAD's tree (`python scripts/agent/validate.py`, tier from the diff); force pushes are denied.
2. The primary compose project `imoveis` is operator-owned: no `docker compose` lifecycle commands against it, no `docker system prune` / `docker volume rm`. Tests use the ephemeral `<workspace>-test` stack. Primary migration = `bash scripts/agent/migrate-primary.sh` only (Redis lock + backfill heartbeat; never delete those keys).
3. `.env.local` and `configs/anchors.local.yaml` are never edited by agents; the gate reads `.env.local` through a workspace-identity allowlist (never `DATABASE_URL`, `GEMINI_API_KEY`, `IMOVEIS_*`).

## Working rules

- Validate with `python scripts/agent/validate.py` (never raw `pytest`/`npm test` as the verdict). Ship with `python scripts/agent/ship.py` (validate → squash-merge → push). `bmad-loop/<run>/<story>` branches are merged by the orchestrator: commit, validate, end the session.
- `src/core/` is framework-free and never imports `api`/`adapters`. Settings only via `AppConfig` / `configs/app_config.yaml` (`os.getenv` only in `config.py`). Never f-string SQL; never `eval`/`exec`/`os.system` on user data; no secrets in the repo.
- AI scores are floats in [0, 1]; keep `src/api/schemas.py` and `src/tests/contract/` in sync; `get_logger` kwargs must not use LogRecord reserved names. Property URLs use `public_id`.
- Celery beat tasks must be listed in `task_routes` (`scrapers` vs `ai`); GPU work only on `ai` under the GPU semaphore; `OLLAMA_NUM_PARALLEL` equals `gpu.semaphore_limit`. The committed routing map stays all-local (unit-pinned); cloud opt-in is per host via `IMOVEIS_AI__ENRICHMENT_ROUTING__*` in `.env.local`; one Redis pacer `backfill:gemma` owns the daily quota.
- Scrapers implement the `base.py` contract + registry; Cloudflare/proxy failures are availability `unknown`, never parse failures. Scraper changes trigger the cassette + live dry-run gate; AI prompt/client changes trigger the Ollama golden tests.
- Testing is risk-tiered: TDD in `src/core/`; oracle-first for scrapers; a characterization lock before changing brownfield SQL/dedupe/projection; one happy + one error path for thin glue. Every `fix:` ships a regression test.
- Tracking is BMad artifacts only (`epics.md` plan of record, `sprint-status.yaml` status with BMad-standard keys); feature doc per story at `docs/features/<story-key>-<slug>.md`; epic close only on a fresh re-read after the last push.
- Scope: stop and ask when a change needs more than 3 unexpected files; no out-of-scope refactoring.

Last Updated: 2026-10-07
