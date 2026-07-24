---
title: Imoveis — Deal Tracker
status: final
created: 2026-07-23
updated: 2026-07-23
---

# PRD: Imoveis — Deal Tracker

*Retrofit PRD for the shipped MVP (v0.1–v0.4) plus the next product phase (v0.5 / Beyond MVP).*

## 0. Document Purpose

This PRD is for Felipe (builder/PM), downstream BMad architecture/epics workflows, and Linear execution via the Imoveis feature-pipeline. It **retrofits** the product that already shipped in Linear milestones v0.1–v0.4 (100% Done) so planning artifacts exist in-repo, then defines **what v0.5 should prioritize**. It does not re-litigate shipped implementation details; those live in `docs/features/` and `docs/architecture.md`. Assumptions inferred from code/docs without explicit product confirmation are marked `[ASSUMPTION]`.

## 1. Vision

Imoveis is a **local-first** deal tracker for Brazilian real-estate listings. It continuously scrapes multiple platforms, merges the same physical property into one record, watches prices over time, and enriches listings with **local** AI (visual condition, neighbourhood sentiment, statistical deal signals) so a human can shortlist and act before a good deal disappears.

The product matters because house-hunting across QuintoAndar, OLX, and peers is fragmented: the same flat appears under different IDs, price drops are easy to miss, and raw listing copy/photos do not answer “is this actually a deal for this neighbourhood?” Imoveis turns that noise into a single score-coloured view with alerts.

**Geographic focus (current):** Belo Horizonte / MG. **Product language:** English (UI + AI); second locales deferred (BIN-63). **Deployment posture:** single-operator, privacy-preserving, runs on the user’s machine (Docker + host Ollama).

## 2. Target User

### 2.1 Jobs To Be Done

- **Functional:** Continuously discover and compare rent/sale listings across platforms without manual tab-hopping.
- **Functional:** Know when a watched property drops in price (or looks cheap vs neighbourhood peers).
- **Functional:** Judge listing quality using photos + text + stats without pasting into a cloud chat.
- **Emotional:** Feel in control of a chaotic market; reduce FOMO and second-guessing.
- **Contextual:** Operate entirely on a personal workstation (GPU optional) without sending listing data to a SaaS.

### 2.2 Non-Users (v1 / current product)

- Multi-tenant agencies / brokerages needing SSO, RBAC, or client portals.
- Users who require a fully offline map (OSM tiles need network today).
- National multi-city power users expecting dozens of platforms out of the box. `[ASSUMPTION: BH-first is intentional until geo config is productized.]`

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
  - **Entry state:** Authenticated only via local API key / mock auth as today; watchlist populated.
  - **Path:** Beat scrapes → dedupe detects lower price → notifier fires → Bruno sees toast/log/email channel configured.
  - **Climax:** He opens the property and confirms the drop on the price-history chart.
  - **Resolution:** He schedules a visit; watchlist remains.
  - **Edge case:** Drop is below his min threshold — no alert (noise control).

- **UJ-3. Felipe operates the pipeline without babysitting GPU OOMs.**
  - **Persona + context:** Builder/operator of this local stack.
  - **Entry state:** Docker Compose up; Ollama on host.
  - **Path:** Admin panel → check queue/GPU → trigger scrape or wait for beat → watch AI enrichment throughput on Dashboard.
  - **Climax:** Unchanged listings skip AI; circuit breaker trips a bad platform without killing the worker.
  - **Resolution:** Pipeline runs unattended overnight.

## 3. Glossary

- **Property** — Canonical real-world home/apartment after dedupe; may have many **Listings**.
- **Listing** — A platform-specific offer (QuintoAndar, OLX, …) with its own price, URL, and listing type (rent/sale).
- **Platform** — External source site implemented as a scraper plugin.
- **Dedupe** — Match/merge of listings into one Property using geo proximity + heuristics.
- **Deal verdict** — Short PT-BR natural-language summary combining score, visual, and sentiment signals.
- **Stat score** — Neighbourhood-relative statistical valuation signal.
- **Watchlist** — Per-property subscription that triggers on price drops past a threshold.
- **Favourite** — User-starred Property shortlist (single-tenant today).
- **Saved search** — Named filter preset for the Properties page.
- **Enrichment** — Async AI/metrics pipeline that attaches scores, verdicts, embeddings, etc.
- **Semantic search** — Free-text query over property embeddings (`GET /properties?q=`).
- **Primary checkout** — Main git working tree; idle when on `main` and clean (ADR 0004).
- **Worktree** — Sibling isolated checkout for parallel agents when primary is busy.

## 4. Features

### 4.1 Multi-platform ingestion & resilience (shipped)

**Description:** Plugin scrapers ingest QuintoAndar and OLX with rate limits, checkpoints, and circuit breakers; Celery beat schedules recurring scrapes. Realizes UJ-1, UJ-3.

