---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
status: complete
completed: 2026-08-05
tracking: >
  BMad artifacts are the SOLE tracker (ADR 0005, 2026-08-05 — Linear dropped entirely;
  the partial v0.13 sync BIN-273/274/275 + milestone was canceled/abandoned in Linear).
  This document is the plan of record; execution status lives in
  _bmad-output/implementation-artifacts/sprint-status.yaml. Story keys: v0.13-s1.1 …
  v0.13-s1.6 (Epic 1), v0.13-s2.1 … v0.13-s2.4 (Epic 2). Sequencing gates:
  s1.2←s1.1, s1.3←s1.1, s1.4←s1.1, s1.5←s1.3, s1.6←s1.4+s1.5, s2.2←s2.1, s2.4←s2.3.
inputDocuments:
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-08-05/prd.md'
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-08-05/addendum.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/COMPANION-architecture-delta.md'
  - '_bmad-output/planning-artifacts/sprint-change-proposal-2026-08-05.md'
excludedDocuments:
  - 'UX design contract (none present; brownfield pass without bmad-ux)'
  - 'epics-delivered-2026-07-27.md (historical Epics 1–5 record — fresh set, not an extension)'
supersedes: 'epics-delivered-2026-07-27.md (Epics 1–5, BIN-19…23, delivered)'
planningTarget: 'v0.13'
created: 2026-08-05
---

# imoveis - Epic Breakdown (v0.13)

## Overview

This document provides the complete epic and story breakdown for **imoveis v0.13**, decomposing the requirements from the PRD (2026-08-05), its addendum, and the Architecture Spine (updated 2026-08-05) into implementable stories. The prior epic set (Epics 1–5, delivered 2026-07-27 as BIN-19…23) is archived at `epics-delivered-2026-07-27.md`; this is a fresh set, not an extension.

**Scope of this set:** v0.13 Theme A (FR-27, FR-28, FR-29 — cloud/local AI-enrichment split productization) and the Theme B cut decided at epics time (FR-30 + FR-32; FR-31 deferred). Baseline FR-1–FR-26 is shipped (v0.1–v0.12) and receives no new stories.

## Requirements Inventory

### Functional Requirements

**Shipped baseline (v0.1–v0.12 — no new stories; definition of record: superseded PRDs + `docs/features/`):**

- FR-1–FR-3: pluggable scraper platform, scheduled scraping, checkpoint/resume.
- FR-4–FR-6: cross-platform dedupe, price history, per-platform price comparison.
- FR-7–FR-11: local AI enrichment (visual condition, sentiment, statistical valuation, deal verdict), skip-unchanged.
- FR-12–FR-15: discovery UX (score-coloured grid, filters, favourites/saved searches, semantic search).
- FR-16–FR-17: watchlist price-drop alerts, admin/ops telemetry.
- FR-18–FR-23: comparison UI, auth/API-key gate, proxy rotation, export + digest, neighbourhood polygons, ZapImóveis platform.
- FR-24–FR-26: neighbourhood quality profiles, dual listing-type scoring, listing-description enrichment.

**v0.13 planned (this epic set):**

FR-27: First-class multi-backend enrichment routing. Operator selects enrichment backends per task class (e.g. text signals → cloud-eligible, visual → local) via `AppConfig`, with documented semantics, validation at startup, and contract coverage. Local Ollama/LM Studio remains the default and the permanent fallback — cloud never becomes required (NFR-1). Testable consequences: (a) invalid backend/task-class combinations fail fast at config load with a clear error, not mid-pipeline; (b) with cloud unavailable (no key, quota exhausted, network down), enrichment degrades to the local path without operator intervention.

FR-28: Quota-governed cloud backfill as a product surface. The resumable backfill runner graduates from `scripts/dev` to an operator-facing operation: start/pause/resume, progress and pacing state visible, safe-by-construction quota use. The single Redis pacer (`backfill:gemma`) remains the only budget owner; no second consumer of the quota is ever added. Testable consequences: (a) a backfill interrupted at any point (crash, quota exhaustion, operator stop) resumes without re-enriching completed rows; (b) daily request count never exceeds the configured budget; provider `ResourceExhausted` triggers back-off, not failure.

