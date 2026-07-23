---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
status: complete
completed: 2026-07-23
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-imoveis-2026-07-23/prd.md
  - _bmad-output/planning-artifacts/prds/prd-imoveis-2026-07-23/addendum.md
  - _bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/COMPANION-architecture-delta.md
  - docs/architecture.md
excludedDocuments:
  - UX design contract (none present; brownfield pass without bmad-ux)
notes: >
  BIN-34 stack seed refreshed on this branch before extraction (React 19 / Vite 8 /
  PostGIS+pgvector). FR-1..17 are shipped baseline; v0.5 delivery focus is FR-18..22
  with FR-23 opportunistic. Linear Future seeds BIN-19..23 map to FR-18..22.
---

# Imoveis — Deal Tracker - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Imoveis — Deal Tracker, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: Operator can enable/disable platforms via config and run scrapes that normalize into Listings (pluggable scrapers with circuit breakers).
FR-2: System runs scrapes on a configured Celery beat schedule without requiring manual POST /scrape (manual scrape remains available).
FR-3: Interrupted scrapes resume from checkpoints without re-fetching completed pages.
FR-4: System merges listings within configured geo/area/text thresholds into one Property while keeping per-platform Listing rows.
FR-5: System records price intervals when a Listing price changes and exposes history via API/UI.
FR-6: User can see rent/sale prices per platform on cards/modal.
FR-7: Operator can select Ollama/LM Studio and model names via YAML.
FR-8: System attaches visual condition and sentiment-style signals from local models.
FR-9: Each enriched Property presents a PT-BR deal verdict on the card/modal.
FR-10: System computes neighbourhood-relative scores and a combined score for colouring.
FR-11: Re-scrapes of unchanged Listings do not re-enqueue expensive AI tasks.
FR-12: User can filter the property grid by neighbourhood, price, score, listing type, etc., with non-blocking errors/toasts.
FR-13: User can browse Properties on a map and filter by viewport bbox.
FR-14: User can star Properties and persist named filter sets (single-tenant today).
FR-15: User can query Properties with natural language via embeddings (`q=`). [Shipped BIN-18; hygiene reconcile BIN-38.]
FR-16: User can watch a Property and receive notifications when price drops past threshold.
FR-17: Operator can inspect health, queues, GPU scale, schedules, and enrichment throughput.
FR-18: User can select 2–4 Properties and compare attributes, scores, price/m², and price history in one view. [v0.5; Linear seed BIN-19]
FR-19: User/operator can supply API credentials via env/UI gate instead of hardcoded frontend secrets; nullable `owner` columns become meaningful. [v0.5; Linear seed BIN-20]
FR-20: Operator can enable a rotating proxy pool from YAML for scale/anti-block. [v0.5; Linear seed BIN-21]
FR-21: User can export a filtered result set (CSV/JSON) and optionally receive a scheduled “top new deals” digest. [v0.5; Linear seed BIN-22]
FR-22: System assigns Properties to neighbourhoods by spatial containment when geometry is populated, improving score cohorts. [v0.5; Linear seed BIN-23]
FR-23: Product may add ZapImóveis (or others) as first-class scrapers. [Backlog intent; not committed for v0.5 unless capacity remains.]

### NonFunctional Requirements

NFR-1: Local-first — core enrichment and storage run on operator hardware; no required cloud AI.
NFR-2: Config discipline — runtime settings only via AppConfig / configs/app_config.yaml (+ env); no scattered os.getenv in feature code.
NFR-3: Security — no hardcoded production secrets; forbid imoveis_secret / dev-secret-key in repo; admin routes require API key when configured.
NFR-4: Resilience — circuit breakers and checkpoints keep scrapes operable under partial platform failure.
NFR-5: Testability — merge requires green CI (lint, unit, integration, contract, scrapers live gate, e2e, security) via scripts/agent gates.
NFR-6: Observability — pipeline telemetry and system health endpoints support unattended operation.
NFR-7: i18n — user-facing AI verdicts default to pt-br; planning docs in English.
NFR-8: Single-operator privacy posture — BH/MG geographic focus until multi-city is explicitly productized.

