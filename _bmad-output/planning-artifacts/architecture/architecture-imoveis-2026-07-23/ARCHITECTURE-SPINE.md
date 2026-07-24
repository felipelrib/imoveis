---
name: 'Imoveis'
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: 'hexagonal boundaries + ingestion/enrichment pipeline'
scope: 'Whole-system brownfield ratify for MVP (FR-1..17) and v0.5 themes (FR-18..22)'
status: final
created: '2026-07-23'
updated: '2026-07-23'
binds: ['FR-1', 'FR-2', 'FR-3', 'FR-4', 'FR-5', 'FR-6', 'FR-7', 'FR-8', 'FR-9', 'FR-10', 'FR-11', 'FR-12', 'FR-13', 'FR-14', 'FR-15', 'FR-16', 'FR-17', 'FR-18', 'FR-19', 'FR-20', 'FR-21', 'FR-22']
sources:
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-07-23/prd.md'
  - 'docs/architecture.md'
companions:
  - 'COMPANION-architecture-delta.md'
---

# Architecture Spine — Imoveis

## Design Paradigm

**Hexagonal (ports & adapters) for boundaries; pipes-and-filters for the ingestion/enrichment path.**

| Hexagonal role | Lives in |
| --- | --- |
| Domain | `src/core/` |
| Driving adapters (HTTP) | `src/api/` |
| Driven adapters (DB, scrapers, AI, queue, notify, metrics) | `src/adapters/` |
| Cross-cutting infra (config, DB session, Redis, logging) | `src/infra/` |
| UI client | `frontend/` |

Pipeline stages (async where noted): **scrape → normalize → dedupe → persist → score / AI enrich → alert**.

```mermaid
flowchart LR
  subgraph driving [Driving]
    API[api FastAPI]
    UI[frontend React]
  end
  subgraph domain [Domain]
    CORE[core]
  end
  subgraph driven [Driven adapters]
    SCR[scrapers]
    DB[(PostGIS)]
    Q[Celery / Redis]
    AI[local AI client]
    N[notifiers]
  end
  UI --> API
  API --> CORE
  API --> DB
  SCR --> CORE
  SCR --> DB
  Q --> SCR
  Q --> AI
  CORE -.->|ideal: no import| DB
  AI --> DB
  N --> Q
```

## Invariants & Rules

### AD-1 — Dependency direction (ideal hexagonal)

- **Binds:** `src/core/`, all FR areas that touch domain logic
- **Prevents:** Domain and adapters co-evolving into a ball of mud; parallel features importing ORM/queue into `core`
- **Rule:** `core` must not import `adapters` or `api`. Application/orchestration that needs ORM or task enqueue lives outside `core` (api, adapters, or a thin app layer). Existing `core` → adapters leaks (e.g. dedupe ORM + alert enqueue) are **debt to burn down**, not ratified. [ideal; debt]

### AD-2 — Config channel [ADOPTED]

- **Binds:** all runtime settings; FR-7, FR-19, FR-20, FR-2
- **Prevents:** Parallel features inventing `os.getenv` / hardcoded config channels
- **Rule:** Runtime settings flow only through `AppConfig` / `configs/app_config.yaml` (plus env wiring into that load path). Feature code does not call scattered `os.getenv`.

### AD-3 — Property / Listing ownership & mutation path [ADOPTED]

- **Binds:** FR-4, FR-5, FR-6, FR-16, FR-18, FR-21, FR-22; persistence + API write paths
- **Prevents:** Two meanings of “property”; identity merges or price/geo writes from random handlers; export/compare inventing alternate writers
- **Rule:** **Property** = canonical real-world home; **Listing** = platform-specific offer; price history hangs on listings. Identity/merge mutation happens only in the **dedupe path**. All Listing/Property commercial and geo fields used for containment (price, currency, platform keys, coordinates) mutate only on the **scrape → normalize → dedupe → persist** path. API/export/compare are **read-only** for those fields; snapshots are immutable projections, not second writers.

### AD-4 — AI enrichment async + GPU policy [ADOPTED]

- **Binds:** FR-7..11, FR-15; `adapters/ai`, `adapters/queue`
- **Prevents:** Inline model calls from API request threads; competing GPU concurrency schemes
- **Rule:** Model-backed enrichment runs only via the Celery **`ai`** queue. The API never calls models inline. GPU-bound concurrency is owned by the ai-worker policy + GPU semaphore (single-GPU / low-concurrency story).

### AD-5 — Scraper plugin entry [ADOPTED]

- **Binds:** FR-1..3, FR-20, FR-23 intent
- **Prevents:** One-off fetch scripts becoming a second ingestion architecture
- **Rule:** New platforms enter only as `BaseScraper` + `@register("name")` + AppConfig enablement. No first-class bypass fetchers outside the registry. Resilience (rate limits, checkpoints, circuit breakers) is part of that scraper/runtime contract — not a parallel ad-hoc HTTP stack.