FR-29: Enrichment coverage telemetry. Operator can see, per signal type, what fraction of Properties is enriched, backfill throughput, and a projected completion date for an active backfill. Testable consequence: coverage figures derive from the DB (not runner logs) and survive runner restarts.

FR-30: Price-per-m² percentile views. User sees where a Property's price/m² falls within its neighbourhood cohort (percentile on card/modal, filterable). Cohorts come from shipped neighbourhood polygons (FR-22) + dual-type scoring (FR-25); no new geo work.

FR-32: Saved-search new-match alerts. A saved search can notify when a **new** Property matching it appears — extending alerts beyond watched-property price drops. Reuses the shipped notifier registry (FR-21) and saved searches (FR-14); no new channel work for v1.

**Theme B cut (decided at epics time, 2026-08-05):** FR-30 + FR-32 are in; **FR-31 (total-cost-of-occupancy normalization) is deferred** — it carries the worst data-availability risk (partial platform fee coverage, PRD §9 Q2), and the v0.13 success metric requires ≥1 Theme B FR; the chosen pair ships two with bounded risk. FR-31 stays on the debt ledger for a later wave.

**FR-28 surface decision (PRD §9 Q1, decided at epics time):** admin-panel exposure **is** the v0.13 target, built as slices — hardened runner control core (lease, pause/resume semantics) first, then auth-gated admin API + panel visibility/control, with FR-29 telemetry landing independently. A CLI-only cut remains the fallback slice if the wave must shrink.

### NonFunctional Requirements

NFR-1: Local-first with bounded cloud assist — core enrichment and storage run on operator hardware; no *required* cloud AI. Sanctioned exception: the quota-bounded, operator-triggered, batch-only cloud-assist path (Gemini/Gemma free tier) may accelerate backfill, never gate core function; the local path is never removed.

NFR-2: Config discipline — runtime settings via `AppConfig` / `configs/app_config.yaml` (+ env), never scattered `os.getenv` in feature code.

NFR-3: Security — no hardcoded production secrets; `imoveis_secret` / `dev-secret-key` forbidden in repo; admin routes require API key when configured; cloud API keys via env only.

NFR-4: Resilience — circuit breakers and checkpoints keep scrapes operable under partial platform failure; quota exhaustion degrades to local enrichment, not outage.

NFR-5: Testability — merge requires green CI (lint, unit, integration, contract, scrapers live gate, e2e, security); gates preserved unchanged across the SoR pivot.

NFR-6: Observability — pipeline telemetry and system health support unattended operation; extended in v0.13 to enrichment coverage and backfill pacing (FR-29).

NFR-7: i18n — English default; pt-BR supported via catalogs + preference (`ui.locale` / Redis); canonical DB/API wire values remain English; new user-facing strings must land in both catalogs.

NFR-8: Geography & tenancy posture — BH/MG primary geography, opportunistic SP/Campinas data; single-tenant personalization (nullable `owner`) until multi-city / multi-profile is explicitly productized.

### Additional Requirements

**From the Architecture Spine (binding on story design):**