**Functional Requirements:**

#### FR-1: Pluggable platform scrapers
Operator can enable/disable platforms via config and run scrapes that normalize into Listings. Realizes UJ-1, UJ-3.

**Consequences (testable):**
- New platform class registering via `@register("name")` appears in `/platforms` when enabled in YAML.
- Failed platform trips circuit breaker and does not block other platforms’ workers indefinitely.

#### FR-2: Scheduled scraping
System runs scrapes on a configured schedule without manual `POST /scrape`. Realizes UJ-2, UJ-3.

**Consequences (testable):**
- Celery beat schedule reflects per-platform intervals from `AppConfig`.
- Manual scrape remains available for on-demand runs.

#### FR-3: Checkpoint resume
Interrupted scrapes resume without re-fetching completed pages. Realizes UJ-3.

### 4.2 Deduplication & price history (shipped)

**Description:** Listings for the same Property merge; price intervals record changes over time. Realizes UJ-1, UJ-2.

#### FR-4: Cross-platform dedupe
System merges listings within configured geo/area/text thresholds into one Property. Realizes UJ-1.

**Consequences (testable):**
- Two listings within 50 m (default) with sufficient similarity resolve to one Property id.
- Per-platform Listing rows remain queryable for price comparison.

#### FR-5: Price history
System records price intervals when a Listing price changes and exposes history via API/UI. Realizes UJ-2.

#### FR-6: Per-platform price comparison UI
User can see rent/sale prices per platform on cards/modal. Realizes UJ-1.

### 4.3 Local AI enrichment & scoring (shipped)

**Description:** Local models assess visuals/text, produce deal verdicts, and compute neighbourhood-relative scores; GPU concurrency is bounded. Realizes UJ-1, UJ-3.

#### FR-7: Configurable local AI backends
Operator can select Ollama/LM Studio and model names via YAML. Realizes UJ-3.

#### FR-8: Visual + text enrichment
System attaches visual condition and sentiment-style signals from local models. Realizes UJ-1.

#### FR-9: Deal verdict
Each enriched Property presents an English deal verdict on the card/modal. Realizes UJ-1. [Correct-course 2026-07-24 BIN-64; was PT-BR.]

#### FR-10: Statistical scoring
System computes neighbourhood-relative scores and a combined score for colouring. Realizes UJ-1.

#### FR-11: Skip unchanged AI work
Re-scrapes of unchanged Listings do not re-enqueue expensive AI tasks. Realizes UJ-3.

### 4.4 Discovery UX (shipped + BIN-18 Done)

**Description:** Properties grid/map, filters, favourites, saved searches, and semantic search. Realizes UJ-1.

#### FR-12: Filterable property grid
User can filter by neighbourhood, price, score, listing type, etc., with non-blocking errors/toasts. Realizes UJ-1.

#### FR-13: Interactive map
User can browse Properties on a map and filter by viewport bbox. Realizes UJ-1.

#### FR-14: Favourites & saved searches
User can star Properties and persist named filter sets (single-tenant). Realizes UJ-1.

#### FR-15: Semantic free-text search
User can query Properties with natural language via embeddings (`q=`). Realizes UJ-1.