### AD-6 — Auth at API edge [ADOPTED]

- **Binds:** FR-19; admin and user-gated routes; frontend
- **Prevents:** A second auth model in React diverging from the API
- **Rule:** Credential/session enforcement lives only at the **API edge** (middleware / deps). The frontend treats the API as source of truth for authz. Mechanism choice (API-key gate vs local profiles) is product-open, but **must** satisfy AD-11 once introduced — do not ship a second principal model.

### AD-7 — Local runtime topology + secrets [ADOPTED]

- **Binds:** deployment envelope; FR-7, NFR local-first
- **Prevents:** Mid-feature “deploy to cloud SaaS” forks; secret sprawl
- **Rule:** Supported shape is **Docker Compose** (Postgres/PostGIS, Redis, API, Celery scrapers + ai + beat) with **host-local AI backends** (Ollama and/or LM Studio via `LocalAIClient` / AppConfig — not required cloud SaaS AI). Secrets via env → AppConfig only; no hardcoded secrets in repo.

### AD-8 — Frontend I/O boundary [ADOPTED]

- **Binds:** FR-12..16, FR-18, FR-21 UI; `frontend/`
- **Prevents:** Browser talking to Redis/DB/Ollama directly
- **Rule:** React talks only to the FastAPI surface.

### AD-9 — Alerts on the pipeline [ADOPTED]

- **Binds:** FR-16, FR-21
- **Prevents:** UI-triggered one-off notification paths; dual notifier stacks for watchlist vs digest
- **Rule:** All outbound user notifications (price-drop, digest, future types) go through Celery + notifier adapters. Watchlist and digest are **rule sources** that emit onto **one** preference/channel registry (owned by one module), not separate notifier config trees. Threshold / noise control for a channel lives with that registry.

### AD-10 — Enrichment write ownership [ADOPTED]

- **Binds:** FR-7..11, FR-15, FR-22; Enrichment / score / neighbourhood cohort fields
- **Prevents:** Dual writers racing the same Enrichment row (geo job vs AI upsert)
- **Rule:** Enrichment mutation (scores, verdict, embeddings, neighbourhood assignment used for cohorts) has a **single ordered pipeline authority**: geo/neighbourhood assignment is a named stage that must not race AI upserts; column ownership and skip-unchanged keys stay with that pipeline, not with ad-hoc API or feature jobs.

### AD-11 — Principal / owner identity [ADOPTED]

- **Binds:** FR-14, FR-16, FR-19, FR-21; favourites, saved searches, watchlist, digest, export ACL
- **Prevents:** Auth inventing `owner_id` while digest invents a disconnected subscriber
- **Rule:** One principal model owns Favourite, WatchlistEntry, SavedSearch, DigestSubscription, and export ACL. A digest subscriber **is** that principal (or a verified contact on it). Until FR-19 lands, single-tenant null-owner remains the transitional state — new features must not invent a competing identity key.

### AD-12 — Canonical property projection [ADOPTED]

- **Binds:** FR-6, FR-12, FR-18, FR-21; grid, compare, export, digest item rows
- **Prevents:** Compare and export inventing incompatible flatteners for the same Property
- **Rule:** One API-owned versioned read DTO (or shared serializer) defines primary-listing selection, price/m², enrichment fields, and neighbourhood id/label for decisioning views. FR-18 consumes it; FR-21 serializes it; no parallel ad-hoc flatteners.

```mermaid
flowchart TB
  UI[frontend] --> API[api]
  API --> CORE[core]
  API --> AD[adapters]
  WORK[workers] --> AD
  AD --> CORE
  INF[infra] --> API
  INF --> AD
  INF --> WORK
  CORE -.->|forbidden| AD
  CORE -.->|forbidden| API
```

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Naming | Packages under `src/` match roles above; scrapers register by platform slug; Celery queues `scrapers` / `ai` |
| Data & formats | Property/Listing as AD-3; projections as AD-12; API errors non-blocking for UI toasts; AI verdicts default English (NFR-7; BIN-64) |
| Geography | Product focus BH/MG until multi-city is explicitly productized; config may allow more, UX stays BH-first |
| State & cross-cutting | Mutations per AD-3/10; config AD-2; auth AD-6/11; logging via `infra.logging`; FR-17 telemetry via `api` system/admin + existing metrics adapters — no second telemetry bus |
| Tests / merge | Green agent gates (`validate.sh`, scraper live gate when scrapers change) before merge — process companion to design co-existence |

## Stack

