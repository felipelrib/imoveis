---
stepsCompleted:
  - step-01-document-discovery
  - step-02-prd-analysis
  - step-03-epic-coverage-validation
  - step-04-ux-alignment
  - step-05-epic-quality-review
  - step-06-final-assessment
inputDocuments:
  - prds/prd-imoveis-2026-07-23/prd.md
  - prds/prd-imoveis-2026-07-23/addendum.md
  - architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md
  - architecture/architecture-imoveis-2026-07-23/COMPANION-architecture-delta.md
  - epics.md
date: 2026-07-23
project: Imoveis — Deal Tracker
---

# Implementation Readiness Assessment Report

**Date:** 2026-07-23
**Project:** Imoveis — Deal Tracker

## Document Discovery

### Assessment set (confirmed)

| Type | Path |
|------|------|
| PRD | `prds/prd-imoveis-2026-07-23/prd.md` |
| PRD addendum | `prds/prd-imoveis-2026-07-23/addendum.md` |
| Architecture spine | `architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md` |
| Architecture companion | `architecture/architecture-imoveis-2026-07-23/COMPANION-architecture-delta.md` |
| Epics & stories | `epics.md` |
| UX | *(none — not in scope for this readiness pass)* |

### Issues noted at discovery

- No whole-vs-sharded duplicate conflicts
- UX design document absent (optional for this brownfield retrofit; UX alignment coverage will be limited)

## PRD Analysis

### Functional Requirements

FR-1: Pluggable platform scrapers — Operator can enable/disable platforms via config and run scrapes that normalize into Listings. Realizes UJ-1, UJ-3. Consequences: New platform class registering via `@register("name")` appears in `/platforms` when enabled in YAML; Failed platform trips circuit breaker and does not block other platforms’ workers indefinitely.

FR-2: Scheduled scraping — System runs scrapes on a configured schedule without manual `POST /scrape`. Realizes UJ-2, UJ-3. Consequences: Celery beat schedule reflects per-platform intervals from `AppConfig`; Manual scrape remains available for on-demand runs.

FR-3: Checkpoint resume — Interrupted scrapes resume without re-fetching completed pages. Realizes UJ-3.

FR-4: Cross-platform dedupe — System merges listings within configured geo/area/text thresholds into one Property. Realizes UJ-1. Consequences: Two listings within 50 m (default) with sufficient similarity resolve to one Property id; Per-platform Listing rows remain queryable for price comparison.

FR-5: Price history — System records price intervals when a Listing price changes and exposes history via API/UI. Realizes UJ-2.

FR-6: Per-platform price comparison UI — User can see rent/sale prices per platform on cards/modal. Realizes UJ-1.

FR-7: Configurable local AI backends — Operator can select Ollama/LM Studio and model names via YAML. Realizes UJ-3.

FR-8: Visual + text enrichment — System attaches visual condition and sentiment-style signals from local models. Realizes UJ-1.

FR-9: Deal verdict — Each enriched Property presents a PT-BR deal verdict on the card/modal. Realizes UJ-1.

FR-10: Statistical scoring — System computes neighbourhood-relative scores and a combined score for colouring. Realizes UJ-1.

FR-11: Skip unchanged AI work — Re-scrapes of unchanged Listings do not re-enqueue expensive AI tasks. Realizes UJ-3.

FR-12: Filterable property grid — User can filter by neighbourhood, price, score, listing type, etc., with non-blocking errors/toasts. Realizes UJ-1.

FR-13: Interactive map — User can browse Properties on a map and filter by viewport bbox. Realizes UJ-1.

FR-14: Favourites & saved searches — User can star Properties and persist named filter sets (single-tenant). Realizes UJ-1.

FR-15: Semantic free-text search — User can query Properties with natural language via embeddings (`q=`). Realizes UJ-1. Notes: BIN-18 Done; UX polish reconciled in v0.5 hygiene (BIN-38).

FR-16: Watchlist price-drop alerts — User can watch a Property and receive notifications when price drops past threshold. Realizes UJ-2.

