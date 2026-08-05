---
project_name: 'imoveis'
user_name: 'Felipe'
date: '2026-08-05'
sections_completed:
  ['technology_stack', 'language_rules', 'framework_rules', 'architecture_topology_rules', 'testing_rules', 'quality_rules', 'workflow_rules', 'anti_patterns']
status: 'complete'
rule_count: 52
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- **Backend:** Python 3.11, FastAPI + uvicorn, SQLAlchemy ≥2.0.51 + GeoAlchemy2 + pgvector, Celery 5.6 (Redis broker), Alembic (24 migrations), python-jose (JWT), slowapi
- **Database:** PostgreSQL 17 + PostGIS 3.5 + pgvector (in-repo Docker image); DBs `realestate` / `realestate_test`
- **AI:** multi-backend (`ai.backend: ollama | lmstudio | gemini | gemma` in `configs/app_config.yaml`) — local Ollama / LM Studio (host-side, GPU) + cloud Gemma via the Gemini API's OpenAI-compatible endpoint; ONNX runtime; 1024-dim embeddings
- **Scraping:** aiohttp + httpx + BeautifulSoup4, FlareSolverr v3.3.21, rapidfuzz + jellyfish
- **Frontend:** React 19.2, Vite 8, TypeScript (strict, flat eslint + typescript-eslint), react-router-dom 7, maplibre-gl 6 (named imports only), recharts 3, lucide-react 1.27, Playwright e2e
- **Pinning:** backend via pip-compile (`requirements.in` → `requirements.txt`); frontend `package-lock.json`. Major dep bumps (eslint 10, maplibre 6, PostGIS 17) need code changes, not just version edits.

## Critical Implementation Rules

### Language-Specific Rules (Python)

- All settings come from `AppConfig` (`src/infra/config.py`, Pydantic + YAML). `os.getenv()` is allowed **only** inside `config.py`. Never hardcode ports/URLs.
- `src/core/` is framework-free domain logic and must never import from `src/api/` (layering, BIN-134).
- Never build SQL with f-strings/concatenation — parameterize (BIN-135 eliminated these).
- Never `eval()`/`exec()`/`os.system()` on user-influenced data.
- `get_logger` kwargs become LogRecord extras — never pass reserved keys (`name`, `msg`, `args`, `level`, …); use prefixed names like `neighbourhood_name` (BIN-87).
- AI scores are **floats in [0.0, 1.0]**, never ints — Pydantic `response_model` types must match domain producers (BIN-56/BIN-148).
- Multi-branch parsers: split helpers early (load → signal → fallback) — deep nesting is a maintenance smell.

### Framework-Specific Rules

- **FastAPI:** contract surface is `src/api/schemas.py` + `src/tests/contract/`; keep them in sync with any schema change. 500s must not leak exceptions (BIN-132). Admin/system routes are auth-gated and audited (`admin_audit`). Property URLs use `public_id`, not UUID (BIN-82).
- **Celery:** explicit `task_routes` split scraper vs AI queues — beat tasks must be routed or they silently die. Scheduler state lives in Redis (`redis_scheduler.py`). GPU work goes through `gpu_semaphore`; keep host `OLLAMA_NUM_PARALLEL` equal to `gpu.semaphore_limit` or VRAM spills into system RAM.
- **Scrapers:** implement the `base.py` contract + registry; checkpoints in `platform_checkpoints`; Cloudflare 403/proxy failures are availability `unknown`, **never** parse failures or product regressions. OLX uses Flight/`__NEXT_DATA__` parsing with listing-type stamping.
- **React:** state lives in hooks (`usePropertiesFiltersState`, etc.); components stay presentational. i18n is pt-BR/en with locale-aware money/date formatters; AI tags/verdicts are localized server-side. Prefer primary listing for dual rent/sale properties (`utils/primaryListing.ts`).

### Architecture & Topology Rules (2026-08 technical research)

- **Local stack is the system of record** — GPU, residential scraping IP, and unmetered storage live here; cloud may only ever hold a slim, disposable, regenerable read-model projection. Never lift-and-shift the scraper, the full DB, or Celery+Redis to cloud free tiers (see `_bmad-output/planning-artifacts/research/technical-imoveis-local-vs-cloud-hybrid-stack-research-2026-08-05.md`).
- **Scrapers must egress from the residential IP** — datacenter/cloud ASNs are wholesale-flagged by 2026 anti-bot systems; never move scraping off-box.
- **Ollama is a permanent enrichment fallback backend** — never make enrichment cloud-quota-only; do not delete or bypass the local AI path.
- **Redis is multi-surface, not just Celery's broker** — it also backs slowapi rate limiting, the `ui:locale` runtime override, and `backfill:gemma` pacing state. Swapping or removing Redis is a multi-surface refactor, never a simple broker change.

### Testing Rules

