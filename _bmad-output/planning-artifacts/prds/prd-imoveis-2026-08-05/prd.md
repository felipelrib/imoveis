---
title: Imoveis — Deal Tracker
status: final
created: 2026-08-05
updated: 2026-08-05
supersedes: prds/prd-imoveis-2026-07-23/prd.md
---

# PRD: Imoveis — Deal Tracker

*Versioned refresh: baseline is everything shipped through v0.12; planning target is v0.13.*

## 0. Document Purpose

This PRD is for Felipe (builder/PM), downstream BMad architecture/epics workflows, and bmad-loop execution. It supersedes the 2026-07-23 PRD, whose entire planning scope (v0.5 / FR-18–FR-23) has since shipped, along with six further waves. The **baseline is Linear milestones v0.1–v0.12 (all 100% Done, backlog empty)**; the planning target is **v0.13**. Shipped implementation details are not re-litigated here — they live in `docs/features/` and `docs/architecture.md`. Assumptions inferred without explicit product confirmation are marked `[ASSUMPTION]`.

**Planning regime (settled 2026-08-05):** BMad is the source of truth for planning *and* the dev loop (bmad-loop), superseding the Linear-SoR/feature-pipeline regime. Wave-4 harness surgery (CLAUDE.md rewrite, gate wiring via `bmad-customize`) runs as a pre-epic harness track; `scripts/agent/` validation gates are preserved, not replaced. Linear remains the tracking mirror.

## 1. Vision

Imoveis is a **local-first** deal tracker for Brazilian real-estate listings. It continuously scrapes multiple platforms, merges the same physical property into one record, watches prices over time, and enriches listings with AI (visual condition, neighbourhood sentiment, listing-description signals, statistical deal signals) so a human can shortlist and act before a good deal disappears.

The product matters because house-hunting across QuintoAndar, OLX, ZapImóveis, and peers is fragmented: the same flat appears under different IDs, price drops are easy to miss, and raw listing copy/photos do not answer "is this actually a deal for this neighbourhood?" Imoveis turns that noise into a single score-coloured view with alerts.

**Geographic focus:** Belo Horizonte / MG is the primary product geography. SP/Campinas scrape coverage shipped (BIN-113) and is **opportunistic** — data flows, but multi-city is not yet product intent (candidate v0.14 theme; see §9).

**AI posture:** local models (Ollama / LM Studio) are the default and permanent enrichment path; a **quota-bounded cloud assist** (Gemini/Gemma free tier) exists for batch backfill and is being productized in v0.13 (see §4.3, NFR-1).

**Product language:** English default (UI + AI) with `pt-BR` supported; further locales via the add-a-locale checklist. **Deployment posture:** single-operator, privacy-preserving, runs on the user's machine (Docker + host Ollama).

## 2. Target User

### 2.1 Jobs To Be Done

- **Functional:** Continuously discover and compare rent/sale listings across platforms without manual tab-hopping.
- **Functional:** Know when a watched property drops in price (or looks cheap vs neighbourhood peers).
- **Functional:** Judge listing quality using photos + text + stats without pasting into a cloud chat.
- **Emotional:** Feel in control of a chaotic market; reduce FOMO and second-guessing.
- **Contextual:** Operate entirely on a personal workstation (GPU optional) without sending listing data to a SaaS — with a deliberate, bounded exception for anonymous-enough batch text enrichment via the cloud assist path.

### 2.2 Non-Users (current product)

- Multi-tenant agencies / brokerages needing SSO, RBAC, or client portals.
- Users who require a fully offline map (OSM tiles need network today).
- National multi-city power users expecting dozens of platforms out of the box — SP/Campinas coverage exists, but the product is BH-first by decision (2026-08-05), not assumption.

### 2.3 Key User Journeys

