---
stepsCompleted: ['step-01-document-discovery', 'step-02-prd-analysis', 'step-03-epic-coverage-validation', 'step-04-ux-alignment', 'step-05-epic-quality-review', 'step-06-final-assessment']
documentsIncluded:
  prd:
    - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-08-05/prd.md'
    - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-08-05/addendum.md'
  architecture:
    - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md'
    - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/COMPANION-architecture-delta.md'
  epics:
    - '_bmad-output/planning-artifacts/epics.md'
  ux:
    - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md'
    - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/EXPERIENCE.md'
---

# Implementation Readiness Assessment Report

**Date:** 2026-08-05
**Project:** imoveis

## Document Inventory

### Documents Selected for Assessment

| Type | Document(s) | Notes |
|---|---|---|
| PRD | `prds/prd-imoveis-2026-08-05/prd.md` + `addendum.md` | Current version (v0.13-fu1 + FR-33–FR-38 refresh) |
| Architecture | `architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md` + `COMPANION-architecture-delta.md` | Single version; refreshed 2026-08-05 |
| Epics & Stories | `epics.md` | Plan of record (post UX-contract refresh, 2026-08-05) |
| UX | `ux-designs/ux-imoveis-2026-08-05/DESIGN.md` + `EXPERIENCE.md` | Finalized 2026-08-05 |

### Archive / Context (not assessed as primary inputs)

- `prds/prd-imoveis-2026-07-23/` — prior-cycle PRD (version history, kept)
- `epics-delivered-2026-07-27.md` — delivered-work archive from previous milestone
- `ux-designs/ux-imoveis-2026-08-05/review-*.md`, `validation-report.md` — UX review support docs
- `research/technical-imoveis-local-vs-cloud-hybrid-stack-research-2026-08-05.md` — research context
- `sprint-change-proposal-2026-08-05.md` — change-management record
- `implementation-readiness-report-2026-07-23.md` — historical readiness report

### Duplicate Resolution

- PRD dated versions (2026-07-23 vs 2026-08-05): **2026-08-05 selected**; older folder treated as archive. No whole-vs-sharded conflicts found for any document type.

## PRD Analysis

**Source:** `prds/prd-imoveis-2026-08-05/prd.md` (+ `addendum.md`), status `final`, supersedes 2026-07-23 PRD. FR numbering is global and stable across PRD versions. Baseline = v0.1–v0.12 all shipped; planning target = **v0.13**.

### Functional Requirements

**Baseline (shipped, not re-litigated — definitions of record in superseded PRD / docs/features/):**

- FR-1–FR-3: Pluggable scrapers (v0.1–v0.4 MVP)
- FR-4–FR-6: Dedupe & price history (MVP)
- FR-7–FR-11: Local AI enrichment & scoring (MVP)
- FR-12–FR-15: Discovery UX (MVP)
- FR-16–FR-17: Alerts & operations (MVP)
- FR-18: Side-by-side comparison (v0.5)
- FR-19: Auth/API-key management (v0.5)
- FR-20: Proxy rotation (v0.5)
- FR-21: Export + digest / notifier registry (v0.5)
- FR-22: Neighbourhood polygons (v0.5)
- FR-23: Additional platforms — ZapImóveis first-class scraper (shipped, BIN-127)
- FR-24: Neighbourhood quality profiles (v0.6)
- FR-25: Dual listing-type scoring — rent + sale on one Property (v0.7)
- FR-26: Listing-description enrichment — AI signals from listing text (v0.12)

**v0.13 planned scope (the set this assessment validates):**