- NEVER raw `pytest`/`npm test` — always `bash scripts/agent/validate.sh {fast|backend|all}` (wrappers encode env setup, DB provisioning, migrations).
- Risk-tiered: TDD on `src/core/`; oracle-first (live probe → cassette fixture) for scrapers; a characterization lock before changing brownfield SQL/dedupe/projection; one happy + one error path for thin glue — no coverage theater.
- Every `fix:` ships with a regression test that fails without the fix.
- Validation never uses the API image or the primary stack — no rebuild is needed before `validate.sh backend`; alembic and pytest run host-side against the ephemeral test stack. Rebuild `api` (`docker compose --env-file .env.local build api`) only to **run the app** after `src/api/` changes (BIN-79).
- Config tests must clear `get_config()`'s `lru_cache` (autouse fixture) when `DATABASE_URL`/`REDIS_URL` are set; `validate.sh backend`/`all` override stale host DB/Redis env from the test stack automatically.
- Unit tests hitting rate-limited routes must bypass slowapi Redis (unit runs have none).
- Meaningful coverage comes from domain/classifier branches, not adapter padding — no coverage theater.

### Code Quality & Style Rules

- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`).
- CI lint = pre-commit on ALL files (stricter than local `validate.sh`, which only flake8's `src/` — F401 is not ignored in CI).
- Feature docs: `docs/features/<story-key>-<slug>.md` (e.g. `v0.13-s1.1-…`) from `_template.md`, all sections mandatory; filename prefix is the story key from epics.md/sprint-status.yaml; keep the `Story:` header in sync (legacy `BIN-*` docs keep their names). Review-found bugs go in Notes/Follow-ups as `**BUG (Severity)**: … — fix hint.`
- Forbidden strings in committed files: `imoveis_secret`, `dev-secret-key`. Secrets default to `""` or env vars.
- Tables designed with nullable `owner` (single-user for now).

### Development Workflow Rules

- First action every session: `git rev-parse --abbrev-ref HEAD`. On `main`: `bash scripts/agent/setup-branch.sh "<slug>"` before any edit. Never a `claude/`-prefixed branch name.
- Finish = `bash scripts/agent/finish-feature.sh` (validate → **local** squash-merge to `main` → mandatory `git push origin main` → cleanup; run with a long timeout — it takes minutes). There is no PR step and no remote CI gate; a red `validate.sh all` blocks the merge. Validated ≠ finished; merged-and-pushed is finished. Never merge manually.
- Domain gates after touching: scrapers → `validate-scrapers.sh --require-live`; AI prompts/clients → `validate-ai.sh` (WSL: `OLLAMA_HOST` via default route); API schema → contract tests; DB schema → `alembic check`.
- Tracking is **BMad artifacts only** (ADR 0005, 2026-08-05 — Linear dropped): `epics.md` = plan of record, `sprint-status.yaml` = execution status (`in-progress` at start, `done` only **after** merge, never downgrade); story keys `v0.N-sE.S` replace `BIN-<id>` in feature-doc names and branches; epic close only on a fresh re-check of all sibling story keys + non-ticketed leftovers.
- Scope: stop and ask if touching >3 unexpected files; no out-of-scope refactoring.

### Critical Don't-Miss Rules

- Never `docker system prune`, `docker volume rm`, or `compose down -v` on the primary stack; cleanup only via `scripts/agent/docker-cleanup.sh` (keeps `imoveis-*` images and all named volumes).
- `validate.sh`/`finish-feature.sh` **never touch the primary stack** — DB/Redis come from the ephemeral `<workspace>-test` compose project (`test-stack.sh`; docker-assigned ports, throwaway volumes), so validation is safe at any time, **including during a live backfill**. Primary `realestate` migration is exclusively the operator step `bash scripts/agent/migrate-primary.sh` (refuses while the backfill heartbeat `backfill:gemma:active` is alive; the key self-clears — never delete it manually). `teardown.sh` fails closed on ambiguous/primary identity. Restore primary port drift with `docker compose --env-file .env.local`.
- Bare `docker compose up` (without `--env-file .env.local`) drifts ports and breaks `API_KEY` auth (403s).
- Worktree checkouts (`.claude/worktrees/`) have no `.venv`/`.env.local` — run `setup-worktree.sh` before validating there.
- Mass-scrape returning `0 processed`, beat tasks not firing, `max_price` filtering: check `docs/harness-troubleshooting.md` before "fixing" — these have known incident-derived causes (BIN-77, BIN-79, task_routes, …).
- Gemini API key is **free tier**: Gemma ≈ 30 RPM / **14,400 RPD** / 16K TPM (best-case — `ResourceExhausted` can fire early); Gemini Flash free RPD is an order of magnitude smaller (2.5 Flash ≈ 20 RPD). At 3 requests/property that's ~4,600 properties/day — don't plan single-day whole-DB cloud backfills. Exactly **one pacer** (Redis `backfill:gemma`, BIN-248 runner) owns the daily budget — never add a second consumer of the quota.
- BMad dev-side skills (`bmad-dev-story`, `bmad-quick-dev`, `bmad-dev-auto`) **are the sanctioned executors** for ticket → ship, bound by `_bmad/custom/` overrides to the `scripts/agent` gates: validation only via `validate.sh`, shipping only via `finish-feature.sh`, never any compose action against the primary project, never raw `pytest`/`npm test`.

---

## Usage Guidelines

**For AI Agents:**

- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**

- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review quarterly for outdated rules
- Remove rules that become obvious over time

Last Updated: 2026-08-05