FR-17: Admin & pipeline telemetry — Operator can inspect health, queues, GPU scale, schedules, and enrichment throughput. Realizes UJ-3.

FR-18: Side-by-side comparison — User can select 2–4 Properties and compare attributes, scores, price/m², and price history in one view. Realizes UJ-1. `[ASSUMPTION: frontend-only over existing APIs is sufficient for v1 of comparison.]`

FR-19: Minimal auth & API key management — User/operator can supply API credentials via env/UI gate instead of hardcoded frontend secrets; nullable `owner` columns become meaningful for favourites/searches/watchlist. Realizes UJ-2, UJ-3.

FR-20: Scraper proxy rotation — Operator can enable a rotating proxy pool from YAML for scale/anti-block. Realizes UJ-3.

FR-21: Export & weekly digest — User can export a filtered result set (CSV/JSON) and optionally receive a scheduled “top new deals” digest. Realizes UJ-1, UJ-2.

FR-22: Neighbourhood polygons — System assigns Properties to neighbourhoods by spatial containment when geometry is populated, improving score cohorts. Realizes UJ-1, UJ-3.

FR-23: Additional platforms (backlog intent) — Product may add ZapImóveis (or others already referenced in UI sanitize lists) as first-class scrapers. `[ASSUMPTION: not committed for v0.5 until epics prioritize after FR-18–22.]`

Total FRs: 23

### Non-Functional Requirements

NFR-1: Local-first — Core enrichment and storage run on operator hardware; no required cloud AI.

NFR-2: Config discipline — Runtime settings via `AppConfig` / `configs/app_config.yaml` (+ env), not scattered `os.getenv` in feature code.

NFR-3: Security — No hardcoded production secrets; forbid `imoveis_secret` / `dev-secret-key` in repo; admin routes require API key when configured.

NFR-4: Resilience — Circuit breakers and checkpoints keep scrapes operable under partial platform failure.

NFR-5: Testability — Merge requires green CI (lint, unit, integration, contract, scrapers live gate, e2e, security).

NFR-6: Observability — Pipeline telemetry and system health endpoints support unattended operation (UJ-3).

NFR-7: i18n — User-facing AI verdicts default to `pt-br`; planning docs in English.

NFR-8: Single-operator privacy posture — BH/MG geographic focus and single-tenant personalization until multi-city / multi-profile is explicitly productized. *(Aligned into PRD §8 during readiness.)*

Total NFRs: 8

### Additional Requirements

**Scope / constraints**
- Baseline shipped MVP: FR-1–FR-17 (v0.1–v0.4 + BIN-18 Done).
- v0.5 in scope: formalize PRD/architecture/epics; prioritize and deliver a cut of FR-18–FR-22; harness bridge; BIN-38 reconcile.
- Out of scope for v0.5: FR-23 unless capacity remains; hot-reload of `app_config.yaml`; multi-city productization UX.

**Explicit non-goals**
- Cloud multi-tenant SaaS with billing; mandatory cloud LLM; brokerage CRM; guaranteed offline maps; perfect condo/IPTU normalization in v0.5; automatic dead-URL pruning as v0.5 must-have; dual-model Planner/Implementer agents.

**Addendum (mechanism / debt)**
- Stack: FastAPI, Celery+Redis, PostgreSQL 15 + PostGIS + pgvector, React/Vite, host Ollama.
- Dedup defaults: 50 m geo, ±2 m² area, Jaro–Winkler ≥ 0.65 (config-driven).
- Implementation gates: `validate.sh`, `finish-feature.sh --pr`, babysit-pr — not replaced by BMad alone.
- Debt carried (not v0.5 commitments): condo/IPTU normalization, dead URL pruning, config hot-reload, map tiles need network, image MD5 / asyncio-in-Celery, beat restart for schedule changes.

**Open questions (PRD §9)**
1. v0.5 priority order among FR-18–FR-22
2. Email digest required vs in-app export first for FR-21
3. Auth FR-19: API-key gate only vs lightweight multi-profile login
4. Neighbourhood polygon data source for BH (FR-22)
5. ZapImóveis in v0.5 vs opportunistic (FR-23)