- **UJ-1. Ana finds a Savassi deal without opening five tabs.**
  - **Persona + context:** Ana, renting in BH, checks listings most evenings after work.
  - **Entry state:** Stack already scraping on a schedule; she opens the React app on localhost.
  - **Path:** Opens Properties → filters neighbourhood/price → scans score-coloured cards → opens modal for price history + deal verdict → stars a favourite.
  - **Climax:** She sees the same flat from QuintoAndar and OLX as **one** property with comparable platform prices.
  - **Resolution:** Favourite saved; she can return tomorrow without rebuilding filters.
  - **Edge case:** One platform is circuit-broken — she still sees the other listing and a degraded platform set.

- **UJ-2. Bruno gets pinged when a watched listing drops.**
  - **Persona + context:** Bruno, buying in BH, watches 8–12 candidates.
  - **Entry state:** Authenticated via the API-key gate; watchlist populated.
  - **Path:** Beat scrapes → dedupe detects lower price → notifier fires on his configured channel.
  - **Climax:** He opens the property and confirms the drop on the price-history chart.
  - **Resolution:** He schedules a visit; watchlist remains.
  - **Edge case:** Drop is below his min threshold — no alert (noise control).

- **UJ-3. Felipe operates the pipeline without babysitting GPU OOMs.**
  - **Persona + context:** Builder/operator of this local stack.
  - **Entry state:** Docker Compose up; Ollama on host.
  - **Path:** Admin panel → check queue/GPU → trigger scrape or wait for beat → watch AI enrichment throughput on Dashboard.
  - **Climax:** Unchanged listings skip AI; circuit breaker trips a bad platform without killing the worker.
  - **Resolution:** Pipeline runs unattended overnight.

- **UJ-4. Felipe backfills the whole DB over cloud quota without watching it.**
  - **Persona + context:** Same operator, wanting description-derived signals on *every* historical property, not just new scrapes.
  - **Entry state:** Free-tier Gemma quota (~14.4k requests/day best-case); tens of thousands of un-enriched rows; backfill runner available.
  - **Path:** Kicks off a quota-paced backfill → runner consumes the daily budget through the single Redis pacer → hits the cap → sleeps → resumes next day, unattended.
  - **Climax:** He checks coverage telemetry mid-run and sees % enriched climbing and a credible ETA, without `ResourceExhausted` bans or a second consumer racing the quota.
  - **Resolution:** Multi-day backfill completes; enrichment coverage reaches target; local Ollama continues handling incremental work.
  - **Edge case:** Quota exhausts early (provider-side throttling) — runner backs off and resumes cleanly; no data loss, no duplicate work.

## 3. Glossary

- **Property** — Canonical real-world home/apartment after dedupe; may have many **Listings**.
- **Listing** — A platform-specific offer (QuintoAndar, OLX, ZapImóveis, …) with its own price, URL, and listing type (rent/sale).
- **Platform** — External source site implemented as a scraper plugin.
- **Dedupe** — Match/merge of listings into one Property using geo proximity + heuristics.
- **Deal verdict** — Short natural-language summary combining score, visual, and sentiment signals (localized).
- **Stat score** — Neighbourhood-relative statistical valuation signal.
- **Description enrichment** — AI signals extracted from listing text (v0.12): condition cues, amenity extraction, red flags.
- **Cloud assist** — The optional, quota-bounded Gemini/Gemma batch-enrichment path; never required for core enrichment.
- **Backfill runner** — Resumable driver (`core/backfill_runner.py`) that enriches historical rows through the same pipeline authority, paced by the quota pacer.
- **Quota pacer** — The single Redis-backed budget owner (`backfill:gemma`) for cloud-assist requests; by invariant there is exactly one consumer.
- **Watchlist** — Per-property subscription that triggers on price drops past a threshold.
- **Favourite / Saved search** — User-starred shortlist / named filter preset (single-tenant).
- **Enrichment** — Async AI/metrics pipeline that attaches scores, verdicts, embeddings, etc.
- **Semantic search** — Free-text query over property embeddings (`GET /properties?q=`).

## 4. Features