- **AD-13 (cloud assist, bounded):** cloud path is optional, operator-triggered, batch-backfill-only. Incremental (live Celery) enrichment always routes to local backends; FR-27's per-task-class routing decides cloud-*eligibility for backfill* only. Every cloud request is metered by the single Redis pacer (`BackfillConfig.redis_prefix`, default `backfill:gemma`). Config that would produce an unmetered cloud call (e.g. legacy scalar `ai.backend: gemini|gemma` on a live path) must fail FR-27's startup validation, not run silently. Backend routing has **one** AppConfig-owned source of truth (the FR-27 task-class map supersedes the scalar key) with one startup validator. At most one runner instance holds the backfill lease (CLI and admin surface share it); budget consumption is atomic under that lease. An active backfill is operator-visible; quota exhaustion / provider errors back off or degrade to local — never outages.
- **Canonical vocabulary:** one enum of enrichment task classes / signal types shared by FR-27 routing, FR-28 backfill scope, and FR-29 coverage — no per-feature vocabularies.
- **FR-29 data source:** coverage/ETA derives from the **DB**; runner Redis checkpoints are internal pacing state, never a second progress metric.
- **Derived cohort stats (FR-30):** computed in the metrics/enrichment pipeline stage (AD-10), on a single price basis defined there, cohort-keyed **neighbourhood × listing type**, with a config-owned min-cohort size (AD-2); consumed read-only via the AD-12 canonical projection — no read-time re-derivation in views. Percentiles on cohorts below min size are suppressed, not shown (counter-metric: signal noise).
- **FR-32 delivery path:** notifications go through Celery + the single notifier preference registry (AD-9); subscription identity uses the single principal model (AD-11); saved-search matching must not create a second writer of Property/Listing fields (AD-3).
- **Admin surface (FR-28):** auth-gated at the API edge and audited (`admin_audit`, AD-6); frontend talks only to the FastAPI surface (AD-8).
- **Backfill runner status (AD-4/AD-10):** sanctioned second *driver* through the single enrichment pipeline authority — never a second writer; does no GPU work; if it ever gains a local-backend mode, that mode goes through the `ai` queue + semaphore.
- **Brownfield:** no starter template; all work lands in the existing `src/` hexagonal layout. `core` must not import `adapters`/`api` (AD-1) — do not add new leaks while touching `core/backfill_runner.py`.

**Operational/process requirements:**

- **Quota sizing basis (FR-28/29):** free-tier Gemma ≈ 30 RPM / 14,400 RPD best-case (`ResourceExhausted` can fire early); ~3 requests/property ⇒ ≈4,600 properties/day ⇒ whole-DB backfill is inherently multi-day (~6 days planning basis). Never plan single-day whole-DB cloud runs.
- **Backfill vs validation collision:** `validate.sh`/`finish-feature.sh` recreate the primary Postgres container; FR-28's surface must make an active backfill visible precisely so this collision stops being tribal knowledge.
- **Harness-track gate (process, not an FR):** SoR-pivot waves 3–4 (per-epic verification feeding the bmad-loop deferred-work ledger; CLAUDE.md rewrite + gate wiring via `bmad-customize`) complete **before** v0.13 story execution starts.
- **Validation gates:** API schema changes update/run `src/tests/contract/`; DB schema changes run `alembic check`; AI prompt/client changes run `validate-ai.sh`; all merges through `validate.sh` + CI.

### UX Design Requirements

No UX design contract exists for this wave (no `ux-designs/` folder or legacy UX documents in planning artifacts). UI work in FR-28 (admin backfill card), FR-29 (coverage telemetry display), FR-30 (percentile on card/modal + filter), and FR-32 (saved-search alert toggle) follows the shipped admin-panel and property-grid patterns plus NFR-7 i18n conventions.

### FR Coverage Map

FR-1–FR-26: Shipped baseline (v0.1–v0.12) — no epic in this set; definition of record in `docs/features/`.
FR-27: Epic 1 — first-class multi-backend enrichment routing (task-class map, startup validation, local fallback).
FR-28: Epic 1 — quota-governed cloud backfill as an operator surface (hardened runner control + admin API/panel).
FR-29: Epic 1 — enrichment coverage telemetry (DB-derived coverage, throughput, ETA).
FR-30: Epic 2 — price-per-m² percentile views (pipeline-computed cohort stats → projection → UI).
FR-31: **Deferred (not covered in v0.13)** — worst data-availability risk; stays on the debt ledger.
FR-32: Epic 2 — saved-search new-match alerts (matcher on the pipeline, notifier registry delivery, UI toggle).

## Epic List

### Epic 1: Hybrid Enrichment, Productized (Theme A)