**Notes:** BIN-18 Done ([#16](https://github.com/felipelrib/imoveis/pull/16)); feature doc `docs/features/20-semantic-search.md`. Hygiene reconcile BIN-38 closed (no scope split) — see `docs/features/24-semantic-search-reconcile.md`.

### 4.5 Alerts & operations (shipped)

#### FR-16: Watchlist price-drop alerts
User can watch a Property and receive notifications when price drops past threshold. Realizes UJ-2.

#### FR-17: Admin & pipeline telemetry
Operator can inspect health, queues, GPU scale, schedules, and enrichment throughput. Realizes UJ-3.

### 4.6 Next phase — v0.5 product themes (planned)

**Description:** Prioritized Beyond-MVP capabilities. Exact epic order is decided after architecture + readiness; this section states product intent.

#### FR-18: Side-by-side comparison
User can select 2–4 Properties and compare attributes, scores, price/m², and price history in one view. Realizes UJ-1. `[ASSUMPTION: frontend-only over existing APIs is sufficient for v1 of comparison.]`

#### FR-19: Minimal auth & API key management
User/operator can supply API credentials via env/UI gate instead of hardcoded frontend secrets; nullable `owner` columns become meaningful for favourites/searches/watchlist. Realizes UJ-2, UJ-3.

#### FR-20: Scraper proxy rotation
Operator can enable a rotating proxy pool from YAML for scale/anti-block. Realizes UJ-3.

#### FR-21: Export & weekly digest
User can export a filtered result set (CSV/JSON) and optionally receive a scheduled “top new deals” digest. Realizes UJ-1, UJ-2.

#### FR-22: Neighbourhood polygons
System assigns Properties to neighbourhoods by spatial containment when geometry is populated, improving score cohorts. Realizes UJ-1, UJ-3.

#### FR-23: Additional platforms (backlog intent)
Product may add ZapImóveis (or others already referenced in UI sanitize lists) as first-class scrapers. `[ASSUMPTION: not committed for v0.5 until epics prioritize after FR-18–22.]`

## 5. Non-Goals (Explicit)

- Cloud-hosted multi-tenant SaaS with billing.
- Replacing local Ollama with a mandatory cloud LLM.
- Full brokerage CRM (leads, commissions, contracts).
- Guaranteed offline maps / offline OSM tileserver.
- Perfect cross-platform condo fee / IPTU normalization in v0.5.
- Automatic dead-URL pruning as a v0.5 must-have (track as debt).
- Reviving dual-model Planner/Implementer agents (ADR 0001 superseded).

## 6. Scope

### 6.1 Baseline (shipped MVP — v0.1–v0.4)

FR-1 through FR-17 as implemented and documented in `docs/features/` (+ BIN-18 semantic search Done).

### 6.2 In scope for v0.5 planning / delivery

- Formalize this PRD + architecture spine + epics (Linear v0.5 milestone / BIN-31 children).
- Prioritize and deliver a cut of FR-18–FR-22 (exact subset set in epics after readiness).
- Harness: BMad planning bridge (ADR 0003) + parallel agent workspaces (ADR 0004) already landing.
- ~~Reconcile BIN-18 documentation/status drift (BIN-38).~~ **Done** — see `docs/features/24-semantic-search-reconcile.md`.

### 6.3 Out of scope for v0.5 (deferred)

- FR-23 additional platforms unless capacity remains after FR-18–22.
- Hot-reload of `app_config.yaml`.
- Multi-city productization UX (config may allow it; product still BH-first).

## 7. Success Metrics

| Metric | Intent | Counter-metric |
|--------|--------|----------------|
| Dedup accuracy | Same physical home → one Property across platforms | Over-merge rate (distinct homes wrongly merged) |
| Alert latency | Time from price drop write → user-visible notification | Alert spam (drops below threshold, duplicates) |
| Enrichment throughput | Listings enriched / minute on single GPU | GPU OOM / queue backup hours |
| Filter → shortlist | Saved searches / favourites created per active week | Stale favourites never revisited |
| v0.5 outcome | At least one Beyond-MVP theme (FR-18–22) shipped with feature doc | Scope churn without readiness check |

`[ASSUMPTION: exact numeric SLOs are not yet instrumented as first-class dashboard KPIs; telemetry exists for pipeline health.]`

## 8. Non-Functional Requirements

- **NFR-1 Local-first:** Core enrichment and storage run on operator hardware; no required cloud AI.
- **NFR-2 Config discipline:** Runtime settings via `AppConfig` / `configs/app_config.yaml` (+ env), not scattered `os.getenv` in feature code.
- **NFR-3 Security:** No hardcoded production secrets; forbid `imoveis_secret` / `dev-secret-key` in repo; admin routes require API key when configured.
- **NFR-4 Resilience:** Circuit breakers and checkpoints keep scrapes operable under partial platform failure.
- **NFR-5 Testability:** Merge requires green CI (lint, unit, integration, contract, scrapers live gate, e2e, security).
- **NFR-6 Observability:** Pipeline telemetry and system health endpoints support unattended operation (UJ-3).
- **NFR-7 i18n:** User-facing product language (UI + AI) defaults to English; planning docs in English. Second locales (e.g. `pt-br`) deferred to AI translation (BIN-63). Correct-course 2026-07-24 (BIN-64).
- **NFR-8 Single-operator privacy posture:** BH/MG geographic focus and single-tenant personalization until multi-city / multi-profile is explicitly productized.

## 9. Open Questions

1. v0.5 priority order among FR-18–FR-22 — confirm after architecture (BIN-34) / epics (BIN-35). `[NOTE FOR PM]`
2. Is email digest (FR-21) required, or is in-app export enough for first cut?
3. Auth (FR-19): API-key gate only vs lightweight login UX for multiple local profiles?
4. Neighbourhood polygon data source for BH (FR-22) — open data vs manual GeoJSON?
5. Should ZapImóveis be explicitly scheduled in v0.5 or stay opportunistic (FR-23)?

## 10. References

- `README.md`, `docs/index.md`, `docs/architecture.md`, `docs/features/*`
- ADR 0002 (Cursor single-agent), ADR 0003 (BMad planning bridge), ADR 0004 (parallel workspaces — on main)
- Linear: project Imoveis — Deal Tracker; milestone v0.5; BIN-31 parent; BIN-18 Done; BIN-19–23 backlog
- `_bmad-output/planning-artifacts/bmad-help-session.md`