FR numbering is global and stable across PRD versions; section numbering restarts here.

### 4.1 MVP baseline — FR-1–FR-17 (shipped, v0.1–v0.4)

Unchanged from the superseded PRD, which remains their definition of record: pluggable scrapers (FR-1–3), dedupe & price history (FR-4–6), local AI enrichment & scoring (FR-7–11), discovery UX (FR-12–15), alerts & operations (FR-16–17). Not restated here; see `docs/features/` for implementation truth.

### 4.2 Shipped since the last PRD — v0.5–v0.12 (baseline fold-in)

Everything the 2026-07-23 PRD planned has shipped, plus six waves it never saw:

| Wave | Theme | Product capabilities added |
|------|-------|----------------------------|
| v0.5 | Beyond-MVP cut | **FR-18** side-by-side comparison, **FR-19** auth/API-key management, **FR-20** proxy rotation, **FR-21** export + digest, **FR-22** neighbourhood polygons — all shipped |
| v0.6 | Neighbourhood quality | **FR-24** neighbourhood quality profiles (sentiment/quality signals per neighbourhood, BIN-85 area) |
| v0.7 | Dual listing-type scoring | **FR-25** rent and sale listings on one Property scored per listing type (BIN-96 area) |
| v0.8 | i18n | Product pt-BR localization (catalogs, locale preference, localized AI verdicts) — NFR-7 |
| v0.9 | Follow-up sweep | Debt/polish wave (BIN-104) — no new FRs |
| v0.10 | Debt remediation | Engineering wave (layering, SQL parameterization, lockfile) — no new FRs |
| v0.11 | Frontend TS migration | TypeScript-strict frontend — no new FRs |
| v0.12 (retroactive) | Stabilization & description enrichment | **FR-26** listing-description enrichment (AI signals from listing text), Cloudflare bypass generalization (FlareSolverr), resumable cloud backfill runner as **dev tooling** (productized by v0.13), platform upgrades (PostGIS 17, maplibre 6) |

**FR-23 (additional platforms):** shipped — ZapImóveis is a first-class scraper (BIN-127). Moved from "deferred" into baseline.

### 4.3 v0.13 Theme A — Productize the cloud/local AI-enrichment split (planned)

**Description:** The v0.12 wave left a working but informal hybrid: local Ollama enriches incrementally, and a dev-script backfill runner pushes historical rows through free-tier Gemma. v0.13 makes this split a sanctioned, observable product capability instead of operator folklore. Realizes UJ-3, UJ-4.

#### FR-27: First-class multi-backend enrichment routing
Operator selects enrichment backends per task class (e.g. text signals → cloud-capable, visual → local) via `AppConfig`, with documented semantics, validation at startup, and contract coverage. Local Ollama/LM Studio remains the default and the permanent fallback — cloud never becomes required (NFR-1). Realizes UJ-3, UJ-4.

**Consequences (testable):**
- Invalid backend/task-class combinations fail fast at config load with a clear error, not mid-pipeline.
- With cloud unavailable (no key, quota exhausted, network down), enrichment degrades to the local path without operator intervention.

#### FR-28: Quota-governed cloud backfill as a product surface
The resumable backfill runner graduates from `scripts/dev` to an operator-facing operation: start/pause/resume, progress and pacing state visible, safe-by-construction quota use. The single Redis pacer (`backfill:gemma`) remains the only budget owner; no second consumer of the quota is ever added. Realizes UJ-4. `[ASSUMPTION: admin-panel exposure is the target surface; a hardened CLI + telemetry-only cut is an acceptable first slice — see §9.]`

**Consequences (testable):**
- A backfill interrupted at any point (crash, quota exhaustion, operator stop) resumes without re-enriching completed rows.
- Daily request count never exceeds the configured budget; provider `ResourceExhausted` triggers back-off, not failure.

#### FR-29: Enrichment coverage telemetry
Operator can see, per signal type, what fraction of Properties is enriched, backfill throughput, and a projected completion date for an active backfill. Realizes UJ-3, UJ-4.