Felipe (operator) runs the cloud/local AI-enrichment split as a sanctioned, observable product capability instead of operator folklore: per-task-class backend routing validated at startup, a quota-governed cloud backfill he can start/pause/resume from the admin surface and leave unattended for its multi-day run, and DB-derived coverage telemetry showing % enriched, throughput, and a credible ETA. Cloud stays optional — with no key or exhausted quota, everything degrades to local Ollama without intervention. Realizes UJ-3, UJ-4.

**FRs covered:** FR-27, FR-28, FR-29
**NFRs in play:** NFR-1, NFR-2, NFR-3, NFR-4, NFR-6
**Governed by:** AD-13, AD-2, AD-4, AD-6, AD-8, AD-10, AD-12 (coverage projection); canonical task-class enum convention

### Epic 2: Deal-Intelligence Deepening (Theme B cut)

Ana and Bruno (users) get sharper deal signals than one combined score: every property card/modal shows where its price/m² falls within its neighbourhood × listing-type cohort (filterable, suppressed on too-small cohorts), and saved searches notify when a **new** matching property appears — so a good deal surfaces without rebuilding filters every evening. Realizes UJ-1, UJ-2.

**FRs covered:** FR-30, FR-32
**NFRs in play:** NFR-6, NFR-7, NFR-8
**Governed by:** AD-10 (cohort stats in pipeline stage), AD-12 (read-only projection), AD-3, AD-8, AD-9 (one notifier registry), AD-11 (principal model)

**Epic dependencies:** None between the two — Epic 2 touches the metrics/alerts/UI surfaces, Epic 1 the AI-routing/backfill/telemetry surfaces; they share no core files and can run in parallel after the harness-track gate. Within Epic 1, the canonical task-class enum story is the foundation for everything else.

## Epic 1: Hybrid Enrichment, Productized (Theme A)

Felipe (operator) runs the cloud/local AI-enrichment split as a sanctioned, observable product capability: per-task-class backend routing validated at startup (FR-27), a quota-governed cloud backfill controllable from CLI and admin surface under one lease (FR-28), and DB-derived coverage telemetry with a credible ETA (FR-29). Cloud stays optional and batch-only; local Ollama/LM Studio is the permanent default and fallback (NFR-1, AD-13).

### Story 1.1: Canonical enrichment task classes + per-task-class routing config

As the operator,
I want one canonical vocabulary of enrichment task classes with a per-task-class backend routing map in `AppConfig`, validated at startup,
So that routing, backfill scope, and coverage telemetry all speak the same language and misconfiguration fails fast instead of mid-pipeline.

**Acceptance Criteria:**

**Given** the codebase has no shared enrichment vocabulary
**When** this story lands
**Then** a single enum of enrichment task classes / signal types exists in `src/core/` (framework-free, no adapter imports — AD-1) and is the only vocabulary used by routing, backfill scope, and coverage (consistency convention)
**And** `AppConfig` gains a task-class → backend routing map (superseding the scalar `ai.backend` key as the single source of truth — AD-13, AD-2) with documented semantics in `configs/app_config.yaml`

**Given** a config with an invalid backend/task-class combination (unknown backend, unknown task class, or a cloud backend routed to a live/incremental path)
**When** the application loads config
**Then** startup fails with a clear, actionable error naming the offending key — not a mid-pipeline failure (FR-27)
**And** the legacy scalar `ai.backend: gemini|gemma` (which would produce an unmetered cloud call on a live path) is rejected by the same validator (AD-13)

**Given** the default shipped config
**When** config loads
**Then** all task classes route to the local backend and validation passes (NFR-1 — local default; existing deployments keep working)
**And** unit tests cover valid/invalid/legacy-scalar branches (TDD — `src/core/` + `src/infra/config.py` surface), clearing `get_config()`'s `lru_cache` per testing rules

### Story 1.2: Live pipeline routes by task class with local fallback

As the operator,
I want live enrichment to resolve its backend per task class through the new routing map, degrading to local automatically when cloud is unavailable,
So that incremental enrichment never depends on cloud availability or quota (NFR-1, NFR-4).

