---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
status: complete
completed: 2026-08-05
refresh: >
  UX-contract refresh (2026-08-05, second pass): folding the finalized UX design
  contract (DESIGN.md + EXPERIENCE.md, merged a9058a7) into this set in place —
  story keys and sequencing gates preserved. The original v0.13 set completed all
  four workflow steps earlier the same day, pre-UX-contract.
originalCompleted: 2026-08-05
tracking: >
  BMad artifacts are the SOLE tracker (ADR 0005, 2026-08-05 — Linear dropped entirely;
  the partial v0.13 sync BIN-273/274/275 + milestone was canceled/abandoned in Linear).
  This document is the plan of record; execution status lives in
  _bmad-output/implementation-artifacts/sprint-status.yaml. Story ids: v0.13-s1.1 …
  v0.13-s1.6 (Epic 1), v0.13-s2.1 … v0.13-s2.5 (Epic 2; s2.5 minted at the 2026-08-05
  UX-contract refresh) — used for branch names (feat/v0.13-sN.M-…) and feature docs.
  sprint-status.yaml uses BMad-STANDARD keys (epic-N, N-M-slug — what bmad-loop
  parses; decided 2026-08-05, do NOT regenerate v0.13-prefixed yaml keys); yaml
  story N-M ↔ story id v0.13-sN.M. Delivered pre-v0.13 epics are archived in
  sprint-status-archive-pre-v0.13.yaml, never resurrected into the live tracker.
  Sequencing gates: s1.2←s1.1, s1.3←s1.1, s1.4←s1.1, s1.5←s1.3,
  s1.6←s1.4+s1.5, s2.2←s2.1, s2.3←s2.1, s2.4←s2.3, s2.5←s2.2.
  RETROSPECTIVE AMENDMENT (2026-08-12, epic-1 retro): Epic 3 minted
  (s3.1…s3.4 — FR-28's unmet stated outcome + the corpus-integrity ledger
  items Epic 1's reviews fenced out of their own stories), and s2.6 minted as
  Epic 2's UX foundation piece. Added gates: s3.4←s3.3, s2.2←s2.6, s2.4←s2.6,
  s2.5←s2.6, s2.1←s3.2+s3.3+s3.4. Wave order: s3.1 → (s3.2 ∥ s3.3) → s3.4;
  s2.6 parallel with any of them; Epic 2 proper last. Retrospective action
  items are tracked as `epic-1-retro-item-N-<slug>` keys in sprint-status
  (bmad-loop's RETRO_ITEM_RE shape) — see _bmad/custom/bmad-retrospective.toml.
inputDocuments:
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-08-05/prd.md'
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-08-05/addendum.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/COMPANION-architecture-delta.md'
  - '_bmad-output/planning-artifacts/sprint-change-proposal-2026-08-05.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/EXPERIENCE.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/review-adversarial-ux.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/review-ptbr-microcopy.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/validation-report.md'
excludedDocuments:
  - 'epics-delivered-2026-07-27.md (historical Epics 1–5 record — fresh set, not an extension)'
supersedes: 'epics-delivered-2026-07-27.md (Epics 1–5, BIN-19…23, delivered)'
planningTarget: 'v0.13'
created: 2026-08-05
---

# imoveis - Epic Breakdown (v0.13)

## Overview

This document provides the complete epic and story breakdown for **imoveis v0.13**, decomposing the requirements from the PRD (2026-08-05), its addendum, and the Architecture Spine (updated 2026-08-05) into implementable stories. The prior epic set (Epics 1–5, delivered 2026-07-27 as BIN-19…23) is archived at `epics-delivered-2026-07-27.md`; this is a fresh set, not an extension.

**UX-contract refresh (2026-08-05, second pass):** the original set was minted before the UX design contract existed. This refresh folds `ux-designs/ux-imoveis-2026-08-05/` (DESIGN.md + EXPERIENCE.md) in as a first-class input — per the PRD ("v0.13 UI stories consume it") — updating NFR text that had drifted (NFR-5 local gate, NFR-7 pt-BR default), FR-32's UX refinements, and adding the UX Design Requirements section. FR-33–FR-38 (UX-driven backend scope) stay scheduled as the v0.14 wave and are **not** pulled into this set.

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

FR-32: Saved-search new-match alerts. A saved search can notify when a **new** Property matching it appears — extending alerts beyond watched-property price drops. Reuses the shipped notifier registry (FR-21) and saved searches (FR-14); no new channel work for v1. **UX refinements (2026-08-05 contract, binding):** new-match alerts fire only once verdict/percentile enrichment exists (an alert click always lands decidable); the drop-alert threshold lives per saved search/watch, beside its notify toggle — no global setting — and every alert email states the threshold that fired it; channel posture is email (guaranteed interrupt) + in-app + desktop push (opportunistic) — no Telegram; email new-match alerts batch into one daily window per search, and the weekly digest excludes already-alerted Properties.

**Theme B cut (decided at epics time, 2026-08-05):** FR-30 + FR-32 are in; **FR-31 (total-cost-of-occupancy normalization) is deferred** — it carries the worst data-availability risk (partial platform fee coverage, PRD §9 Q2), and the v0.13 success metric requires ≥1 Theme B FR; the chosen pair ships two with bounded risk. FR-31 stays on the debt ledger for a later wave.

**FR-28 surface decision (PRD §9 Q1, decided at epics time):** admin-panel exposure **is** the v0.13 target, built as slices — hardened runner control core (lease, pause/resume semantics) first, then auth-gated admin API + panel visibility/control, with FR-29 telemetry landing independently. A CLI-only cut remains the fallback slice if the wave must shrink.

### NonFunctional Requirements

NFR-1: Local-first with bounded cloud assist — core enrichment and storage run on operator hardware; no *required* cloud AI. Sanctioned exception: the quota-bounded, operator-triggered, batch-only cloud-assist path (Gemini/Gemma free tier) may accelerate backfill, never gate core function; the local path is never removed.

NFR-2: Config discipline — runtime settings via `AppConfig` / `configs/app_config.yaml` (+ env), never scattered `os.getenv` in feature code.

NFR-3: Security — no hardcoded production secrets; `imoveis_secret` / `dev-secret-key` forbidden in repo; admin routes require API key when configured; cloud API keys via env only.

NFR-4: Resilience — circuit breakers and checkpoints keep scrapes operable under partial platform failure; quota exhaustion degrades to local enrichment, not outage.

NFR-5: Testability — merge requires a green **local gate**: `scripts/agent/validate.sh all` (lint, unit, integration, contract, scrapers live gate, e2e, security) run by `finish-feature.sh`, the only path to `main` (validate → squash-merge → push). Validation runs against the ephemeral test stack and never touches the primary compose project — safe during a live backfill. GitHub Actions is docs deploy + nightly scraper drift canary only. *(Rewritten post-v0.13-fu1; gate contents preserved unchanged across the SoR pivot.)*

NFR-6: Observability — pipeline telemetry and system health support unattended operation; extended in v0.13 to enrichment coverage and backfill pacing (FR-29). Coverage is a first-class SLO on the front-door health strip (coverage % = minimum across signal types), with per-signal-type detail in Operações (UX contract, resolves old Q4).

NFR-7: i18n — **pt-BR is the UI default** (UX contract 2026-08-05, superseding the earlier "English default"); the engineering rule is unchanged: every string lands in both `en` and `pt-BR` catalogs, locale switchable via preference (`ui.locale` / Redis); canonical DB/API wire values remain English.

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
- **Backfill vs primary-maintenance collision *(updated post-v0.13-fu1)*:** validation is now primary-safe (ephemeral test stack) — a live backfill and a validate/finish cycle no longer collide. The remaining guarded operation is `migrate-primary.sh`, which refuses while the backfill heartbeat (`backfill:gemma:active`) is alive. FR-28's visibility rationale stands on its own: an active backfill is a visible product surface (front-door chip + Operações card), not tribal knowledge; the UI warning line is a reminder, the shell-side heartbeat is the real guard.
- **Harness-track gate (process, not an FR): DONE** — landed 2026-08-05 as `v0.13-fu1` (main `8f5d885` + `f2da788`) before story execution, as gated.
- **Validation gates:** API schema changes update/run `src/tests/contract/`; DB schema changes run `alembic check`; AI prompt/client changes run `validate-ai.sh`; all merges through `finish-feature.sh` (local `validate.sh all` gate).

### UX Design Requirements

Extracted from the UX design contract `ux-designs/ux-imoveis-2026-08-05/` (DESIGN.md = visual identity/tokens; EXPERIENCE.md = IA/behavior/states; finalized 2026-08-05 — the three review docs' findings are already folded into the spines). Scope note: only requirements binding **v0.13 surfaces** (FR-28/29/30/32 UI) are extracted as UX-DRs; UX-driven scope beyond that is FR-33–FR-38, scheduled as the v0.14 wave. Spine wins on conflict with mockups.

**Foundation (bind every v0.13 UI story):**

UX-DR1: Meia-noite design tokens. All new v0.13 UI adopts the DESIGN.md frontmatter token set — colors (incl. blend variants like `price-drop-tint-12/35`, `surface-health-chip`), the two type families (serif reserved for price + neighbourhood name only; sans everything else), tabular numerals for all numbers, radii scale (no pills), 4-based spacing. Dark-only; no light theme.

UX-DR2: pt-BR-default UI. New surfaces render pt-BR by default (NFR-7 as amended); every string still lands in both `en` and `pt-BR` catalogs; wire enums/DB values stay English. Vocabulary: "coleta" for a scrape run on every user-facing surface ("run" only in code/wire); the admin surface is named **Operações** in nav.

UX-DR3: Honest-absence + no-meters discipline. Progress bars are banned everywhere — coverage and backfill speak in text numbers and dates; no blocking spinners over content; null/missing renders as **absent** (no fake percentile, no fabricated ETA/throughput when no run is active); API errors and conflicts surface as non-blocking toasts (bottom-anchored, max two stacked, per the DESIGN.md toast spec).

UX-DR4: Detail-surface posture. There are no centered modals in the system: the detail surface is a right-side **panel** over a partial scrim (grid dims, map rail stays visible), one level deep, `Esc` closes; the persistence contract holds — map viewport, grid scroll, and filter state survive refreshes and panel open/close. **Decided (Felipe, 2026-08-05): v0.13 adopts the side panel** — s2.2 renders percentile in the new detail side panel per the contract (the modal→panel migration lands in v0.13 since s2.2 touches that surface anyway; no throwaway modal work).

**Operações / Epic 1 surfaces (FR-28, FR-29 — story 1.6):**

UX-DR5: Backfill card (Operações). States render pt-BR — `inativo / em execução / pausado / em espera (limite da API)` (wire enum stays `idle/running/paused/backing-off`); today's budget use, throughput, and **day-scale ETA** as tabular text lines, simply absent with no active run; start/pause/resume controls; a lease-conflict on start surfaces as a toast **naming the active run**; while running, a persistent warning line in `health-warn` with a warning glyph (collision reminder — the real guard is the shell-side heartbeat `backfill:gemma:active`). Visual spec: `surface-card`, hairline border, default radius; no bars.

UX-DR6: Coverage display. Per-signal-type coverage breakout in Operações (visual, sentiment, valuation, embeddings) as text percentages only — no tracks, no bars (FR-29).

UX-DR7: Front-door visibility slice (health strip). An active backfill is operator-visible **always** (AD-13): the Painel health strip carries a backfill chip with the warning glyph while running, and coverage as text — `Cobertura de IA 82%` — where the number is the **minimum across signal types**, labeled as such on hover; per-type detail lives in Operações. *(v0.13 slice of the health strip only; per-scraper cadence/anomaly/calibrating chip semantics are FR-37, v0.14.)*

**Epic 2 surfaces (FR-30 — stories 2.1/2.2):**

UX-DR8: Percentile microcopy hard rules. Badge form: `entre os 25% mais baratos` — the word *barato* appears on the badge itself; sentence form (detail surface): `entre os 25% mais baratos do bairro`, and on dual-type Properties the sentence names the cohort type (`…dos aluguéis do bairro` / `…das vendas do bairro`). Never statistician notation (`P25`, "percentil", `≤`); every phrasing makes lower-price-is-better explicit; cohort language mirrors neighbourhood × listing type.

UX-DR9: Percentile badge visual. Compact chip: `price-drop` ink on `price-drop-tint-12` background with `price-drop-tint-35` border, small radius, right-aligned on the serif price line of the card; **absent entirely** when suppressed (small cohort / missing data) — never a placeholder.

UX-DR10: Percentile filter control. A `Preço no bairro` select in the Filtros panel — `entre os 25% mais baratos` / `entre os 50% mais baratos` / `qualquer preço` (default); the active value renders as **one chip** composing under the filter bar's hard 2-line ceiling; cohorts are per listing type — switching tipo re-evaluates against that type's cohort (BIN-77 no-cross-type-leakage).

**Epic 2 surfaces (FR-32 — stories 2.3/2.4):**

UX-DR11: Enrichment-gated alerts. New-match alerts fire only once verdict **and** percentile exist for the Property — an alert click always lands on a decidable detail surface, never `análise de IA pendente` (FR-32 refinement; resolves the J2 async race).

UX-DR12: Channel posture + batching. Email is the guaranteed interrupt channel; in-app (Alertas) and desktop push are opportunistic; **no Telegram**. Email new-match alerts batch into one daily window per search; the weekly digest excludes already-alerted Properties (no double delivery). **Decided (Felipe, 2026-08-05): v0.13 ships email-only v1** through the shipped notifier registry (honoring FR-32's "no new channel work"); the in-app Alertas bell/panel and desktop push are v0.14 surfaces. Enrichment gating (UX-DR11) and batching/threshold-statement rules apply to the email channel now.

UX-DR13: Saved-search row (Buscas salvas). `surface-card` rows with hairline separators; search name in body type, filter summary in meta type; per-search notify-on-new-match toggle **plus inline minimum-drop threshold value** (accent when interactive); alert state visible at a glance. No global threshold setting; every alert email states the threshold that fired it (`queda de R$ 240 — seu mínimo: R$ 100`).

### FR Coverage Map

FR-1–FR-26: Shipped baseline (v0.1–v0.12) — no epic in this set; definition of record in `docs/features/`.
FR-27: Epic 1 — first-class multi-backend enrichment routing (task-class map, startup validation, local fallback).
FR-28: Epic 1 — quota-governed cloud backfill as an operator surface (hardened runner control + admin API/panel).
FR-29: Epic 1 — enrichment coverage telemetry (DB-derived coverage, throughput, ETA).
FR-30: Epic 2 — price-per-m² percentile views (pipeline-computed cohort stats → projection → card + detail side panel + filter).
FR-31: **Deferred (not covered in v0.13)** — worst data-availability risk; stays on the debt ledger.
FR-32: Epic 2 — saved-search new-match alerts, email-only v1 (enrichment-gated matcher on the pipeline, notifier registry delivery, per-search toggle + threshold UI).

## Epic List

### Epic 1: Hybrid Enrichment, Productized (Theme A)

Felipe (operator) runs the cloud/local AI-enrichment split as a sanctioned, observable product capability instead of operator folklore: per-task-class backend routing validated at startup, a quota-governed cloud backfill he can start/pause/resume from the **Operações** surface and leave unattended for its multi-day run, and DB-derived coverage telemetry showing % enriched, throughput, and a credible ETA. An active backfill is visible from the front door: the Painel health strip carries the backfill chip (warning glyph while running) and `Cobertura de IA` % (minimum across signal types) — the UX contract's v0.13 health-strip slice (per-scraper chip semantics stay v0.14/FR-37). Cloud stays optional — with no key or exhausted quota, everything degrades to local Ollama without intervention. Realizes UJ-3, UJ-4.

**FRs covered:** FR-27, FR-28, FR-29
**NFRs in play:** NFR-1, NFR-2, NFR-3, NFR-4, NFR-6
**Governed by:** AD-13, AD-2, AD-4, AD-6, AD-8, AD-10, AD-12 (coverage projection); canonical task-class enum convention; UX-DR1–3 (tokens, pt-BR/Operações naming, honest absence), UX-DR5–7 (backfill card, coverage display, front-door slice)

### Epic 2: Deal-Intelligence Deepening (Theme B cut)

Ana and Bruno (users) get sharper deal signals than one combined score: every property card and the **detail side panel** show where its price/m² falls within its neighbourhood × listing-type cohort (filterable, suppressed on too-small cohorts), and saved searches notify by **email** when a **new** matching property appears — already enriched, so the alert click lands decidable. The modal→side-panel migration is in this epic (decided 2026-08-05): the detail surface becomes the contract's right-side panel (partial scrim, map rail visible, persistence contract) via a dedicated story (s2.5) that consumes s2.2's percentile projection — s2.2 stays grid-only so neither story depends on a later one. FR-32 ships email-only v1 through the shipped notifier registry; the Alertas panel and desktop push are v0.14 surfaces. Realizes UJ-1, UJ-2.

**FRs covered:** FR-30, FR-32
**NFRs in play:** NFR-6, NFR-7, NFR-8
**Governed by:** AD-10 (cohort stats in pipeline stage), AD-12 (read-only projection), AD-3, AD-8, AD-9 (one notifier registry), AD-11 (principal model); UX-DR1–4 (tokens, pt-BR, honest absence, side-panel posture), UX-DR8–13 (percentile copy/badge/filter, enrichment-gated email alerts, saved-search row)

### Epic 3: Enrichment Hardening & Operability

*(Minted 2026-08-12 at the Epic 1 retrospective.)* Felipe (operator) can actually run the cloud backfill from the surface Epic 1 built for it, and trust what it wrote: the runner gets a committed, supervised home so the admin Start button stops depending on a hand-started dev script; a systemic AI-client failure stops fabricating a `0.5` score and permanently retiring the row; the daily budget counts the requests the provider counts; and a displaced runner stops rewinding its successor's checkpoint. Not new scope — FR-28's unmet stated outcome plus the corpus-integrity items Epic 1's review passes found and correctly fenced out of their own stories' intent contracts.

**FRs covered:** FR-28 (stated outcome), FR-27/FR-29 (hardening)
**NFRs in play:** NFR-1, NFR-3, NFR-4, NFR-6
**Governed by:** AD-13, AD-4, AD-10, AD-1, AD-6; local-first / residential-IP topology invariants
**Ledger drained:** DW-27, DW-17, DW-18, DW-11

**Epic dependencies:** Epic 1 (closed) and Epic 2 touch disjoint surfaces — metrics/alerts/UI vs AI-routing/backfill/telemetry — and shared no core files. **Epic 3 gates Epic 2**: stories 3.2/3.3/3.4 govern what the enrichment pipeline writes, and Epic 2 computes price/m² percentiles over that corpus, so s2.1 must not run while fabricated scores are still accruing. Within Epic 1, the canonical task-class enum story was the foundation. Within Epic 3, 3.1 is independent of 3.2–3.4 (hosting vs runner internals) but must not run concurrently with them; 3.4←3.3 (shared `backfill_runner.py`). Within Epic 2, s2.6 is the UX foundation piece and s2.1 the data foundation; the side-panel migration (s2.5) consumes s2.2's projection and s2.3's enrichment gating consumes s2.1's percentile capability (gates: s2.2←s2.1+s2.6, s2.3←s2.1, s2.4←s2.3+s2.6, s2.5←s2.2+s2.6, s2.1←s3.2+s3.3+s3.4).

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

**Given** that primary-DB maintenance is guarded by the backfill heartbeat (post-v0.13-fu1: validation is primary-safe on the ephemeral test stack; `migrate-primary.sh` refuses while `backfill:gemma:active` is alive)
**When** a backfill is active
**Then** its status is visible via the status endpoint (and surfaced in Story 1.6's UI) so an active run is a visible product surface, not tribal knowledge
**And** admin actions are recorded in the `admin_audit` trail (AD-6)

**Given** this adds admin API schema
**When** the story completes
**Then** contract tests cover the new endpoints; unit tests mock the runner/lease (thin-glue tier: one happy path + one conflict/error path per endpoint)
**And** rate-limited-route unit tests bypass slowapi Redis per testing rules

### Story 1.6: Operações — backfill card, coverage display, front-door visibility

As the operator,
I want the Operações surface to show the backfill card and per-signal coverage per the UX contract, with the active backfill visible from the front-door health strip,
So that I can kick off, monitor, and pause the multi-day run and watch coverage climb without touching a terminal (FR-28, FR-29; UJ-4 climax; UX-DR5–7).

**Acceptance Criteria:**

**Given** the APIs from Stories 1.4 and 1.5
**When** I open Operações (`frontend/`, talking only to the FastAPI surface — AD-8; nav label **Operações** — UX-DR2)
**Then** the backfill card renders per UX-DR5: state in pt-BR (`inativo / em execução / pausado / em espera (limite da API)`; the wire enum stays `idle/running/paused/backing-off`), today's budget use, throughput, and **day-scale ETA** as tabular text lines — absent when there is no active run (UX-DR3: no fabricated values, no bars) — plus start/pause/resume controls wired to the admin API
**And** a lease conflict on start surfaces as a non-blocking toast **naming the active run**; while running, the card carries a persistent `health-warn` warning line with glyph (the shell-side heartbeat remains the real guard)

**Given** coverage data from Story 1.4
**When** Operações renders coverage
**Then** per-signal-type coverage (visual, sentiment, valuation, embeddings) renders as text percentages only — no tracks, no bars (UX-DR6) — and absent data renders absent

**Given** the Painel front door
**When** a backfill is active (and whenever coverage exists)
**Then** the health strip carries a backfill chip with the warning glyph while running (AD-13 — operator-visible always) and `Cobertura de IA N%` as text, where N is the **minimum across signal types**, labeled as such on hover (UX-DR7; per-scraper chip semantics stay v0.14/FR-37)

**Given** the visual contract and product i18n
**When** the story completes
**Then** new components use the Meia-noite tokens (UX-DR1, dark-only), all new strings land in both `en` and `pt-BR` catalogs, and the UI default locale flips to **pt-BR** (NFR-7 as amended; `ui.locale` preference still switches)
**And** a Playwright e2e covers the card's happy path (status render + a control action against a mocked/stubbed API) and asserts honest absence (no ETA/throughput text with no active run)

### Epic 1 close + post-epic sequencing (retrospective, 2026-08-12)

Epic 1 closed with all six stories delivered, merged and pushed. Its retrospective (`_bmad-output/implementation-artifacts/epic-1-retro-2026-08-12.md`) found that FR-28's acceptance criteria were all met while its **stated outcome** — graduating the runner out of `scripts/dev` — was not, and that the deferred-work ledger closed 7 items while opening 32, three of them with corpus-integrity consequences.

That remediation is **Epic 3** (below), not a set of follow-up keys: each item needs its own spec, acceptance criteria and review pass, which is what a story is for. The one frontend item is **Story 2.6**, owned by the epic that consumes it.

**Wave order (recorded here so future sessions do not re-derive it):**

- **Wave A:** `3.1` (runner hosting) — serial, first.
- **Wave B:** `3.2` ∥ `3.3`, then `3.4`.
- **Wave C:** `2.6` — frontend-only, parallel with A or B.
- **Wave D:** Epic 2 Wave 1 (`2.1`), then the rest of Epic 2.

**Gates:** `3.4←3.3` (shared `src/core/backfill_runner.py`); `2.2←2.6`, `2.4←2.6`, `2.5←2.6`; `2.1←3.2+3.3+3.4` (Epic 2 computes percentiles over a corpus that must not be accruing fabricated scores while it does so).

**Do not parallelize:** `3.3` with `3.4` (same runner file); `3.1` with `3.2`/`3.3` (a hosting change that moves the runner's entrypoint while its internals are being rewritten); any Epic 2 UI story before `2.6` (they would pin further e2e assertions on top of the wrong pt-BR strings).

## Epic 2: Deal-Intelligence Deepening (Theme B cut)

Ana and Bruno (users) get sharper deal signals than one combined score: price/m² percentile within the neighbourhood × listing-type cohort on every card and in the detail side panel, with filtering (FR-30), and saved searches that notify by email when a new matching Property appears — already enriched, so the alert lands decidable (FR-32, email-only v1). The modal→side-panel migration is this epic's UX foundation piece (s2.5). Both FRs consume shipped foundations (polygons, dual-type scoring, saved searches, notifier registry) — no new geo or channel work.

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
**Then** a characterization test locks the existing projection behavior before the change, and the Alembic migration passes `alembic check` (runs against the ephemeral test DB inside `validate.sh backend`; no API-image rebuild is needed for validation — rebuild `api` only to run the app after `src/api/` changes)
**And** percentile math has TDD unit coverage in `src/core/`/metrics (boundaries: cohort exactly at min size, single-listing cohorts, ties)

### Story 2.2: Percentile badge on cards + percentile filter

As a user scanning the grid,
I want the price/m² percentile visible on property cards as the contract's badge, and filterable via the `Preço no bairro` control,
So that I can shortlist statistically cheap properties in one pass (FR-30; UJ-1; UX-DR8–10).

**Acceptance Criteria:**

**Given** stored percentiles from Story 2.1
**When** the property grid renders
**Then** the percentile comes from the canonical AD-12 projection (one API-owned DTO — no parallel flattener) and renders on the card as the contract's badge — `entre os N% mais baratos`, the word *barato* on the badge itself, never `P25`/"percentil"/`≤` (UX-DR8) — right-aligned on the serif price line, `price-drop` ink on `price-drop-tint-12` background with `price-drop-tint-35` border (UX-DR9), for the primary listing (respecting `utils/primaryListing.ts` on dual-type Properties)
**And** suppressed (null) percentiles render as **absent** — no placeholder, no fake value (UX-DR3/9)

**Given** the Filtros panel
**When** I set the `Preço no bairro` filter (`entre os 25% mais baratos` / `entre os 50% mais baratos` / `qualquer preço` default — UX-DR10)
**Then** the API filters server-side on the stored value, the grid updates, and the active value renders as **one chip** composing under the filter bar's 2-line ceiling; the filter round-trips through the existing filters state hooks
**And** cohorts are per listing type — switching tipo re-evaluates against that type's cohort, respecting `price_type` semantics (BIN-77 lesson — no cross-type leakage)

**Given** contract, visual, and i18n obligations
**When** the story completes
**Then** `src/api/schemas.py` + contract tests cover the projection/filter change (percentile as float, nullable), new components use the Meia-noite tokens (UX-DR1), and new strings land in `en` + `pt-BR` catalogs (NFR-7)
**And** a Playwright e2e covers badge display + filter happy path, and asserts the badge is absent for a suppressed-percentile Property

### Story 2.3: Saved-search new-match detection on the pipeline

As a user with saved searches,
I want the pipeline to detect when a newly created Property matches one of my notification-enabled saved searches,
So that new deals reach me without re-running my filters every evening (FR-32; UJ-2).

**Acceptance Criteria:**

**Given** a saved search (`src/api/saved_searches.py` / existing model) with new-match notifications enabled
**When** the scrape → normalize → dedupe → persist path creates a **new** Property matching the search's criteria
**Then** a notification is emitted through Celery + the single notifier preference registry on the **email channel only** (v1 — UX-DR12; AD-9 — no new channel work, no second notifier path), owned by the single principal model (AD-11, nullable owner)
**And** matching runs read-only against Property/Listing fields — no writes outside the dedupe/persist authority (AD-3)

**Given** enrichment gating (UX-DR11)
**When** a new Property matches but is not yet decidable
**Then** the alert is **held until enrichment completes** — it fires only once the verdict is present and the percentile has been evaluated (a value or a suppressed-null both count as evaluated) — never dropped, and never sent pointing at an `análise de IA pendente` surface (requires Story 2.1's percentile capability — gate s2.3←s2.1)

**Given** noise control
**When** matches are evaluated and delivered
**Then** only genuinely new Properties fire (a re-scraped or price-updated existing Property does not), each search × property pair notifies at most once (dedupe on delivery), and a disabled search never fires
**And** email new-match alerts batch into **one daily window per search**, the weekly digest excludes already-alerted Properties (no double delivery — UX-DR12), and a platform circuit-break or scrape failure produces no spurious "new match" noise

**Given** schema and glue obligations
**When** the story completes
**Then** the subscription flag/migration passes `alembic check`; matcher logic has TDD unit coverage in `src/core/`-tier code (match/no-match/threshold/disabled branches) with no new `core` → `adapters` leaks (AD-1)
**And** the Celery task wrapper gets one happy-path and one error-path test (thin-glue tier)

### Story 2.4: Saved-search alert management UI

As a user managing saved searches,
I want to toggle new-match notifications and set a minimum-drop threshold per saved search, and see which are alerting,
So that I control alert volume per search instead of all-or-nothing (FR-32; UX-DR13).

**Acceptance Criteria:**

**Given** the subscription capability from Story 2.3
**When** I view my saved searches (Buscas salvas)
**Then** each row shows a notify-on-new-match toggle **and an inline minimum-drop threshold value** whose states round-trip through the saved-searches API (AD-8 — API only, no direct infra access); the threshold lives per saved search — no global setting (UX-DR13; small migration for the per-search threshold, `alembic check` passes)
**And** toggling is immediate, surfaced errors are non-blocking toasts, and the alert state is visible at a glance in the list

**Given** a drop alert fires for a search
**When** the alert email is delivered
**Then** it states the threshold that fired it (`queda de R$ 240 — seu mínimo: R$ 100` — UX-DR13), so even a default threshold is visible and correctable

**Given** contract, visual, and i18n obligations
**When** the story completes
**Then** the saved-searches API schema change is covered by contract tests, rows follow the contract's saved-search-row spec with Meia-noite tokens (UX-DR1/13: `surface-card` rows, hairline separators, filter summary in meta type, accent on interactive values), and new strings land in `en` + `pt-BR` catalogs (NFR-7)
**And** a Playwright e2e covers toggle-on + threshold edit → state persists after reload

### Story 2.5: Detail side panel — modal migration + percentile sentence

As a user opening a property,
I want the detail surface to be the contract's right-side panel with the percentile stated in plain language,
So that I can judge a property with the map still in view and never lose my place in the grid (UX-DR4, UX-DR8; UJ-1).

**Acceptance Criteria:**

**Given** the existing detail modal and the percentile projection from Story 2.2 (gate s2.5←s2.2)
**When** I open a property from a card
**Then** the detail renders as a right-side **panel** over a **partial** scrim — the grid dims, the map rail stays visible — one level deep, closable with `Esc` (UX-DR4), and the centered modal is retired (no dead modal code left behind)
**And** the panel carries today's modal content (photos, verdict, price-history chart, per-platform comparison) restyled with the Meia-noite tokens (UX-DR1), plus the percentile **sentence** — `entre os N% mais baratos do bairro`, and on dual-type Properties the sentence names the cohort type (`…dos aluguéis do bairro` / `…das vendas do bairro` — UX-DR8)

**Given** the persistence contract (UX-DR4)
**When** the panel opens and closes, including across data refreshes
**Then** the map viewport, grid scroll position, and filter state are all preserved — closing the panel never loses my place
**And** a suppressed percentile renders as **absent** in the panel too — no placeholder sentence (UX-DR3)

**Given** i18n and regression obligations
**When** the story completes
**Then** new strings land in `en` + `pt-BR` catalogs (NFR-7) and existing modal-dependent e2e specs are migrated to the panel, not deleted
**And** a Playwright e2e covers open → `Esc`-close → grid scroll preserved, plus the percentile sentence on a dual-type Property

### Story 2.6: UI contract debt — toast anchoring + pt-BR plural agreement

*(Minted 2026-08-12 at the Epic 1 retrospective. Epic 2's UX foundation piece — it gates 2.2, 2.4 and 2.5, which all add pt-BR strings and toast surfaces on top of it. Numbered last, sequenced first.)*

As a user of any surface in the product,
I want toasts to appear where the design contract says and Portuguese counts to agree with their nouns,
So that Epic 2's new surfaces build on a correct foundation instead of inheriting and re-pinning defects (UX-DR1, UX-DR3).

**Acceptance Criteria:**

**Given** `frontend/src/components/ToastProvider.tsx` is anchored top-right while DESIGN.md's toast spec is bottom-anchored, max two stacked
**When** this story lands
**Then** the shared provider matches the contract (bottom-anchored, max two stacked, per the DESIGN.md toast spec — UX-DR3) and every existing flow that raises a toast is re-verified, not just the new ones
**And** the e2e specs asserting toast position are updated to the contract, and the story-1.6 lease-conflict toast still passes

**Given** the v0.13-s1.6 locale flip promoted pre-existing single-form pt-BR catalog keys from an opt-in preference to **every** user's default
**When** the catalog is swept
**Then** `compareSelected`, `properties.countProperties`, `properties.countFavourited` and `common.bedsShort` model the singular/plural split the catalog already uses elsewhere (`modal.listingCountOne` / `listingCountMany`) — no more `1 selecionados`, `1 imóveis`, `1 favoritos`, `1 quartos`
**And** `compare-select.spec.js`, `compare-map-select.spec.js` and `compare-view.spec.js`, which currently assert the defective strings **verbatim**, are corrected rather than neutralized — the assertions must still pin exact copy

**Given** this is a shared-surface change every later story inherits
**When** the story completes
**Then** `bash scripts/agent/validate.sh all` is green including the full Playwright suite, no new string exists in only one catalog (NFR-7), and no Epic 2 UI story has been started against the old strings

## Epic 3: Enrichment Hardening & Operability

*(Minted 2026-08-12 at the Epic 1 retrospective. Not new scope: this is FR-28's unmet stated outcome plus the corpus-integrity holes Epic 1's review passes found and deliberately fenced out of their own stories' intent contracts.)*

Felipe (operator) can actually run the cloud backfill from the product surface Epic 1 built for it, and trust what it wrote. Story 1.5 shipped a correct control plane whose Start button only works while a hand-started dev script stays alive; stories 1.3–1.6 closed the fabricated-score corruption for provider *quota* refusals only, left the daily budget measuring properties instead of requests, and left a displaced runner able to rewind its successor's checkpoint. Each was correctly deferred — every one is fenced by its origin story's own "Never" clause — and each needs a deliberate design decision rather than a review patch.

**FRs covered:** FR-28 (completing the stated outcome), FR-27/FR-29 (hardening the delivered surface)
**NFRs in play:** NFR-1, NFR-3, NFR-4, NFR-6
**Governed by:** AD-13 (single pacer, one lease, cloud bounded), AD-4/AD-10 (second driver never second writer, no GPU work), AD-1 (no `core` → `adapters` leak), AD-6 (admin surface audited); local-first/residential-IP topology invariants (runner placement)
**Ledger drained:** DW-27, DW-17, DW-18, DW-11

### Story 3.1: Backfill runner hosting — a committed home for the consumer

As the operator,
I want the thing that executes a requested backfill to have a committed, supervised home,
So that the admin Start button is a product surface rather than a request queued into the void (FR-28's stated outcome; DW-27).

**Acceptance Criteria:**

**Given** `POST /admin/backfill/start` only records a request, and nothing consumes it unless a hand-started `scripts/dev/backfill_gemma.py --serve` is alive
**When** this story lands
**Then** the runner has a committed home — a committed systemd unit, a dedicated compose service, or promotion out of `scripts/dev` to a supported entrypoint — and the choice is recorded as an ADR with its rationale
**And** the cloud key placement respects NFR-3 (env-only, never committed) and the local-first / residential-IP invariants are preserved: the runner does not move off-box, and nothing about this change routes scraping or enrichment through a datacenter ASN

**Given** the supervisor is installed
**When** the operator presses Start with no run in flight
**Then** a run begins without any manual host-side step, and `runner_present` reflects reality rather than whether someone remembered to start a script
**And** a supervisor restart (host reboot, `systemctl restart`, container recreate) recovers without operator action and without double-starting under the shared lease (AD-13)

**Given** the primary docker stack is inviolable
**When** the change is delivered
**Then** it introduces no compose action against the primary project in any gate or script, and `validate.sh` / `finish-feature.sh` remain primary-safe
**And** the feature doc records the operator-visible install/upgrade step

### Story 3.2: Non-quota AI failures must not fabricate a score

As the operator,
I want a revoked key, a retired model id or a transport outage to stop the run instead of writing a fabricated score,
So that an unattended multi-day pass cannot silently stamp ~4,600 properties/day with `0.5` and retire them from the candidate set forever (DW-17).

**Acceptance Criteria:**

**Given** `analyze_visuals` / `analyze_text` / `summarize_deal` return `0.5` fallbacks on every exception except a quota error, `run_enrichment` persists and commits that score, and `mode_is_missing_ai` keys on `not score` — so `0.5` is truthy and the row leaves the candidate set permanently
**When** this story lands
**Then** a systemic client failure (401 revoked key, 404 retired model, DNS/proxy outage) no longer results in a persisted score, an advanced checkpoint, or a retired row
**And** the mechanism is a **typed marker on the fallback result** plus a consecutive-fallback circuit breaker in `run_backfill` — never the `analysis == "Error"` string

**Given** the local Ollama path depends on the template fallback (story 1.3's intent contract fenced this deliberately)
**When** a *local* backend fails transiently
**Then** its existing template-fallback behaviour is preserved unchanged — this story changes what happens to the *result*, not the local resilience contract
**And** the quota path delivered by story 1.3 keeps working exactly as it does today

**Given** TDD obligations on `src/core/`
**When** the story completes
**Then** the circuit-breaker state machine has unit coverage (below threshold / at threshold / recovery / interleaved with quota back-off) with no new `core` → `adapters` import, and `bash scripts/agent/validate-ai.sh` passes (AI client surface changed)
**And** a regression test proves a non-quota failure writes no score — failing before the fix

### Story 3.3: The daily budget must count requests, not properties

As the operator,
I want the daily budget to measure what the provider actually counts,
So that AC-1's never-exceed guarantee is about the provider's RPD rather than a proxy that can undercount by an order of magnitude (DW-18).

**Acceptance Criteria:**

**Given** `budget.try_consume(requests_per_property)` charges a flat 3 at launch while one property is up to 3 stages × 3 JSON attempts × 5 HTTP retries — and 429s are in `_RETRY_STATUS`, so the undercount is worst exactly when the account is already throttled
**When** this story lands
**Then** the budget is reconciled against the client's real `request_count` / `retry_count` after each row (a `settle(n)` built on the existing atomic Lua reserve), so the counter tracks requests actually sent
**And** the reservation remains atomic and the rollback path is preserved — story 1.3's `test_backfill_lua_scripts.py` contention guarantees must still hold, re-derived against the new quantity

**Given** `--continuous` decides "RPD spent" from this counter
**When** the meaning of the budget changes
**Then** the back-off / window-roll / stall-detector branches are re-verified against the new semantics, and `backfill.daily_request_budget`'s documented meaning in `configs/app_config.yaml` is updated to say requests, not properties
**And** an existing budget hash written under the old semantics migrates or rolls without handing a run a second day's spend (the hazard `_migrate_start_epoch` was added for)

**Given** TDD on `src/core/`
**When** the story completes
**Then** reconciliation has unit coverage (under, at, and over the cap; a row that retries heavily; a row that fails before sending) and the integration test asserting never-exceed runs against the reconciled counter

### Story 3.4: Checkpoint advance semantics under lease loss

As the operator,
I want a displaced runner's draining rows to stop rewinding its successor's position,
So that a lease handover does not cause re-enrichment of a gap already covered and does not inflate `processed_total` (DW-11).

**Acceptance Criteria:**

**Given** `checkpoint.advance()` is an unconditional `hset` on a key shared by every runner, and in-flight rows always drain by design (cancelling mid-enrichment leaves half-written properties)
**When** this story lands
**Then** a runner that has lost its lease can no longer move `last_property_id` backwards for the successor, and `processed_total` counts each row once
**And** the chosen mechanism — monotonic compare-and-set on the id's ordering, or lease-gated advance — is recorded with its trade-off, because the same call also records genuinely completed work that must not be lost

**Given** story 1.3's drain-after-loss constraint and v0.13-fu7's `_publish` guard
**When** the change lands
**Then** the drain still completes (no cancelled mid-enrichment), and the guard fu7 added for the state key and this story's checkpoint rule express the same handover policy rather than two divergent ones
**And** `src/core/backfill_runner.py` gains no `adapters`/`api` import (AD-1)

**Given** TDD on `src/core/`
**When** the story completes
**Then** unit coverage drives a real handover (owner loses lease mid-drain, successor has advanced past, rows finish) and asserts neither rewind nor double-count, with a regression that fails before the fix