**Consequences (testable):**
- Coverage figures derive from the DB (not runner logs) and survive runner restarts.

### 4.4 v0.13 Theme B — Deal-intelligence deepening (planned)

**Description:** With description enrichment (FR-26) landing signals on every listing and backfill (Theme A) extending them to the whole corpus, the dashboard can answer sharper questions than a single combined score. Realizes UJ-1, UJ-2. Exact cut within this theme is decided at epics time.

#### FR-30: Price-per-m² percentile views
User sees where a Property's price/m² falls within its neighbourhood cohort (percentile on card/modal, filterable). Realizes UJ-1. `[ASSUMPTION: neighbourhood polygons (FR-22) + dual-type scoring (FR-25) give adequate cohorts; no new geo work needed.]`

#### FR-31: Total-cost-of-occupancy normalization
Condo fee + IPTU are normalized across platforms into a comparable monthly total alongside rent/price — promoting long-carried debt into a product capability. Realizes UJ-1. `[ASSUMPTION: platform coverage of fee data is partial; the FR includes surfacing "unknown" honestly rather than imputing.]`

#### FR-32: Saved-search new-match alerts
Alerts extend beyond watched-property price drops: a saved search can notify when a **new** Property matching it appears. Realizes UJ-2. `[ASSUMPTION: reuses the shipped notifier registry (FR-21) and saved searches (FR-14); no new channel work required for v1.]`

## 5. Non-Goals (Explicit)

- Cloud-hosted multi-tenant SaaS with billing.
- Making cloud AI **required** for any core path — the cloud assist is optional, quota-bounded, and batch-only; local enrichment is never removed (research invariant, 2026-08-05).
- Lift-and-shift of scraper, DB, or Celery/Redis to cloud free tiers — cloud may only ever hold a slim, regenerable read-model projection; scrapers must egress from the residential IP.
- Multi-city productization UX in v0.13 (coverage stays opportunistic; candidate v0.14 theme).
- Full brokerage CRM (leads, commissions, contracts).
- Guaranteed offline maps / offline OSM tileserver.
- Paid cloud AI tiers as a planning basis — v0.13 sizes against the free tier.

## 6. Scope

### 6.1 Baseline (shipped — v0.1–v0.12)

FR-1 through FR-26 as implemented and documented in `docs/features/` (58 BIN-prefixed feature docs), including all of the superseded PRD's planned scope (FR-18–FR-23).

### 6.2 In scope for v0.13 planning / delivery

- **Theme A:** FR-27, FR-28, FR-29 — cloud/local split productization.
- **Theme B:** a prioritized cut of FR-30–FR-32 (exact subset set at epics after readiness).
- **Harness track (process, not FR):** SoR pivot waves 3–4 — per-epic verification feeding the bmad-loop deferred-work ledger; CLAUDE.md rewrite inverting the feature-pipeline mandate; `scripts/agent/` gates wired into bmad-loop via `bmad-customize`. Gate: completes **before** v0.13 story execution starts.
- Architecture pass binds the cloud-assist path (AD-13 or AD-7 amendment) per sprint-change-proposal §4.2.

### 6.3 Out of scope for v0.13 (deferred)

- Multi-city productization (v0.14 candidate — revisit at v0.13 close).
- Hot-reload of `app_config.yaml`.
- Dead listing URL pruning (tracked debt).
- New scrape platforms beyond the shipped three.

## 7. Success Metrics

| Metric | Intent | Counter-metric |
|--------|--------|----------------|
| Dedup accuracy | Same physical home → one Property across platforms | Over-merge rate (distinct homes wrongly merged) |
| Alert latency | Price drop / new match → user-visible notification | Alert spam (sub-threshold, duplicates) |
| Enrichment coverage (new) | % of Properties with description signals; backfill days-to-complete within free quota | Quota overruns / provider bans; second quota consumer appearing |
| Cloud independence (new) | Core pipeline fully functional with cloud assist disabled | Silent cloud dependency creeping into incremental enrichment |
| Deal-intelligence adoption | Percentile/TCO signals visible on shortlisted properties; saved-search alerts firing | Signal noise (percentiles on cohorts too small to mean anything) |
| v0.13 outcome | Theme A shipped whole; ≥1 Theme B FR shipped with feature doc | Scope churn without readiness check |