- **FR-27: First-class multi-backend enrichment routing** — operator selects enrichment backends per task class via `AppConfig`, documented semantics, startup validation, contract coverage; local Ollama/LM Studio remains default and permanent fallback; cloud never required (NFR-1). Testable consequences: invalid backend/task-class combos fail fast at config load; with cloud unavailable, enrichment degrades to local without operator intervention. Realizes UJ-3, UJ-4.
- **FR-28: Quota-governed cloud backfill as a product surface** — backfill runner graduates from `scripts/dev` to operator-facing: start/pause/resume, progress + pacing visible, safe-by-construction quota use; single Redis pacer (`backfill:gemma`) is the only budget owner (product invariant: never a second quota consumer). Surface decided at epics: admin-panel target, built as slices (runner control core → auth-gated admin API + panel); CLI-only is the fallback slice. Testable consequences: interrupted backfill resumes without re-enriching completed rows; daily requests never exceed budget; `ResourceExhausted` → back-off, not failure. Realizes UJ-4.
- **FR-29: Enrichment coverage telemetry** — per signal type: fraction of Properties enriched, backfill throughput, projected completion date for an active backfill. Coverage figures derive from DB (not runner logs), survive runner restarts. Coverage % joins the front-door health strip (NFR-6). Realizes UJ-3, UJ-4.
- **FR-30: Price-per-m² percentile views** — Property's price/m² percentile within neighbourhood cohort (card/modal, filterable). Assumption: FR-22 polygons + FR-25 dual-type scoring give adequate cohorts; no new geo work. Realizes UJ-1.
- **FR-32: Saved-search new-match alerts** — saved search notifies when a NEW matching Property appears; reuses notifier registry (FR-21) + saved searches (FR-14). UX refinements: fire only once verdict/percentile enrichment exists; drop-alert threshold per saved search; channels = email (guaranteed) + in-app + desktop push (opportunistic), no Telegram. Realizes UJ-2.

**Explicitly deferred / out of v0.13:**

- **FR-31: Total-cost-of-occupancy normalization** — deferred at epics 2026-08-05 (data-availability risk); back on the debt ledger.
- **FR-33–FR-38 (v0.14 wave):** FR-33 recheck/availability verification; FR-34 gone/resurrection lifecycle + favourite-gone alerts; FR-35 personal POI travel-time layer; FR-36 sentiment-dimension filters; FR-37 scraper run-history behavioral analytics; FR-38 recent-filter recall. Epic breakdown deferred to the v0.14 epics pass.

Total FRs: 38 defined globally · **5 in v0.13 assessment scope (FR-27, FR-28, FR-29, FR-30, FR-32)** · 1 deferred (FR-31) · 6 scheduled v0.14 (FR-33–38) · 26 shipped baseline.

### Non-Functional Requirements

- **NFR-1 Local-first with bounded cloud assist:** core enrichment/storage on operator hardware; no required cloud AI; sanctioned exception = quota-bounded, operator-triggered, batch-only Gemini/Gemma free-tier path; local path never removed.
- **NFR-2 Config discipline:** runtime settings via `AppConfig` / `configs/app_config.yaml` (+ env); no scattered `os.getenv`.
- **NFR-3 Security:** no hardcoded production secrets; forbid `imoveis_secret`/`dev-secret-key`; admin routes API-key-gated when configured; cloud API keys via env only.
- **NFR-4 Resilience:** circuit breakers + checkpoints keep scrapes operable under partial platform failure; quota exhaustion degrades to local enrichment, not outage.
- **NFR-5 Testability:** merge requires green local gate — `validate.sh all` run by `finish-feature.sh` (only path to `main`); validation on ephemeral test stack, never touches primary; GitHub Actions = docs deploy + nightly drift canary only.
- **NFR-6 Observability:** telemetry supports unattended operation; extended in v0.13 to enrichment coverage + backfill pacing (FR-29); coverage is a first-class SLO on the health strip (coverage % = minimum across signal types), detail in Admin.
- **NFR-7 i18n:** pt-BR is the UI default (UX contract 2026-08-05, supersedes English default); every string in both `en` and `pt-BR` catalogs; canonical DB/API wire values remain English; locales additive.
- **NFR-8 Geography & tenancy posture:** BH/MG primary geography, opportunistic SP/Campinas; single-tenant personalization (nullable `owner`).

Total NFRs: 8.

### Additional Requirements & Constraints

