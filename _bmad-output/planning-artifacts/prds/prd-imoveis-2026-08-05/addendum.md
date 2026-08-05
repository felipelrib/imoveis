# Addendum — Imoveis Deal Tracker PRD (2026-08-05)

Technical and planning depth that belongs downstream (architecture, epics) or supports the PRD without bloating it. Supersedes the 2026-07-23 addendum; unchanged entries carried forward.

## Mechanism decisions (for architecture)

- Stack (current, post-v0.12): FastAPI, Celery + Redis, PostgreSQL 17 + PostGIS 3.5 + pgvector (in-repo image, BIN-272), React 19 / Vite 8 / TypeScript strict, maplibre-gl 6, host Ollama / LM Studio, FlareSolverr in Compose, full pip-compile lockfile (BIN-138).
- AI backends: `ai.backend: ollama | lmstudio | gemini | gemma` already exists in `configs/app_config.yaml` — FR-27 productizes routing semantics on top of it, not a new config surface.
- Backfill runner: `core/backfill_runner.py` + `scripts/dev` CLI (BIN-248) writes through the single enrichment pipeline authority — architecture pass should name it a sanctioned second *driver* (AD-4/AD-10 note), plus AD-13 (or AD-7 amendment) bounding the cloud-assist path.
- Redis is multi-surface: Celery broker, slowapi rate limiting, `ui:locale` override, `backfill:gemma` pacer. Any Redis change is a multi-surface refactor.
- Scraper plugin registry; queues `scrapers` vs `ai` (GPU semaphore; host `OLLAMA_NUM_PARALLEL` = `gpu.semaphore_limit`).
- Dedup defaults: 50 m geo, ±2 m² area, Jaro–Winkler ≥ 0.65 (config-driven).
- Implementation gates: `scripts/agent/validate.sh` / CI stay merge-blocking across the SoR pivot; bmad-loop wraps them via `bmad-customize`, never replaces them.

## Cloud-assist sizing data (for FR-28/FR-29 planning)

- Gemini API key is **free tier**. Gemma: ~30 RPM / **14,400 RPD** / 16K TPM best-case; `ResourceExhausted` can fire early. Gemini Flash free RPD is an order of magnitude smaller (~20 RPD for 2.5 Flash) — Gemma is the backfill workhorse.
- At ~3 requests/property ⇒ ≈4,600 properties/day ⇒ whole-DB backfill is inherently **multi-day (~6 days observed planning basis)**. Single-day whole-DB requires paid tier or local-only — out of scope (§5).
- Exactly one pacer (`backfill:gemma`) owns the daily budget. "Never add a second quota consumer" is a product invariant (FR-28), not just an ops note.
- Operational conflict: `validate.sh` / `finish-feature.sh` recreate the primary Postgres container — a running multi-day backfill and a validation cycle must never overlap. FR-28's product surface should make an active backfill *visible* precisely so this collision stops being tribal knowledge.

## Alternatives considered (product + process)

| Theme | Chosen (date) | Rejected / deferred |
|-------|---------------|---------------------|
| Hosting | Local-first single operator | Multi-tenant cloud SaaS |
| AI topology | Local default + quota-bounded free-tier cloud assist (2026-08-05) | Cloud-only LLM; paid-tier planning basis; lift-and-shift of stack to cloud free tiers (research: scrapers must keep residential egress; cloud holds at most a slim regenerable read-model) |
| v0.13 headline | Cloud/local split productization + deal-intelligence (2026-08-05) | Multi-city productization — deferred to v0.14 candidate (largest UX/data surface; coverage already flows opportunistically) |
| Planning/dev regime | **BMad-SoR + bmad-loop** (settled 2026-08-05) | Linear-SoR + feature-pipeline (superseded; Linear stays as tracking mirror); staying hybrid indefinitely |
| Parallel agents | Worktree when primary busy (ADR 0004) | Always-on nested `.worktrees/` |

## SoR pivot — remaining execution (harness track, pre-epic gate)

Waves 1–2 done (project-context + hybrid-stack research; correct-course + this PRD). Remaining before v0.13 story execution:

- **Wave 3:** per-epic verification (testarch-trace + adversarial/edge-case reviews) feeding the bmad-loop deferred-work ledger.
- **Wave 4:** harness surgery — rewrite CLAUDE.md (invert the "never BMad dev skills / always feature-pipeline" mandate), remove non-BMad `.claude/skills/` duplicates, wire `scripts/agent/*` gates into bmad-loop via `bmad-customize`. Also correct stale memory notes that describe the pivot as undecided.

## Debt carried into planning (not v0.13 commitments unless listed in §6.2)

- Condo/IPTU normalization → **promoted to FR-31** (Theme B candidate).
- Dead listing URL pruning — still debt.
- Config hot-reload absent — still debt.
- Map tiles require internet — accepted.
- Image store MD5 identity; `asyncio.run` inside sync Celery AI tasks — still debt.
- Schedule changes may need Celery beat restart — still debt.
- AD-1 core→ORM dedupe leak burn-down status — verify during architecture pass (flagged in correct-course §4.2).

## Linear mapping (pre-epic) — historical

*[Amended 2026-08-05, post-epics: Linear dropped entirely (ADR 0005). The table below is the shipped-history mapping only; v0.13 rows are tracked as epics.md story keys (v0.13-s1.1…s2.4), not Linear issues.]*

| FR | Status / seed |
|----|---------------|
| FR-18–FR-23 | Shipped (v0.5 BIN-19–23; Zap = BIN-127) |
| FR-24 / FR-25 / FR-26 | Shipped (v0.6 BIN-85 area / v0.7 BIN-96 area / v0.12 BIN-241–249 area) |
| FR-27–FR-29 (Theme A) | v0.13 epic(s) — create milestone `v0.13` + parent epic at epics sync |
| FR-30–FR-32 (Theme B) | v0.13 epic — cut decided at epics after readiness |
