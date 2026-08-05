# Addendum — Imoveis Deal Tracker PRD (2026-08-05)

Technical and planning depth that belongs downstream (architecture, epics) or supports the PRD without bloating it. Supersedes the 2026-07-23 addendum; unchanged entries carried forward.

## Mechanism decisions (for architecture)

- Stack (current, post-v0.12): FastAPI, Celery + Redis, PostgreSQL 17 + PostGIS 3.5 + pgvector (in-repo image, BIN-272), React 19 / Vite 8 / TypeScript strict, maplibre-gl 6, host Ollama / LM Studio, FlareSolverr in Compose, full pip-compile lockfile (BIN-138).
- AI backends: `ai.backend: ollama | lmstudio | gemini | gemma` already exists in `configs/app_config.yaml` — FR-27 productizes routing semantics on top of it, not a new config surface.
- Backfill runner: `core/backfill_runner.py` + `scripts/dev` CLI (BIN-248) writes through the single enrichment pipeline authority — architecture pass should name it a sanctioned second *driver* (AD-4/AD-10 note), plus AD-13 (or AD-7 amendment) bounding the cloud-assist path.
- Redis is multi-surface: Celery broker, slowapi rate limiting, `ui:locale` override, `backfill:gemma` pacer. Any Redis change is a multi-surface refactor.
- Scraper plugin registry; queues `scrapers` vs `ai` (GPU semaphore; host `OLLAMA_NUM_PARALLEL` = `gpu.semaphore_limit`).
- Dedup defaults: 50 m geo, ±2 m² area, Jaro–Winkler ≥ 0.65 (config-driven).
- Implementation gates *(updated post-v0.13-fu1)*: `scripts/agent/validate.sh` is THE merge gate, run locally by `finish-feature.sh` (validate → squash-merge → push — the only path to `main`); CI is reduced to docs deploy + nightly scraper drift canary. bmad-loop wraps the gates via `bmad-customize`, never replaces them.

## Cloud-assist sizing data (for FR-28/FR-29 planning)

- Gemini API key is **free tier**. Gemma: ~30 RPM / **14,400 RPD** / 16K TPM best-case; `ResourceExhausted` can fire early. Gemini Flash free RPD is an order of magnitude smaller (~20 RPD for 2.5 Flash) — Gemma is the backfill workhorse.
- At ~3 requests/property ⇒ ≈4,600 properties/day ⇒ whole-DB backfill is inherently **multi-day (~6 days observed planning basis)**. Single-day whole-DB requires paid tier or local-only — out of scope (§5).
- Exactly one pacer (`backfill:gemma`) owns the daily budget. "Never add a second quota consumer" is a product invariant (FR-28), not just an ops note.
- ~~Operational conflict: `validate.sh` / `finish-feature.sh` recreate the primary Postgres container — a running multi-day backfill and a validation cycle must never overlap.~~ **Resolved by v0.13-fu1:** validation runs on the ephemeral test stack and never touches the primary project; the remaining guarded operation is `migrate-primary.sh`, which refuses while the backfill heartbeat (`backfill:gemma:active`) is alive. FR-28's visibility rationale stands on its own: an active backfill should be *visible* as a product surface, not tribal knowledge.

## Alternatives considered (product + process)

| Theme | Chosen (date) | Rejected / deferred |
|-------|---------------|---------------------|
| Hosting | Local-first single operator | Multi-tenant cloud SaaS |
| AI topology | Local default + quota-bounded free-tier cloud assist (2026-08-05) | Cloud-only LLM; paid-tier planning basis; lift-and-shift of stack to cloud free tiers (research: scrapers must keep residential egress; cloud holds at most a slim regenerable read-model) |
| v0.13 headline | Cloud/local split productization + deal-intelligence (2026-08-05) | Multi-city productization — deferred to v0.14 candidate (largest UX/data surface; coverage already flows opportunistically) |
| Planning/dev regime | **BMad-SoR + bmad-loop** (settled 2026-08-05) | Linear-SoR + feature-pipeline (superseded; Linear stays as tracking mirror); staying hybrid indefinitely |
| Parallel agents | Worktree when primary busy (ADR 0004) | Always-on nested `.worktrees/` |

## SoR pivot — harness track (COMPLETE, 2026-08-05)

All four waves done. Waves 1–2: project-context + hybrid-stack research; correct-course + this PRD. Wave 3: per-epic verification feeding the bmad-loop deferred-work ledger. **Wave 4 landed as `v0.13-fu1`** (main `8f5d885` + `f2da788`): CLAUDE.md rewritten (BMad-only harness, legacy skills removed), `scripts/agent/*` gates wired via `bmad-customize`, validation made primary-safe (ephemeral test stack), merge gate made PR-less local (`finish-feature.sh`). The pre-epic gate held: surgery completed before v0.13 story execution.

## UX contract (2026-08-05) — depth pointers

- Design authority: `ux-designs/ux-imoveis-2026-08-05/` — DESIGN.md (Meia-noite token palette, editorial verdict components, contrast table) + EXPERIENCE.md (IA, state patterns, J1–J4 journeys, pt-BR microcopy). PRD holds capability-level FRs only; interaction detail stays there.
- Product-model decisions settled in the UX run and folded into PRD §1/§3/§4.5: starred = watched (no separate watchlist surface); Favoritos = availability tracking + filterable gone-history + optional-reason discard (visit-day framing dropped); detail = side panel, map rail stays visible; map→grid filtering explicit via `filtrar pela área do mapa` chip; since-panel resets on real engagement only; drop-alert threshold per saved search; channels = email (guaranteed) + in-app + desktop push, no Telegram.
- Consciously undesigned (deliberate, not gaps): export UI (stays API/digest-only), auth/API-key management UI (stays key gate), Compare (minimal/deprioritized).
- FR-33–FR-38 originate from EXPERIENCE.md `[NOTE FOR PRD]` flags; recheck cooldown/budget numbers and run-history baseline mechanics are design-level detail in EXPERIENCE.md, to be hardened at architecture/epics time when scheduled.

## Debt carried into planning (not v0.13 commitments unless listed in §6.2)

- Condo/IPTU normalization → **promoted to FR-31** (Theme B candidate) → *deferred at epics 2026-08-05; back on the ledger.*
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
| FR-30–FR-32 (Theme B) | Cut decided at epics: FR-30 + FR-32 in (Epic 2, v0.13-s2.1…s2.4); FR-31 deferred |