- **Topology invariants (research, 2026-08-05):** local stack is system of record; scrapers must egress from residential IP; cloud may only hold slim regenerable read-model; Ollama is permanent enrichment fallback; Redis is multi-surface (broker, slowapi, `ui:locale`, `backfill:gemma` pacer).
- **Quota sizing basis (addendum):** Gemma free tier ~30 RPM / 14,400 RPD / 16K TPM best-case; ~3 req/property ⇒ ≈4,600 properties/day ⇒ whole-DB backfill inherently multi-day (~6 days planning basis); exactly one pacer owns the budget.
- **UX contract binding:** v0.13 UI stories must consume `ux-designs/ux-imoveis-2026-08-05/` (DESIGN.md + EXPERIENCE.md) — admin backfill card, coverage telemetry, percentile presentation, saved-search alert toggles. Starred = watched (no separate watchlist surface).
- **Architecture hook:** architecture pass binds cloud-assist path via AD-13 or AD-7 amendment; backfill runner named a sanctioned second driver (AD-4/AD-10 note); AD-1 core→ORM dedupe leak burn-down to verify.
- **Process (done):** harness track landed as v0.13-fu1 before story execution.
- **Non-goals guarding scope:** no multi-tenant SaaS, no required cloud AI, no lift-and-shift to cloud, no multi-city UX in v0.13/v0.14, no export/auth UI (consciously undesigned), no paid-tier planning basis.

### PRD Completeness Assessment

Strong: FRs carry testable consequences (FR-27/28/29 explicitly), UJ traceability (each planned FR names the journeys it realizes), explicit non-goals, decision provenance (dates, deciders, supersessions), and a clean scope fence between v0.13 / v0.14 / deferred. Assumptions are marked inline. The FR-1–17 definitions live in the superseded PRD by design — acceptable, though it means two documents are needed for full baseline traceability. Open question #3 (multi-city) is explicitly parked for v0.13 close — no blocking ambiguity for this wave.

## Epic Coverage Validation

**Source:** `epics.md` (status `complete`, UX-contract refresh 2026-08-05; planningTarget v0.13; 2 epics, 11 stories v0.13-s1.1…s1.6 + v0.13-s2.1…s2.5). The document carries its own FR Coverage Map, a Requirements Inventory restating all v0.13 FRs/NFRs verbatim, and 13 UX-DRs.

### Coverage Matrix

| FR | PRD Requirement | Epic Coverage | Status |
|---|---|---|---|
| FR-27 | Multi-backend enrichment routing (per-task-class, startup validation, local fallback) | Epic 1 — s1.1 (canonical task-class enum + routing config + validator), s1.2 (live pipeline routing + degrade-to-local) | ✓ Covered |
| FR-28 | Quota-governed cloud backfill as product surface (start/pause/resume, lease, single pacer) | Epic 1 — s1.3 (runner control core: lease, pause/resume, safe interruption), s1.5 (admin control API under shared lease), s1.6 (Operações card + controls) | ✓ Covered |
| FR-29 | Enrichment coverage telemetry (DB-derived, throughput, ETA) | Epic 1 — s1.4 (coverage endpoint, DB-derived), s1.6 (coverage display + front-door health-strip slice) | ✓ Covered |
| FR-30 | Price-per-m² percentile views (card/detail, filterable, cohort-suppressed) | Epic 2 — s2.1 (pipeline-computed cohort percentiles), s2.2 (badge + filter), s2.5 (detail side panel percentile sentence) | ✓ Covered |
| FR-32 | Saved-search new-match alerts (enrichment-gated, email-only v1, per-search threshold) | Epic 2 — s2.3 (pipeline new-match detection + gating + batching), s2.4 (alert management UI + threshold) | ✓ Covered |
| FR-31 | Total-cost-of-occupancy normalization | Deferred at epics 2026-08-05 (documented in both PRD §4.4/§6.3 and epics.md) | ⏸ Intentionally deferred — consistent |
| FR-1–FR-26 | Shipped baseline v0.1–v0.12 | No new stories (explicitly listed as shipped baseline in epics.md Requirements Inventory) | ✓ Intentional — consistent |
| FR-33–FR-38 | UX-contract-driven scope | Explicitly excluded from this set; scheduled v0.14 (consistent in PRD §4.5/§6.3 and epics.md refresh note) | ✓ Intentional — consistent |