### Additional Requirements

- Brownfield retrofit: no greenfield starter template; ratify existing hexagonal + pipeline layout (AD paradigm).
- AD-1: `core` must not import `adapters`/`api` (ideal); existing core→ORM/alert leaks are explicit debt — burn down via dedicated stories, do not add more.
- AD-2: Runtime settings only via AppConfig (aligns NFR-2).
- AD-3: Property = canonical home; Listing = platform offer; identity/merge mutation lives in dedupe path — not ad-hoc in API handlers.
- AD-4: AI enrichment only via Celery `ai` queue; API never calls models inline.
- AD-5: New platforms only via BaseScraper + @register + AppConfig; resilience is part of scraper contract (FR-20 proxy plugs here).
- AD-6 + AD-11: Auth/session only at API edge; one principal owns personalization + digest subscriber (FR-19 × FR-21).
- AD-7: Supported topology = Docker Compose + host-local AI (Ollama and/or LM Studio); no required cloud SaaS AI.
- AD-8: React talks only to FastAPI (no direct Redis/DB/Ollama from browser).
- AD-9: Alerts/digests fan-out via Celery + one notifier preference registry (FR-16, FR-21).
- AD-10: Single ordered pipeline write authority for enrichment (closes FR-22 × AI dual-writer risk).
- AD-12: One API-owned versioned property projection for grid / compare / export / digest (FR-18 × FR-21).
- Stack seed (refreshed): Python 3.11, FastAPI/Celery unpinned-with-venv pins, React 19.2.8, Vite 8.1.5, Postgres via Dockerfile.postgres (PostGIS 15-3.3 + pgvector v0.8.0).
- Implementation gates remain Imoveis scripts (validate.sh, finish-feature, babysit) — BMad does not replace them.
- Parallel-worktree Compose port isolation stays harness/ADR 0004 (not product epic).
- Open product questions (do not invent answers in stories): FR-18–22 priority order; FR-21 email vs in-app; FR-19 API-key-only vs local profiles; FR-22 polygon data source; FR-23 in v0.5 or not.
- Pre-epic Linear map: FR-18↔BIN-19, FR-19↔BIN-20, FR-20↔BIN-21, FR-21↔BIN-22, FR-22↔BIN-23 (promote/rewrite/supersede; do not invent parallel backlog).
- Ticket altitude (companion): cite applicable ADs, code location, forbidden patterns, special validate gates; skip class diagrams and git-rebase instructions.

### UX Design Requirements

None — no UX design contract (`ux-designs/`) included for this brownfield pass. UI stories for FR-18 (and related) will follow existing frontend patterns plus PRD assumptions until a later `bmad-ux` run if needed.

### FR Coverage Map

FR-1..FR-17: Baseline — shipped MVP (v0.1–v0.4 + BIN-18); no new delivery epic
FR-18: Epic 1 — Compare properties side-by-side
FR-19: Epic 2 — Own favourites, searches & watchlist (minimal auth)
FR-20: Epic 3 — Scale scrapes with proxy rotation
FR-21: Epic 4 — Export shortlists & weekly deal digest
FR-22: Epic 5 — Neighbourhoods by map polygons
FR-23: Deferred / Future — additional platforms (not a v0.5 delivery epic)

## Epic List

### Epic 1: Compare properties side-by-side
User selects 2–4 Properties and compares attributes, scores, price/m², and price history in one view.
**FRs covered:** FR-18

### Epic 2: Own favourites, searches & watchlist (minimal auth)
Operator/user supplies API credentials via env/UI gate; favourites, saved searches, and watchlist become owned by a principal (no hardcoded frontend secret).
**FRs covered:** FR-19

### Epic 3: Scale scrapes with proxy rotation
Operator enables a rotating proxy pool from YAML so scrapers stay resilient under block pressure.
**FRs covered:** FR-20