| Name | Version |
| --- | --- |
| Python (Docker runtime) | 3.11 (`Dockerfile.api`); local `.venv` may differ — image is source of truth for deploy |
| FastAPI | 0.139.0 in current venv; **unpinned** in `requirements.txt` (rebuilds may float) |
| SQLAlchemy | >=2.0.51 (venv 2.0.51) |
| Pydantic | >=2.13.4 (venv 2.13.4) |
| Celery | 5.6.3 in venv; **unpinned** in requirements |
| Redis (client / server) | client 6.4.0 (unpinned) / server `redis:7-alpine` |
| PostgreSQL + PostGIS + pgvector | Compose builds `Dockerfile.postgres` from `postgis/postgis:15-3.3-alpine` + pgvector `v0.8.0`; Python `pgvector` in `requirements.txt` |
| React | 19.2.8 (`frontend/package-lock.json`) |
| Vite | 8.1.5 (`frontend/package-lock.json`) |
| Local AI | Host Ollama and/or LM Studio (not containerized) |

*Stack seed refreshed 2026-07-23 on BIN-35 after BIN-34 landed on an outdated base (missed React 19 / Vite 8 upgrade and PostGIS+pgvector image).*

## Structural Seed

```text
src/
  api/         # driving HTTP
  core/        # domain (ideal: no adapter imports)
  adapters/    # scrapers, db, ai, queue, notify, metrics
  infra/       # config, db session, redis, logging
  tests/
frontend/      # React client → API only
configs/app_config.yaml
alembic/
```

```mermaid
erDiagram
  Property ||--o{ Listing : has
  Listing ||--o{ PriceInterval : history
  Property ||--o| Enrichment : scores_verdict_embeddings
  Property ||--o{ Favourite : starred
  Property ||--o{ WatchlistEntry : watched
  Principal ||--o{ Favourite : owns
  Principal ||--o{ WatchlistEntry : owns
  Principal ||--o{ DigestSubscription : owns
```

Sole system of record: **Postgres + PostGIS + pgvector** (embeddings for FR-15 semantic search). Redis is queue/cache/semaphore, not the system of record.

## Capability → Architecture Map

| Capability | Lives in | Governed by |
| --- | --- | --- |
| FR-1..3 Ingestion / schedule / checkpoint | `adapters/scrapers`, `adapters/queue` | AD-5, AD-2, paradigm pipeline |
| FR-4..6 Dedupe / price history / compare prices | `core` (+ orchestration outside), `adapters/db`, `api`, `frontend` | AD-1, AD-3, AD-12 |
| FR-7..11 AI enrich / scores / skip-unchanged | `adapters/ai`, `adapters/queue`, `adapters/metrics` | AD-4, AD-2, AD-7, AD-10 |
| FR-12..15 Discovery UX / semantic search | `api`, `frontend`, DB | AD-8, AD-3, AD-12 |
| FR-16..17 Alerts / admin telemetry | `adapters/notify`, `adapters/queue`, `api` | AD-9, AD-6, AD-11, AD-4 |
| FR-18 Comparison UI | `frontend` (+ API projection) | AD-8, AD-3, AD-12 |
| FR-19 Auth | `api` edge; env/AppConfig | AD-6, AD-2, AD-11 |
| FR-20 Proxy rotation | scraper adapters + AppConfig | AD-5, AD-2 |
| FR-21 Export / digest | `api` export + pipeline digest | AD-8, AD-9, AD-11, AD-12 |
| FR-22 Neighbourhood polygons | PostGIS + enrichment pipeline stage | AD-3, AD-10, structural seed |

## Deferred

| Item | Why it can wait |
| --- | --- |
| Parallel-worktree Compose port isolation | Harness / ADR 0004 — process, not product spine |
| Image tags, VRAM tuning, host-AI OS quirks | `docs/setup.md` owns operational detail |
| Git sync-with-main / merge hygiene | Feature-pipeline — design co-existence is AD-1..12 |
| Exact auth mechanism (API-key vs local profiles) | PRD open question; constrained by AD-6 + AD-11 |
| Digest channel (email vs in-app only) | PRD open question; constrained by AD-9 + AD-11 |
| FR-22 polygon data source (open data vs manual GeoJSON) | PRD open question; revisit when FR-22 epic starts |
| FR-23 additional platforms schedule | Product backlog; AD-5 constrains *how* |
| Burning down AD-1 debt in `core` | Implementation stories after this spine |
| Numeric success-metric instrumentation as KPIs | Product metrics — not architectural divergence points |
| Event-driven bus / CQRS | Rejected for current altitude |
| Multi-tenant cloud deploy | Explicit non-goal |
| Modular-monolith redraw | Rejected for retrofit |
| Pinning all Python deps in requirements.txt | Hygiene; note already in Stack seed |