**FRs in epics but not in PRD:** none. The epics Requirements Inventory restates FR-27/28/29/30/32 essentially verbatim from the PRD (FR-32 carries the same UX refinements, extended with binding delivery detail: daily batch window, digest exclusion, email-only v1 — sourced from the UX contract, not invented).

**NFR traceability (bonus check):** every epic names its NFRs in play (Epic 1: NFR-1/2/3/4/6; Epic 2: NFR-6/7/8). NFR-5 (gate discipline) is process-level and enforced by the harness rather than a story — appropriate. All 8 NFRs restated verbatim in epics.md.

### Missing Requirements

**None.** Every v0.13-scoped FR maps to at least one story; every deferral/exclusion is explicit and consistent between PRD and epics. No orphan FRs in either direction.

### Coverage Statistics

- Total PRD FRs (global numbering): 38
- FRs in v0.13 delivery scope: 5 (FR-27, FR-28, FR-29, FR-30, FR-32)
- FRs covered in epics: 5 of 5 — **100%**
- Intentionally out of scope, consistently documented: FR-31 (deferred), FR-33–38 (v0.14), FR-1–26 (shipped baseline)

## UX Alignment Assessment

### UX Document Status

**Found** — `ux-designs/ux-imoveis-2026-08-05/DESIGN.md` (visual identity: Meia-noite tokens, typography, components, contrast table) + `EXPERIENCE.md` (IA, voice, component/state patterns, J1–J4 flows, observability, notifications), both status `final`, finalized 2026-08-05. Three review docs' findings already folded into the spines. The PRD names this folder the frontend's design authority; epics.md ingests it as 13 binding UX-DRs.

### UX ↔ PRD Alignment

- **All 8 `[NOTE FOR PRD]` flags in EXPERIENCE.md are accounted for in the PRD:** pt-BR default → NFR-7 amended; sentiment filters → FR-36; recheck cooldown/budget → FR-33; POI layer → FR-35; run-history analytics → FR-37; favourite-gone/resurrection alerts + transition → FR-34; recent-filter recall → FR-38. No orphaned UX flags.
- **Journeys align:** J1 absorbs UJ-1, J2 absorbs UJ-2, J3 absorbs UJ-3+UJ-4, J4 is new UX-driven scope (mapped to FR-33/34, v0.14). ✓
- **Product-model decisions consistent in both:** starred = watched (no separate watchlist), detail = side panel, explicit map-area filtering, per-search drop threshold, no-Telegram channel posture, consciously-undesigned surfaces (export UI, auth UI, Compare). ✓
- **Scope fence respected:** UX-driven backend scope is FR-33–38 (v0.14); v0.13 consumes only the slices its stories touch (backfill card, coverage, health-strip slice, percentile, saved-search rows, side panel). ✓

### UX ↔ Architecture Alignment

- EXPERIENCE.md Foundation restates the binding ADs natively: frontend API-only (AD-8), all decisioning views on the canonical projection (AD-12), single principal (AD-11), async enrichment visible as pending states (AD-4), backfill always operator-visible (AD-13), coverage derived from DB as the single progress truth (FR-29 convention). ✓
- Architecture supports every v0.13 UX surface: toasts ↔ "API errors non-blocking" convention; percentile suppression ↔ config-owned min-cohort (AD-2); lease-conflict toast ↔ AD-13 single-lease. ✓
- FR-33–38 UX scope is **not yet architecture-bound** (spine `binds:` stops at FR-32) — consistent with the plan (hardening deferred to the v0.14 architecture/epics pass), but it means the v0.14 wave must not start from epics alone.

### Alignment Issues (none blocking)