### Epic 4: Export shortlists & weekly deal digest
User exports a filtered result set (CSV/JSON) and can optionally get a scheduled “top new deals” digest.
**FRs covered:** FR-21

### Epic 5: Neighbourhoods by map polygons
Properties land in neighbourhoods via spatial containment when geometry is populated, improving score cohorts.
**FRs covered:** FR-22

## Linear Sync (BIN-35)

Promoted Future seeds → v0.5 epics; stories created as children.

| Epic | Linear | Stories |
| --- | --- | --- |
| Epic 1 Compare | [BIN-19](https://linear.app/felipelrib/issue/BIN-19) | BIN-41, BIN-42, BIN-43 |
| Epic 2 Auth / ownership | [BIN-20](https://linear.app/felipelrib/issue/BIN-20) | BIN-44, BIN-46, BIN-45 |
| Epic 3 Proxy rotation | [BIN-21](https://linear.app/felipelrib/issue/BIN-21) | BIN-47, BIN-48, BIN-49 |
| Epic 4 Export / digest | [BIN-22](https://linear.app/felipelrib/issue/BIN-22) | BIN-50, BIN-51, BIN-52 |
| Epic 5 Neighbourhood polygons | [BIN-23](https://linear.app/felipelrib/issue/BIN-23) | BIN-53, BIN-54, BIN-55 |

FR-23 remains deferred (no delivery epic).
## Epic 1: Compare properties side-by-side

User selects 2–4 Properties and compares attributes, scores, price/m², and price history in one view.

**FRs covered:** FR-18
**Architecture:** AD-8, AD-3, AD-12
**Linear seed:** BIN-19

### Story 1.1: Canonical property projection for decisioning

As a house-hunter,
I want the API to expose one stable property projection (primary listing, price/m², scores, neighbourhood, enrichment fields),
So that compare (and later export/digest) do not invent competing shapes.

**Acceptance Criteria:**

**Given** existing `PropertyModel` / `PropertyDetailModel` in `api`
**When** a client requests property detail and/or a batch-by-ids endpoint for 2–4 ids
**Then** responses include primary-listing price, price/m², scores, neighbourhood id/label, and enrichment fields needed for compare
**And** primary-listing selection rules live once in `api` (AD-12), not re-flattened in React
**And** contract/unit tests cover the projection; no scattered `os.getenv` (AD-2)

### Story 1.2: Multi-select properties for comparison

As a house-hunter,
I want to select 2–4 properties from the grid,
So that I can open a comparison without juggling tabs.

**Acceptance Criteria:**

**Given** the Properties page with listed cards
**When** I select between 2 and 4 properties
**Then** a clear compare affordance is enabled
**And** selecting a 5th is blocked or replaced with a non-blocking toast
**And** clearing selection returns to normal browse
**And** selection state talks only to the FastAPI client (AD-8)

### Story 1.3: Side-by-side compare view

As a house-hunter,
I want a side-by-side view of selected properties (attributes, scores, price/m², price history),
So that I can shortlist faster.

**Acceptance Criteria:**

**Given** 2–4 selected property ids
**When** I open Compare
**Then** I see columns for each property with attributes, scores, price/m², and price history
**And** data comes from the Story 1.1 projection / batch API only
**And** missing enrichment fields degrade gracefully (empty/placeholder, not a hard crash)
**And** I can exit compare and return to the grid with selection clearable

## Epic 2: Own favourites, searches & watchlist (minimal auth)

Operator/user supplies API credentials via env/UI gate; favourites, saved searches, and watchlist become owned by a principal (no hardcoded frontend secret).

**FRs covered:** FR-19
**Architecture:** AD-6, AD-2, AD-11
**Linear seed:** BIN-20
**Product note:** First cut is API-key / credential gate + single principal (not multi-profile SSO).

### Story 2.1: AppConfig-backed API credential at the edge

As an operator,
I want API auth to read credentials from AppConfig (not scattered env reads in feature modules),
So that one principal model is enforceable at the API edge.

**Acceptance Criteria:**

**Given** API_KEY / auth settings configured via AppConfig (+ env wiring)
**When** a protected route is called without a valid credential
**Then** the request is rejected at the API edge
**And** auth verification does not use ad-hoc `os.environ.get` outside the AppConfig channel (AD-2)
**And** a stable principal identity is available to downstream handlers (single-tenant OK for first cut)
**And** tests cover missing/invalid/valid credentials; no `dev-secret-key` / `imoveis_secret` in repo (NFR-3)

### Story 2.2: Frontend credential gate

As a user/operator,
I want to supply API credentials through an env-driven UI gate (or paste-once session),
So that the SPA never ships hardcoded secrets.

**Acceptance Criteria:**

**Given** the React app with no hardcoded API key in source
**When** I open a flow that needs auth
**Then** I can provide a credential stored only in client session storage (not committed)
**And** API calls attach the credential via `api.js` only (AD-8)
**And** invalid credentials surface a non-blocking error/toast
**And** pre-commit / security checks still forbid `dev-secret-key` / `imoveis_secret`

### Story 2.3: Owner-scoped favourites, saved searches & watchlist

As a user,
I want favourites, saved searches, and watchlist rows to belong to my principal,
So that nullable `owner` columns become meaningful and digests can subscribe later (AD-11).

**Acceptance Criteria:**

**Given** an authenticated principal from Story 2.1
**When** I create/list/delete favourites, saved searches, or watchlist entries
**Then** rows are written/read scoped to that principal’s `owner`
**And** unauthenticated access cannot mutate another principal’s data
**And** migrations alter watchlist (and any missing tables) only as needed for `owner`
**And** existing single-tenant data is migrated or attributed safely (documented in the PR)

## Epic 3: Scale scrapes with proxy rotation

Operator enables a rotating proxy pool from YAML so scrapers stay resilient under block pressure.

**FRs covered:** FR-20
**Architecture:** AD-5, AD-2
**Linear seed:** BIN-21

### Story 3.1: AppConfig proxy settings

As an operator,
I want the YAML `proxy` block loaded into AppConfig,
So that proxy enablement is config-driven (AD-2), not hardcoded in scrapers.

**Acceptance Criteria:**

**Given** `proxy:` in `app_config.yaml`
**When** AppConfig loads
**Then** `enabled`, `url`, `rotation_strategy` (`round_robin` | `random`), and `pool` are available on the config object
**And** unit tests cover disabled / single-url / pool modes
**And** no real proxy credentials are committed in config samples

### Story 3.2: Rotating proxy in the scraper HTTP layer

As an operator,
I want scrapers to obtain HTTP clients through a shared proxy-aware helper,
So that rotation is part of the scraper contract (AD-5), not per-platform one-offs.

**Acceptance Criteria:**

**Given** proxy enabled with a non-empty pool (or single `url`)
**When** QuintoAndar/OLX (and BaseScraper path) create HTTP sessions
**Then** requests use the selected proxy per `rotation_strategy`
**And** when `enabled: false`, behavior matches today’s direct connection
**And** platform-level `extra.proxy` either defers to the global pool or is a documented override — one behaviour, tested
**And** unit tests cover round_robin cycling and random selection without live network
**And** scraper changes pass `validate-scrapers.sh` (refresh cassettes if HTTP wiring drifts)

### Story 3.3: Operator enablement & observability

As an operator,
I want to turn proxy rotation on via YAML and see safe operational signals,
So that I can scale scrapes without guessing whether proxies are active.

**Acceptance Criteria:**

**Given** a configured pool and `proxy.enabled: true`
**When** a scrape run starts
**Then** logs/metrics indicate proxy mode is on without printing full credentials
**And** docs describe how to enable the pool
**And** disabling proxy returns to direct mode on next scrape without code changes

## Epic 4: Export shortlists & weekly deal digest

User exports a filtered result set (CSV/JSON) and can optionally get a scheduled “top new deals” digest.

**FRs covered:** FR-21
**Architecture:** AD-8, AD-9, AD-11, AD-12
**Linear seed:** BIN-22
**Product note:** Distinct from existing price-drop `send_daily_digest`. Digest channel is config-driven (email optional).

### Story 4.1: Export filtered properties (API)

As a house-hunter,
I want to export the current filtered property set as CSV or JSON,
So that I can share or archive a shortlist outside the app.

**Acceptance Criteria:**

**Given** a filter query equivalent to the Properties list
**When** I call an export endpoint with `format=csv|json`
**Then** the file/payload uses the AD-12 property projection (same primary listing, price/m², scores, neighbourhood fields as compare)
**And** export is API-owned (AD-8); no direct DB from the browser
**And** auth follows Epic 2 edge rules when enabled
**And** contract/unit tests cover both formats and empty result sets

### Story 4.2: Export from the Properties UI

As a house-hunter,
I want an Export action on the Properties page for my current filters,
So that I do not need to craft API calls by hand.

**Acceptance Criteria:**

**Given** the Properties page with active filters
**When** I choose Export CSV or JSON
**Then** the browser downloads/receives the Story 4.1 payload for those filters
**And** errors toast non-blockingly
**And** all I/O goes through `api.js` (AD-8)

### Story 4.3: Scheduled top-deals digest

As a user,
I want an optional scheduled digest of top new deals,
So that I catch good listings without opening the app daily.

**Acceptance Criteria:**

**Given** a principal subscribed to digests (AD-11; uses Epic 2 owner when available)
**When** the digest Celery beat task runs on schedule
**Then** “top new deals” are selected by a documented rule (e.g. new/high-score since last run) using AD-12 fields
**And** delivery goes through the notifier preference registry (AD-9), not a one-off UI send
**And** channel is config-driven (log/redis/email/in-app as implemented); email is optional, not assumed
**And** unsubscribing / `enabled: false` stops further digests
**And** unit tests cover selection + empty digest without live SMTP

## Epic 5: Neighbourhoods by map polygons

Properties land in neighbourhoods via spatial containment when geometry is populated, improving score cohorts.

**FRs covered:** FR-22
**Architecture:** AD-3, AD-10
**Linear seed:** BIN-23
**Product note:** Polygon source left open; stories use a GeoJSON import path.

### Story 5.1: Load neighbourhood polygons

As an operator,
I want to populate `neighborhoods.geometry` from a GeoJSON (or equivalent) seed,
So that spatial assignment has real polygons to use.

**Acceptance Criteria:**

**Given** a documented BH GeoJSON (or fixture) and import/seed command or migration path
**When** I run the load
**Then** neighbourhood rows have valid SRID 4326 polygons
**And** import is idempotent (re-run safe)
**And** docs note the open data vs manual source choice without locking a vendor in code
**And** unit/integration tests use a tiny fixture polygon set (avoid huge dumps in git)

### Story 5.2: Assign properties by spatial containment

As an operator,
I want Properties with a point location assigned to a neighbourhood via containment,
So that `neighborhood_id` reflects geography instead of brittle string fallback alone.

**Acceptance Criteria:**

**Given** populated neighbourhood geometries and Properties with `location`
**When** the enrichment/pipeline assignment stage runs (AD-10 — single ordered writer)
**Then** `neighborhood_id` is set from PostGIS containment (`ST_Contains` / equivalent)
**And** properties outside all polygons remain unassigned or keep a documented fallback
**And** assignment is not done ad-hoc from API handlers (AD-3)
**And** tests cover inside / boundary / outside cases

### Story 5.3: Scoring cohorts prefer spatial neighbourhoods

As a house-hunter,
I want statistical scores to use spatially assigned neighbourhoods when available,
So that deal colouring reflects better cohorts.

**Acceptance Criteria:**

**Given** properties with spatial `neighborhood_id`
**When** neighbourhood stats / combined scores recompute
**Then** cohorts prefer the linked neighbourhood over `props_json` string fallback
**And** properties still on string-only fallback keep working (no regression)
**And** unit/integration tests show cohort membership changes for a fixture inside a polygon
**And** no dual writer invents a second scoring path outside the pipeline (AD-10)