### PRD Completeness Assessment

PRD is status `final`, clearly separates shipped baseline (FR-1–17) from Beyond-MVP (FR-18–23), marks assumptions, and maps Linear seeds. NFRs are present but qualitative (no numeric SLOs — flagged as assumption). Open questions on v0.5 cut and FR-21/23 priority remain for epics to resolve. Addendum correctly keeps stack/debt out of the spine.

## Epic Coverage Validation

### Epic FR Coverage Extracted

FR-1..FR-17: Covered as Baseline — shipped MVP (v0.1–v0.4 + BIN-18); no new delivery epic
FR-18: Epic 1 — Compare properties side-by-side (stories 1.1–1.3; Linear BIN-19 / BIN-41..43)
FR-19: Epic 2 — Own favourites, searches & watchlist (stories 2.1–2.3; Linear BIN-20 / BIN-44..46)
FR-20: Epic 3 — Scale scrapes with proxy rotation (stories 3.1–3.3; Linear BIN-21 / BIN-47..49)
FR-21: Epic 4 — Export shortlists & weekly deal digest (stories 4.1–4.3; Linear BIN-22 / BIN-50..52)
FR-22: Epic 5 — Neighbourhoods by map polygons (stories 5.1–5.3; Linear BIN-23 / BIN-53..55)
FR-23: Deferred / Future — additional platforms (not a v0.5 delivery epic)

Total FRs accounted in epics map: 23

### Coverage Matrix

| FR Number | PRD Requirement | Epic Coverage | Status |
| --------- | --------------- | ------------- | ------ |
| FR-1 | Pluggable platform scrapers | Baseline (shipped) | ✓ Covered |
| FR-2 | Scheduled scraping | Baseline (shipped) | ✓ Covered |
| FR-3 | Checkpoint resume | Baseline (shipped) | ✓ Covered |
| FR-4 | Cross-platform dedupe | Baseline (shipped) | ✓ Covered |
| FR-5 | Price history | Baseline (shipped) | ✓ Covered |
| FR-6 | Per-platform price comparison UI | Baseline (shipped) | ✓ Covered |
| FR-7 | Configurable local AI backends | Baseline (shipped) | ✓ Covered |
| FR-8 | Visual + text enrichment | Baseline (shipped) | ✓ Covered |
| FR-9 | Deal verdict | Baseline (shipped) | ✓ Covered |
| FR-10 | Statistical scoring | Baseline (shipped) | ✓ Covered |
| FR-11 | Skip unchanged AI work | Baseline (shipped) | ✓ Covered |
| FR-12 | Filterable property grid | Baseline (shipped) | ✓ Covered |
| FR-13 | Interactive map | Baseline (shipped) | ✓ Covered |
| FR-14 | Favourites & saved searches | Baseline (shipped) | ✓ Covered |
| FR-15 | Semantic free-text search | Baseline + hygiene BIN-38 | ✓ Covered |
| FR-16 | Watchlist price-drop alerts | Baseline (shipped) | ✓ Covered |
| FR-17 | Admin & pipeline telemetry | Baseline (shipped) | ✓ Covered |
| FR-18 | Side-by-side comparison | Epic 1 (1.1–1.3) | ✓ Covered |
| FR-19 | Minimal auth & API key management | Epic 2 (2.1–2.3) | ✓ Covered |
| FR-20 | Scraper proxy rotation | Epic 3 (3.1–3.3) | ✓ Covered |
| FR-21 | Export & weekly digest | Epic 4 (4.1–4.3) | ✓ Covered |
| FR-22 | Neighbourhood polygons | Epic 5 (5.1–5.3) | ✓ Covered |
| FR-23 | Additional platforms | Deferred / Future (explicit) | ✓ Covered (deferred) |

### Missing Requirements

### Critical Missing FRs

None.

### High Priority Missing FRs

None.

### Notes (not missing FRs)