`[ASSUMPTION: numeric SLOs still not instrumented as first-class KPIs; FR-29 is the first step toward that for enrichment.]`

## 8. Non-Functional Requirements

- **NFR-1 Local-first with bounded cloud assist:** Core enrichment and storage run on operator hardware; no *required* cloud AI. The sanctioned exception is the quota-bounded, operator-triggered, batch-only cloud-assist path (Gemini/Gemma free tier) — it may accelerate backfill, never gate core function, and the local path is never removed. *(Posture change from the 2026-07-23 PRD documented per correct-course §4.1.)*
- **NFR-2 Config discipline:** Runtime settings via `AppConfig` / `configs/app_config.yaml` (+ env), not scattered `os.getenv` in feature code.
- **NFR-3 Security:** No hardcoded production secrets; forbid `imoveis_secret` / `dev-secret-key` in repo; admin routes require API key when configured; cloud API keys via env only.
- **NFR-4 Resilience:** Circuit breakers and checkpoints keep scrapes operable under partial platform failure; quota exhaustion degrades to local enrichment, not outage.
- **NFR-5 Testability:** Merge requires green CI (lint, unit, integration, contract, scrapers live gate, e2e, security) — gates preserved unchanged across the SoR pivot.
- **NFR-6 Observability:** Pipeline telemetry and system health support unattended operation, extended in v0.13 to enrichment coverage and backfill pacing (FR-29).
- **NFR-7 i18n:** English default; `pt-BR` supported via catalogs + preference (`ui.locale` / Redis). Canonical DB/API wire values remain English. Further locales additive via `docs/i18n/add-a-locale.md`.
- **NFR-8 Geography & tenancy posture:** BH/MG primary geography with opportunistic SP/Campinas data; single-tenant personalization (nullable `owner`) until multi-city / multi-profile is explicitly productized.

## 9. Open Questions

**Answered by shipping since 2026-07-23** (kept for the record): v0.5 priority order → delivered in full; digest necessity → shipped notifier registry + export; auth depth → API-key gate shipped; BH polygon source → GeoJSON path shipped; ZapImóveis timing → shipped (BIN-127).

**Open for v0.13:**

1. FR-28 surface: full admin-panel backfill control, or hardened CLI + FR-29 telemetry as the v0.13 slice? `[NOTE FOR PM: decide at epics; affects scope size materially.]`
2. Theme B cut: which of FR-30/31/32 make the wave? (FR-31 has the worst data-availability risk; FR-32 the smallest surface.)
3. Multi-city (v0.14 candidate): revisit at v0.13 close — promote to product intent or keep opportunistic?
4. Should enrichment coverage targets (FR-29) become the first numeric SLOs on the dashboard?

## 10. References

- `README.md`, `docs/index.md`, `docs/architecture.md`, `docs/features/*` (58 feature docs)
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-08-05.md` (drift analysis + §4.1 edit basis)
- `_bmad-output/planning-artifacts/research/technical-imoveis-local-vs-cloud-hybrid-stack-research-2026-08-05.md` (topology invariants)
- `_bmad-output/project-context.md` (agent rules incl. Gemma quota, Redis surfaces)
- ADR 0002 (agent workflow), ADR 0003 (BMad planning bridge), ADR 0004 (parallel workspaces)
- Superseded: `prds/prd-imoveis-2026-07-23/` (FR-1–FR-17 definitions remain of record there)
- Linear: project Imoveis — Deal Tracker; milestones v0.1–v0.12 all Done; v0.13 milestone to be created at epics sync
