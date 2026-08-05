# Epic 1 Context: Hybrid Enrichment, Productized (Theme A)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Turn the cloud/local AI-enrichment split from operator folklore into a sanctioned, observable product capability. The operator selects enrichment backends per task class (validated at startup), runs a quota-governed cloud backfill he can start/pause/resume from the Operações surface and leave unattended for its multi-day run, and reads DB-derived coverage telemetry showing percent enriched, throughput, and a credible completion ETA. An active backfill is visible from the front door (Painel health strip). Cloud stays strictly optional and batch-only: with no key or exhausted quota, everything degrades to local Ollama/LM Studio — the permanent default and fallback — without operator intervention. Covers FR-27 (routing), FR-28 (backfill as a surface), FR-29 (coverage telemetry); realizes user journeys UJ-3, UJ-4.

## Stories

- Story 1.1: Canonical enrichment task classes + per-task-class routing config
- Story 1.2: Live pipeline routes by task class with local fallback
- Story 1.3: Backfill runner control core — lease, pause/resume, safe interruption
- Story 1.4: Enrichment coverage telemetry (DB-derived)
- Story 1.5: Admin backfill control API — start/pause/resume/status under the shared lease
- Story 1.6: Operações — backfill card, coverage display, front-door visibility

## Requirements & Constraints

- **FR-27 — Multi-backend routing:** operator picks backends per task class via `AppConfig`. Local is the default and permanent fallback; cloud never becomes required. Invalid backend/task-class combinations must fail fast at config load with a clear, key-naming error — not mid-pipeline. With cloud unavailable (no key, quota exhausted, network down), enrichment degrades to local automatically.
- **FR-28 — Backfill as a product surface:** the resumable runner graduates from `scripts/dev` to operator-facing start/pause/resume/status with visible progress and pacing. A backfill interrupted at any point (crash, quota exhaustion, operator stop) resumes without re-enriching completed rows. Daily request count never exceeds the configured budget; provider `ResourceExhausted` triggers back-off, not failure.
- **FR-29 — Coverage telemetry:** per signal type, the fraction of Properties enriched, backfill throughput, and a projected completion date. Figures derive from the DB and survive runner restarts.
- **Quota sizing basis:** free-tier Gemma ≈ 30 RPM / 14,400 RPD best-case (`ResourceExhausted` may fire early); ~3 requests/property ⇒ ≈4,600 properties/day ⇒ whole-DB backfill is inherently multi-day (~6-day planning basis). Never plan single-day whole-DB cloud runs.
- **NFRs in play:** NFR-1 local-first with bounded cloud assist; NFR-2 config via `AppConfig`/`app_config.yaml` (never scattered `os.getenv`); NFR-3 no hardcoded secrets, cloud keys via env only, admin routes API-key gated; NFR-4 resilience (quota exhaustion degrades, never outage); NFR-6 observability (coverage is a first-class SLO).
- **Validation gates:** AI prompt/client changes run `validate-ai.sh`; API schema changes update/run `src/tests/contract/`; DB schema changes run `alembic check`. AI scores stay floats in [0.0, 1.0]. Config tests must clear `get_config()`'s `lru_cache`.

## Technical Decisions