**Acceptance Criteria:**

**Given** the routing map from Story 1.1
**When** the live Celery `ai`-queue pipeline (`src/adapters/ai/enrich_pipeline.py` / `client.py`) enriches a property
**Then** each task class's backend is resolved from the map, and live/incremental work only ever executes on local backends (cloud-eligibility applies to backfill scope only — AD-13, AD-4)
**And** no model call happens inline from an API request thread (AD-4)

**Given** a task class marked cloud-eligible while cloud is unavailable (no `GEMINI_API_KEY`, quota exhausted, or network down)
**When** enrichment for that class runs via the backfill driver
**Then** it degrades to the local path (or backs off, for budget exhaustion) without operator intervention and without marking the property failed (FR-27 consequence b, NFR-4)

**Given** the AI prompt/client surface changed
**When** the story completes
**Then** `bash scripts/agent/validate-ai.sh` passes, and contract tests still hold (AI scores remain floats in [0.0, 1.0])
**And** routing resolution has unit coverage for local-default, cloud-eligible, and degraded branches

### Story 1.3: Backfill runner control core — lease, pause/resume, safe interruption

As the operator,
I want the resumable backfill runner hardened with a single-instance lease and explicit start/pause/resume/stop semantics,
So that CLI and (later) admin surface can share control safely and an interrupted multi-day run always resumes without re-enriching or double-spending quota (FR-28).

**Acceptance Criteria:**

**Given** the existing runner (`src/core/backfill_runner.py`: `DailyBudget`, `Checkpoint`, `Heartbeat`) and CLI (`scripts/dev/backfill_gemma.py`)
**When** this story lands
**Then** at most one runner instance can hold the backfill lease at a time (Redis-backed, under `BackfillConfig.redis_prefix`, default `backfill:gemma`); a second start attempt is refused with a clear message (AD-13)
**And** budget consumption is atomic under that lease — the daily request count can never exceed `backfill.daily_request_budget` (FR-28 consequence b)

**Given** a running backfill interrupted at any point (crash, quota exhaustion, operator pause/stop)
**When** the runner restarts or resumes
**Then** it continues from the checkpoint without re-enriching completed rows (FR-28 consequence a)
**And** provider `ResourceExhausted` triggers back-off-and-wait (sleep until budget reset), never failure or data loss (NFR-4)

**Given** the runner's scope selection
**When** rows are chosen for backfill
**Then** scope is expressed in Story 1.1 task classes, and all writes go through the single enrichment pipeline authority (AD-10 — second driver, never second writer; no GPU work, no new `core` → `adapters` import leaks — AD-1)
**And** pause/resume/lease semantics have unit tests with a mocked Redis/session (state-machine branches covered; TDD on `src/core/`)

### Story 1.4: Enrichment coverage telemetry (DB-derived)

As the operator,
I want per-signal-type enrichment coverage, backfill throughput, and a projected completion date served from the DB,
So that I can judge backfill progress and remaining work mid-run without reading runner logs (FR-29, NFR-6).

**Acceptance Criteria:**

**Given** properties in the DB with and without enrichment signals
**When** I call the coverage endpoint (auth-gated `system`/`admin` surface — AD-6)
**Then** I get, per Story 1.1 signal type, the fraction of Properties enriched, derived from DB queries — not runner logs or Redis checkpoints (FR-29; runner Redis state is never a second progress metric)
**And** figures survive runner restarts and are correct with the runner not running at all

**Given** an active backfill
**When** I request coverage
**Then** the response includes backfill throughput (properties/day) and a projected completion date consistent with the quota sizing basis (~4,600 properties/day best-case; reuses `estimate_eta_days`)
**And** with no active backfill, throughput/ETA fields are absent or null — never fabricated

**Given** this adds an API schema surface
**When** the story completes
**Then** `src/api/schemas.py` + `src/tests/contract/` cover the new response model (fractions as floats in [0.0, 1.0])
**And** the endpoint has one happy-path and one degraded-path (empty DB) test; no second telemetry bus is introduced (consistency convention)