- Epics invent **NFR-8** (single-operator privacy / BH-first) — present in PRD vision/non-users but not numbered in PRD §8. Traceable; recommend either add NFR-8 to PRD or cite as derived from vision.
- FR-15 hygiene (BIN-38) is planning/ops, not a delivery epic — correctly called out in inventory.
- FR-23 correctly deferred per PRD §6.3; no delivery epic required for readiness.

### Coverage Statistics

- Total PRD FRs: 23
- FRs covered in epics (including baseline + deferred): 23
- FRs with v0.5 delivery epics: 5 (FR-18–22)
- Coverage percentage: 100%

## UX Alignment Assessment

### UX Document Status

**Not Found** — no `*ux*.md` / `ux-designs/` under planning artifacts. Epics inventory explicitly excludes UX (`excludedDocuments: UX design contract`).

### Implied UI (yes — UX is implied)

PRD and epics assume a substantial React SPA surface:
- UJ-1/UJ-2: Properties grid, filters, map, cards, modal, favourites, watchlist, alerts
- FR-18: side-by-side compare view (Epic 1 stories 1.2–1.3)
- FR-19: frontend credential gate (Story 2.2)
- FR-21: Export from Properties UI (Story 4.2)
- Architecture AD-8: React talks only to FastAPI

### Alignment Issues

- No formal UX contract to cross-check against PRD journeys or architecture ADs.
- UI acceptance criteria rely on “existing frontend patterns” + PRD assumptions (stated in epics). Risk: inconsistent compare/export/auth gate UX without a shared wireframe or interaction model.
- Architecture supports UI via AD-8 / AD-12 projection, but does not specify interaction patterns (selection limits, compare layout, credential gate UX).

### Warnings

- **WARNING (Medium):** User-facing v0.5 epics (especially Epic 1 Compare and Epic 2 credential gate) proceed without `bmad-ux`. Acceptable for brownfield retrofit if stories stay thin and mirror current UI language; recommend a focused UX pass before or during Epic 1 if compare UI grows beyond a simple table.
- **WARNING (Low):** BIN-38 hygiene for FR-15 semantic search polish has no UX artifact — keep polish scoped to existing patterns.
- Not a blocker for implementation readiness given explicit brownfield exclusion and shipped MVP UI as the pattern source of truth.

## Epic Quality Review

Beginning review against create-epics-and-stories standards (user value, independence, dependencies, AC quality). Brownfield: no starter-template story required; architecture is ratify-existing (AD-1..12).

### Best Practices Compliance (per epic)

| Epic | User value | Independence | Story sizing | No forward deps | ACs (GWT/testable) | FR traceability |
| ---- | ---------- | ------------ | ------------ | --------------- | ------------------ | --------------- |
| 1 Compare | ✓ | ✓ stands alone | ✓ 1.1–1.3 | ✓ 1.1→1.2→1.3 | ✓ | FR-18 |
| 2 Auth/ownership | ✓ (user owns data) | ✓ | ⚠ 2.3 large | ✓ | ✓ | FR-19 |
| 3 Proxy | ✓ (operator UJ-3) | ✓ | ✓ | ✓ | ✓ | FR-20 |
| 4 Export/digest | ✓ | ⚠ soft need Epic 1+2 | ✓ | ✓ within-epic | ✓ | FR-21 |
| 5 Polygons | ✓ (via 5.3) | ✓ | ✓ | ✓ | ✓ | FR-22 |

### 🔴 Critical Violations

None.

- No technical-only epics without a user/operator outcome.
- No forward story dependencies (no “wait for Story N+1”).
- No greenfield starter-template gap (brownfield correct).

### 🟠 Major Issues

1. **Story 2.3 scope risk** — Single story covers favourites + saved searches + watchlist owner scoping + migrations + safe attribution of existing data. Likely oversized for one PR; may slip acceptance or force a mega-migration.
   - **Remediation:** Split before implementation into (a) owner column + migration/attribution, (b) favourites/searches scoping, (c) watchlist scoping — or explicitly size as multi-PR with sequenced ACs in Linear.