- **AD-13 (cloud assist, bounded):** cloud path is optional, operator-triggered, batch-backfill-only. Incremental (live Celery) enrichment always routes local; FR-27 per-task-class routing decides cloud-*eligibility for backfill only*. Every cloud request is metered by the single Redis pacer (`BackfillConfig.redis_prefix`, default `backfill:gemma`) — no second quota consumer ever. Config that would produce an unmetered cloud call (e.g. legacy scalar `ai.backend: gemini|gemma` on a live path) must fail FR-27 startup validation. Backend routing has one `AppConfig`-owned source of truth (task-class map supersedes the scalar key) with one startup validator. At most one runner holds the backfill lease (CLI and admin share it); budget consumption is atomic under that lease.
- **Canonical task-class enum:** one enum of enrichment task classes / signal types, in `src/core/` (framework-free, no adapter imports), shared by FR-27 routing, FR-28 backfill scope, and FR-29 coverage. No per-feature vocabularies. This is the foundation story (1.1) for the whole epic.
- **FR-29 data source:** coverage/ETA derives from the DB. Runner Redis checkpoints are internal pacing state, never a second progress metric.
- **AD-4 / AD-10 (runner posture):** the backfill runner is a sanctioned second *driver* through the single enrichment pipeline authority — never a second writer. It does no GPU work; if it ever gains a local-backend mode, that mode goes through the `ai` queue + semaphore. No model call happens inline from an API request thread.
- **AD-6 (admin surface):** admin/backfill endpoints are auth-gated at the API edge (`verify_admin_access`) and audited via `admin_audit`. Coverage endpoint is the auth-gated `system`/`admin` surface.
- **AD-8:** the frontend talks only to the FastAPI surface — no direct infra access.
- **AD-1 (hexagonal):** `core` must not import `adapters`/`api`. Do not add new leaks while touching `core/backfill_runner.py`.
- **Existing code touched:** `src/infra/config.py` (routing map + validator), `src/adapters/ai/enrich_pipeline.py` / `client.py` (live routing), `src/core/backfill_runner.py` (`DailyBudget`, `Checkpoint`, `Heartbeat`; lease/pause/resume), `scripts/dev/backfill_gemma.py` (CLI), `src/api/admin.py` + `schemas.py` (admin + coverage endpoints), reuse `estimate_eta_days`.
- **Testing tiers:** TDD on `src/core/` + config (valid/invalid/legacy-scalar/degraded branches, state-machine branches with mocked Redis/session); thin-glue happy+error path for admin endpoints; contract tests for new response models; rate-limited-route unit tests bypass slowapi Redis.

## UX & Interaction Patterns

Story 1.6 surfaces only; all new v0.13 UI is dark-only Meia-noite tokens (UX-DR1), pt-BR default with both `en`/`pt-BR` catalogs and English wire enums (UX-DR2), honest absence — no progress bars, no fabricated values, non-blocking bottom toasts (UX-DR3).

- **Backfill card (Operações):** states in pt-BR `inativo / em execução / pausado / em espera (limite da API)` (wire enum `idle/running/paused/backing-off`); today's budget use, throughput, and day-scale ETA as tabular text lines — simply absent with no active run; start/pause/resume controls wired to the admin API. A lease conflict on start surfaces as a toast naming the active run. While running, a persistent `health-warn` warning line with glyph (collision reminder; the shell-side heartbeat `backfill:gemma:active` is the real guard). Visual: `surface-card`, hairline border, default radius, no bars (UX-DR5).
- **Coverage display:** per-signal-type breakout (visual, sentiment, valuation, embeddings) as text percentages only — no tracks, no bars (UX-DR6).
- **Front-door slice (Painel health strip):** an active backfill is operator-visible always — a backfill chip with warning glyph while running, plus `Cobertura de IA N%` as text where N is the minimum across signal types, labeled as such on hover. Per-type detail lives in Operações; per-scraper chip semantics are v0.14/FR-37, out of scope here (UX-DR7).
- Nav label for the admin surface is **Operações**; use "coleta" for a scrape run on user-facing surfaces.
- e2e: Playwright covers the card's happy path (status render + a control action against a mocked/stubbed API) and asserts honest absence (no ETA/throughput text with no active run).

## Cross-Story Dependencies

- Story 1.1 (canonical enum + routing map) is the foundation — everything else builds on it. Sequencing gates: 1.2←1.1, 1.3←1.1, 1.4←1.1, 1.5←1.3, 1.6←1.4+1.5.
- Stories 1.4 (coverage API) and 1.5 (admin control API) both feed the Story 1.6 UI. FR-29 telemetry lands independently of the runner-control slices.
- Epic 1 and Epic 2 share no core files and can run in parallel after the harness-track gate (landed as v0.13-fu1).
- External foundations reused: single Redis pacer / `BackfillConfig`, existing notifier/`admin_audit` infra, `migrate-primary.sh` which refuses while `backfill:gemma:active` is alive (validation is primary-safe on the ephemeral test stack).