1. **LOW — Locale drift in the architecture spine:** Consistency Conventions still say "AI/UI locale **English default** + pt-BR (NFR-7)". NFR-7 was amended to pt-BR-default by the UX contract; PRD and epics carry the amendment, the spine row was not re-touched. Fix opportunistically at the next spine edit.
2. **LOW — Stale collision wording in spine/companion:** AD-13 ("primary-DB maintenance (validate/finish cycles recreate the Postgres container) must never overlap a running backfill") and the companion's known-debt bullet predate the v0.13-fu1 primary-safe validation surgery. epics.md carries the corrected version (only `migrate-primary.sh` is heartbeat-guarded), and stories cite the corrected text — drift is confined to the architecture docs.
3. **LOW — Designed-but-unscheduled surfaces:** the epics decision (UX-DR12) defers FR-32's in-app Alertas bell/panel and desktop push to "v0.14 surfaces", but PRD §4.5 has no FR carrying them; likewise the since-panel and the Meia-noite restyle of existing card/grid surfaces are designed with no FR/milestone assignment. Risk: orphaned scope at v0.14 planning. Recommendation: at the v0.14 epics pass, mint keys for (a) FR-32 channel completion, (b) since-panel, (c) existing-surface restyle — or note them explicitly as later-wave.

### Warnings

None critical. UX documentation exists, is final, is internally consistent (honest-absence rules, contrast table with one documented sub-AA exception), and is already operationalized as 13 UX-DRs bound to specific stories in epics.md — an unusually strong UX→implementation bridge.

## Epic Quality Review

Standards applied: user-value epics (no technical milestones), epic independence (Epic N never needs Epic N+1), no forward story dependencies, per-story schema creation, BDD acceptance criteria, FR traceability.

### Epic Structure

- **Epic 1 — Hybrid Enrichment, Productized:** framed on the operator (Felipe) as user, with concrete outcomes (start/pause/resume a multi-day backfill from Operações, watch coverage climb, unattended degradation to local). For a single-operator product the operator *is* a first-class user (UJ-3/UJ-4 are PRD journeys) — this is not a technical milestone dressed up. ✓
- **Epic 2 — Deal-Intelligence Deepening:** clear end-user value (Ana/Bruno: percentile signals, decidable email alerts). ✓
- **Epic independence:** explicitly none between the two; they touch disjoint surfaces (AI-routing/backfill/telemetry vs metrics/alerts/UI) and share no core files. Epic 2 nowhere references Epic 1 output. No circular dependencies. ✓

### Dependency Analysis

Declared gates (epics.md frontmatter): s1.2←s1.1, s1.3←s1.1, s1.4←s1.1, s1.5←s1.3, s1.6←s1.4+s1.5, s2.2←s2.1, s2.3←s2.1, s2.4←s2.3, s2.5←s2.2. Every dependency is **backward-only**; each story consumes only earlier-story or shipped-baseline output. The s2.2/s2.5 split is explicitly engineered to avoid a forward dependency ("s2.2 stays grid-only so neither story depends on a later one") — textbook. s1.2's degradation AC exercises the *existing* BIN-248 runner (shipped dev tooling), not s1.3's future hardening — no forward reference. ✓

**Database/entity timing:** no upfront-schema story; each migration lands with the story that needs it (s2.1 percentile columns, s2.3 subscription flag, s2.4 per-search threshold), each AC'd with `alembic check`. ✓

**Brownfield discipline:** no starter template (spine: work lands in existing `src/` hexagonal layout); characterization lock before brownfield SQL change (s2.1); existing modal e2e specs migrated, not deleted (s2.5); AD-1 no-new-leaks guard named in the stories touching `core`. ✓

### Acceptance Criteria Quality

All 11 stories use Given/When/Then, are testable, and include error/degraded paths (lease conflict, quota exhaustion back-off, empty-DB coverage, suppressed percentile absence, circuit-break no-noise, failed-recheck honesty). ACs bind the governing ADs and UX-DRs inline and name the project's test-tier obligations (TDD on core, characterization locks, thin-glue happy+error, contract tests, Playwright e2e per UI story) plus the domain gates (`validate-ai.sh`, `alembic check`). This is well above typical AC quality. ✓

### Findings

**🔴 Critical violations:** none.

**🟠 Major issues:** none.

**🟡 Minor concerns:**