### Story 1.5: Admin backfill control API — start/pause/resume/status under the shared lease

As the operator,
I want auth-gated admin endpoints to start, pause, resume, and inspect the cloud backfill,
So that backfill control is a product surface, not tribal CLI knowledge — and an active run is visible before I start anything that would collide with it (FR-28).

**Acceptance Criteria:**

**Given** the hardened runner core from Story 1.3
**When** I call the admin backfill endpoints (`src/api/admin.py`, behind `verify_admin_access` — AD-6)
**Then** I can start/pause/resume a backfill and fetch its status (state, progress, today's budget consumed/remaining, pacing), sharing the **same** lease and pacer as the CLI — no second control path or quota consumer (AD-13)
**And** starting while a lease is held (by CLI or a prior admin start) returns a conflict response naming the active run, not a second runner

**Given** the operational collision risk (validate/finish cycles recreate the primary Postgres container)
**When** a backfill is active
**Then** its status is visible via the status endpoint (and surfaced in Story 1.6's UI) so the collision stops being tribal knowledge
**And** admin actions are recorded in the `admin_audit` trail (AD-6)

**Given** this adds admin API schema
**When** the story completes
**Then** contract tests cover the new endpoints; unit tests mock the runner/lease (thin-glue tier: one happy path + one conflict/error path per endpoint)
**And** rate-limited-route unit tests bypass slowapi Redis per testing rules

### Story 1.6: Admin panel — backfill card + coverage display

As the operator,
I want the admin panel to show the backfill's state and controls plus enrichment coverage per signal type,
So that I can kick off, monitor, and pause the multi-day run and watch % enriched climb without touching a terminal (FR-28, FR-29; UJ-4 climax).

**Acceptance Criteria:**

**Given** the APIs from Stories 1.4 and 1.5
**When** I open the admin panel (`frontend/`, talking only to the FastAPI surface — AD-8)
**Then** I see a backfill card with current state (idle/running/paused/backing-off), progress, today's budget use, throughput, and ETA, plus start/pause/resume controls wired to the admin API
**And** I see per-signal-type coverage (% enriched) rendered from the FR-29 endpoint

**Given** an active backfill
**When** the panel is open
**Then** the active run is unmistakably visible (the operational-collision warning surface), and control errors (e.g. lease conflict) render as non-blocking toasts (consistency convention)

**Given** product i18n
**When** the story completes
**Then** all new strings land in both `en` and `pt-BR` catalogs (NFR-7)
**And** a Playwright e2e covers the card's happy path (status render + a control action against a mocked/stubbed API)

## Epic 2: Deal-Intelligence Deepening (Theme B cut)

Ana and Bruno (users) get sharper deal signals than one combined score: price/m² percentile within the neighbourhood × listing-type cohort on every card/modal with filtering (FR-30), and saved searches that notify when a new matching Property appears (FR-32). Both consume shipped foundations (polygons, dual-type scoring, saved searches, notifier registry) — no new geo or channel work.

### Story 2.1: Cohort price/m² percentiles computed in the pipeline

As a user evaluating a listing,
I want each Property's price/m² percentile computed within its neighbourhood × listing-type cohort,
So that "cheap for Savassi rentals" is a stored, trustworthy signal rather than a guess (FR-30).

**Acceptance Criteria:**

**Given** properties with area, price, neighbourhood assignment (FR-22), and listing type (FR-25)
**When** the metrics/enrichment pipeline stage runs (AD-10 — computed in the pipeline, no read-time re-derivation)
**Then** each Property's percentile is computed on a single price basis defined in that stage, cohort-keyed **neighbourhood × listing type**, and persisted via the single enrichment write authority
**And** dual rent/sale Properties get a percentile per listing type (FR-25 semantics)

**Given** a cohort smaller than the config-owned min-cohort size (`AppConfig` — AD-2, no hardcoded threshold)
**When** percentiles are computed
**Then** the percentile for that Property is suppressed (null), never computed on a meaningless cohort (counter-metric: signal noise)
**And** properties with missing area or unassigned neighbourhood are skipped with a null percentile, not defaulted

**Given** this changes brownfield enrichment/projection SQL and schema
**When** the story completes
**Then** a characterization test locks the existing projection behavior before the change, the Alembic migration passes `alembic check`, and the API image is rebuilt before backend validation (testing rules)
**And** percentile math has TDD unit coverage in `src/core/`/metrics (boundaries: cohort exactly at min size, single-listing cohorts, ties)

### Story 2.2: Percentile on card/modal + percentile filter

As a user scanning the grid,
I want the price/m² percentile visible on property cards and the detail modal, and filterable,
So that I can shortlist statistically cheap properties in one pass (FR-30; UJ-1).

**Acceptance Criteria:**

**Given** stored percentiles from Story 2.1
**When** the property grid/modal renders
**Then** the percentile comes from the canonical AD-12 projection (one API-owned DTO — no parallel flattener) and displays on card and modal for the primary listing (respecting `utils/primaryListing.ts` for dual-type Properties)
**And** suppressed (null) percentiles render as absent — no fake "50th percentile" placeholder

**Given** the filter bar
**When** I set a percentile filter (e.g. "≤ 25th percentile in cohort")
**Then** the API filters server-side on the stored value and the grid updates; the filter round-trips through the existing filters state hooks
**And** filtering respects `price_type`/listing-type semantics (BIN-77 lesson — no cross-type leakage)

**Given** contract and i18n obligations
**When** the story completes
**Then** `src/api/schemas.py` + contract tests cover the projection/filter change (percentile as float, nullable), new strings land in `en` + `pt-BR` catalogs (NFR-7)
**And** a Playwright e2e covers percentile display + filter happy path

### Story 2.3: Saved-search new-match detection on the pipeline

As a user with saved searches,
I want the pipeline to detect when a newly created Property matches one of my notification-enabled saved searches,
So that new deals reach me without re-running my filters every evening (FR-32; UJ-2).

**Acceptance Criteria:**

**Given** a saved search (`src/api/saved_searches.py` / existing model) with new-match notifications enabled
**When** the scrape → normalize → dedupe → persist path creates a **new** Property matching the search's criteria
**Then** a notification is emitted through Celery + the single notifier preference registry (AD-9 — no new channel work, no second notifier path), owned by the single principal model (AD-11, nullable owner)
**And** matching runs read-only against Property/Listing fields — no writes outside the dedupe/persist authority (AD-3)

**Given** noise control
**When** matches are evaluated
**Then** only genuinely new Properties fire (a re-scraped or price-updated existing Property does not), each search × property pair notifies at most once (dedupe on delivery), and a disabled search never fires
**And** a platform circuit-break or scrape failure produces no spurious "new match" noise

**Given** schema and glue obligations
**When** the story completes
**Then** the subscription flag/migration passes `alembic check`; matcher logic has TDD unit coverage in `src/core/`-tier code (match/no-match/threshold/disabled branches) with no new `core` → `adapters` leaks (AD-1)
**And** the Celery task wrapper gets one happy-path and one error-path test (thin-glue tier)

### Story 2.4: Saved-search alert management UI

As a user managing saved searches,
I want to toggle new-match notifications per saved search and see which are alerting,
So that I control alert volume per search instead of all-or-nothing (FR-32).

**Acceptance Criteria:**

**Given** the subscription capability from Story 2.3
**When** I view my saved searches in the frontend
**Then** each shows a notify-on-new-match toggle whose state round-trips through the saved-searches API (AD-8 — API only, no direct infra access)
**And** toggling is immediate, surfaced errors are non-blocking toasts, and the alert state is visible at a glance in the list

**Given** contract and i18n obligations
**When** the story completes
**Then** the saved-searches API schema change is covered by contract tests, new strings land in `en` + `pt-BR` catalogs (NFR-7)
**And** a Playwright e2e covers toggle-on → state persists after reload