2. **Epic 4 soft dependency on Epic 1 (AD-12 projection)** — Story 4.1 requires the same canonical property projection as Compare. Shipping Epic 4 before Epic 1 risks a second shape or rework.
   - **Remediation:** Keep sprint order Epic 1 → … → Epic 4 (as listed), or allow Story 4.1 to *establish* AD-12 if Compare is deferred. Document the chosen order in sprint planning (BIN-37).

### 🟡 Minor Concerns

1. **Epic 2 borderline “auth system” framing** — Mitigated by product note (API-key gate + single principal) and user-facing Story 2.2/2.3. OK if first cut stays gate-only.
2. **Epic 3 is operator/infrastructure-flavoured** — Valid for UJ-3 / FR-20; not an end-user house-hunter epic. Acceptable.
3. **Stories 1.1 / 5.1 / 5.2 are enabling** — Appropriate brownfield pattern; user value lands in later stories of the same epic.
4. **Linear story id order Epic 2** — Table lists BIN-44, BIN-46, BIN-45 (46 before 45). Cosmetic; verify story titles match 2.1/2.2/2.3 sequence in Linear.
5. **Open PRD questions left open** — Correct (do not invent). Sprint planning must pick FR-18–22 delivery order and FR-21 channel cut.
6. **NFR-8 only in epics** — Derived from PRD vision; align numbering in a hygiene edit or cite as derived.

### Architecture / special checks

- Starter template: N/A (brownfield).
- DB timing: migrations appear when first needed (2.3 owner, 5.1 geometry) — ✓
- AD citations on epics/stories — ✓ (ticket altitude)
- Implementation gates preserved — ✓

## Summary and Recommendations

### Overall Readiness Status

**READY** — Planning cohesion is sufficient to proceed to sprint planning (BIN-37) and implementation. FR coverage is 100% (baseline + five v0.5 epics + deferred FR-23). No critical epic-structure defects. Residual gaps are tracked as follow-ups rather than blockers.

### Critical Issues Requiring Immediate Action

None.

### Issues tracked / recommended (non-blocking)

| Severity | Finding | Disposition |
| -------- | ------- | ----------- |
| Major | Story 2.3 oversized | Linear follow-up on Epic 2 / BIN-20 |
| Major | Epic 4 needs Epic 1 projection order | Hand to BIN-37 sprint planning |
| Medium | No UX contract for Compare / auth gate | Optional follow-up: focused `bmad-ux` before Epic 1 UI |
| Low | NFR-8 numbered in epics only | **Fixed** — numbered NFR-1..8 in PRD §8 |
| Low | Epic 2 Linear story id order | Cosmetic check in Linear |

### Recommended Next Steps

1. Run **sprint planning** (BIN-37 / `bmad-sprint-planning`) with delivery order **Epic 1 → 2 → 3|5 → 4** (or equivalent that keeps AD-12 projection before export).
2. Before implementing Epic 2 Story 2.3, **split or sequence** owner migration vs personalization surfaces in Linear.
3. Optionally schedule a thin **UX pass** for Compare + credential gate if UI ambiguity blocks Story 1.2/1.3.
4. Proceed to story cycle: `bmad-create-story` → feature-pipeline gates — do not replace `validate.sh` / `finish-feature.sh`.

### Coverage snapshot

- PRD FRs: 23 — epics map: 23 (100%)
- v0.5 delivery epics: 5 (FR-18–22) — 15 stories — Linear synced (BIN-19..23 + children)
- NFRs: 7 in PRD (+ NFR-8 in epics)
- UX: absent (brownfield warning only)

### Final Note

This assessment identified **0 critical**, **2 major**, **1 medium**, and **2 low** issues across FR coverage, UX alignment, and epic quality. Address the major items via sprint planning and Epic 2 story shaping; they do not require rewriting the PRD or architecture spine before implementation starts.

**Assessor:** Auto (BMad check-implementation-readiness)  
**Date:** 2026-07-23  
**Branch / ticket:** `feat/bin-36` / BIN-36