1. **s1.6 carries a system-wide behavior flip inside a UI story:** the AC "the UI default locale flips to pt-BR" changes every existing surface, not just the new Operações components. Deliberate and AC'd (NFR-7 as amended), but existing Playwright e2e specs and unit snapshots that assert English default strings may break en masse. Recommendation: the s1.6 dev session should budget for a sweep of existing e2e/string assertions; consider noting this in the story context at `bmad-create-story` time.
2. **s1.6 is the largest story** (backfill card + controls + coverage display + health-strip slice + locale flip + i18n + e2e). Acceptable as one story since it's one surface with one API dependency set, but it's the most likely candidate to overrun a session; the fallback slice (CLI-only, per FR-28) gives a natural cut line if needed.
3. **s2.3 test-branch wording vs s2.4 capability:** s2.3's unit-test list names a "threshold" branch, but the per-search minimum-drop threshold (and its migration) lands in s2.4. The matcher in s2.3 is new-match (thresholds gate *drop* alerts, not new-match). Harmless, but a dev session could read it as requiring s2.4's schema early — worth a clarifying word at story-context time.
4. **s1.1 is foundation-flavored** (enum + config + validator). It clears the bar because it has user-observable behavior (fail-fast startup error naming the offending key) and is mandated by AD-13's single-source-of-truth rule — noted only for the record, no action.

### Best Practices Compliance

| Check | Epic 1 | Epic 2 |
|---|---|---|
| Delivers user value | ✓ | ✓ |
| Functions independently | ✓ | ✓ |
| Stories appropriately sized | ✓ (s1.6 watched) | ✓ |
| No forward dependencies | ✓ | ✓ |
| Schema created when needed | ✓ | ✓ |
| Clear, testable ACs | ✓ | ✓ |
| FR traceability maintained | ✓ (FR-27/28/29) | ✓ (FR-30/32) |

## Summary and Recommendations

### Overall Readiness Status

**READY** — v0.13 is cleared for implementation. All five in-scope FRs (FR-27, FR-28, FR-29, FR-30, FR-32) trace to stories with backward-only dependencies, binding AD/UX-DR governance, and testable BDD acceptance criteria. Zero critical and zero major issues; seven minor/low findings, none blocking.

### Critical Issues Requiring Immediate Action

None.

### Minor Findings (fix opportunistically, not gating)

1. Architecture spine locale row still says "English default" — drifted vs the amended NFR-7 (pt-BR default). Touch up at the next spine edit.
2. Spine AD-13 + companion still carry the pre-v0.13-fu1 "validate recreates primary Postgres" collision wording; epics.md carries the corrected text and stories cite it, so dev sessions won't inherit the stale claim.
3. Designed-but-unscheduled UX scope (in-app Alertas panel + desktop push, since-panel, existing-surface Meia-noite restyle) has no FR/milestone key — mint keys or an explicit later-wave note at the v0.14 epics pass.
4. s1.6's pt-BR default flip may break existing English-asserting e2e/string tests — budget a sweep in that story's context.
5. s1.6 is the largest story; the CLI-only fallback slice is the cut line if a session overruns.
6. s2.3's "threshold" test-branch wording could be misread as needing s2.4's migration early — clarify at story-context time.
7. FR-1–17 definitions live only in the superseded PRD — acceptable by design; keep the archive folder.

### Recommended Next Steps

1. **Run sprint planning** (`bmad-sprint-planning`, fresh session per harness rules) to land all 11 story keys (v0.13-s1.1…s1.6, v0.13-s2.1…s2.5) in `sprint-status.yaml` with the sequencing gates from epics.md frontmatter.
2. **Start implementation via bmad-loop / bmad-create-story → bmad-dev-story**, Wave 1 = s1.1 ∥ s2.1 (the two epics are independent; within each, the foundation story first).
3. Fold findings 1–2 (spine drift) into the next architecture touch; carry findings 3–6 into the affected stories' context at creation time.

### Final Note

This assessment identified 7 minor issues across 3 categories (document drift, unscheduled UX scope, story-context clarifications) and 0 critical/major issues. The planning set — PRD (2026-08-05), Architecture Spine (AD-1…AD-13), UX contract (13 UX-DRs), and epics.md (2 epics / 11 stories, 100% FR coverage) — is aligned and implementation-ready. Proceed to sprint planning; the minor findings can ride along without blocking.

**Assessed:** 2026-08-05, by the bmad-check-implementation-readiness workflow (facilitated for Felipe).
