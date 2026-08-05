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

**Planning regime (settled 2026-08-05):** BMad is the source of truth for planning *and* the dev loop (bmad-loop), superseding the Linear-SoR/feature-pipeline regime. ~~Linear remains the tracking mirror.~~ *[Amended later on 2026-08-05, post-epics: Linear dropped entirely (free-plan issue limit hit mid-sync) — BMad artifacts (epics.md + sprint-status.yaml) are the sole tracker; see ADR 0005.]* Wave-4 harness surgery **landed** the same day as `v0.13-fu1` (main `8f5d885` + `f2da788`): validation is primary-safe (ephemeral test stack; a live backfill and a validation cycle no longer collide), merging is the PR-less local gate (`finish-feature.sh` = validate → squash-merge → push), and the harness is BMad-only. `scripts/agent/` gates were preserved, not replaced; GitHub Actions is reduced to docs deploy + a nightly scraper drift canary (see NFR-5).

## 1. Vision

Imoveis is a **local-first** deal tracker for Brazilian real-estate listings. It continuously scrapes multiple platforms, merges the same physical property into one record, watches prices over time, and enriches listings with AI (visual condition, neighbourhood sentiment, listing-description signals, statistical deal signals) so a human can shortlist and act before a good deal disappears.

The product matters because house-hunting across QuintoAndar, OLX, ZapImóveis, and peers is fragmented: the same flat appears under different IDs, price drops are easy to miss, and raw listing copy/photos do not answer "is this actually a deal for this neighbourhood?" Imoveis turns that noise into a single score-coloured view with alerts.

**Geographic focus:** Belo Horizonte / MG is the primary product geography. SP/Campinas scrape coverage shipped (BIN-113) and is **opportunistic** — data flows, but multi-city is not yet product intent (v0.15+ candidate; see §9).

**AI posture:** local models (Ollama / LM Studio) are the default and permanent enrichment path; a **quota-bounded cloud assist** (Gemini/Gemma free tier) exists for batch backfill and is being productized in v0.13 (see §4.3, NFR-1).

**Product language:** the UI experience targets **pt-BR** (default per the 2026-08-05 UX contract — this supersedes the earlier "English default" posture; see NFR-7). The engineering rule is intact: every string lands in both `en` and `pt-BR` catalogs, canonical DB/API wire values remain English, and further locales stay additive via the add-a-locale checklist. **Deployment posture:** single-operator, privacy-preserving, runs on the user's machine (Docker + host Ollama); target surface is a **desktop browser** — no mobile/multi-surface requirement (UX contract, 2026-08-05).

**UX contract:** the frontend's design authority is `_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/` (`DESIGN.md` + `EXPERIENCE.md`, finalized 2026-08-05, merged `a9058a7`): Meia-noite palette, editorial worded verdicts, one-dashboard IA with health strip + "desde a última visita" panel, grid × map split view, detail side panel, **Favoritos** surface (starred = watched — no separate watchlist concept). v0.13 UI stories consume it; the UX pass also surfaced new product scope, folded in as FR-33–FR-38 (§4.5).

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
- **Watchlist** — Per-property subscription that triggers on price drops past a threshold. *[Amended by the UX contract, 2026-08-05: **starred = watched** — there is no separate watchlist surface; starring a Property is what subscribes it. FR-16 semantics unchanged underneath.]*
- **Favourite / Saved search** — User-starred shortlist (**Favoritos** surface: availability tracking, filterable history of gone favourites, optional-reason discard) / named filter preset (single-tenant).
- **Recheck** — On-demand or automatic single-listing availability verification against the source platform (FR-33); a blocked/failed probe is `unknown`, never `gone`.
- **Gone / voltou ao mercado** — A Listing no longer present in successful scrapes is marked gone; a reappearance clears the state and annotates price history (FR-34).
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

**Description:** With description enrichment (FR-26) landing signals on every listing and backfill (Theme A) extending them to the whole corpus, the dashboard can answer sharper questions than a single combined score. Realizes UJ-1, UJ-2. **Cut decided at epics time (2026-08-05): FR-30 + FR-32 are in; FR-31 is deferred** — worst data-availability risk (partial platform fee coverage); it stays on the debt ledger for a later wave.

#### FR-30: Price-per-m² percentile views
User sees where a Property's price/m² falls within its neighbourhood cohort (percentile on card/modal, filterable). Realizes UJ-1. `[ASSUMPTION: neighbourhood polygons (FR-22) + dual-type scoring (FR-25) give adequate cohorts; no new geo work needed.]`

#### FR-31: Total-cost-of-occupancy normalization — **deferred at epics (2026-08-05)**
Condo fee + IPTU are normalized across platforms into a comparable monthly total alongside rent/price — promoting long-carried debt into a product capability. Realizes UJ-1. `[ASSUMPTION: platform coverage of fee data is partial; the FR includes surfacing "unknown" honestly rather than imputing.]` Not in the v0.13 epic set; stays on the debt ledger.

#### FR-32: Saved-search new-match alerts
Alerts extend beyond watched-property price drops: a saved search can notify when a **new** Property matching it appears. Realizes UJ-2. `[ASSUMPTION: reuses the shipped notifier registry (FR-21) and saved searches (FR-14); no new channel work required for v1.]` *UX refinements (2026-08-05 contract): new-match alerts fire only once verdict/percentile enrichment exists; drop-alert threshold is per saved search; channel posture is email (guaranteed) + in-app + desktop push (opportunistic) — no Telegram.*

### 4.5 v0.14 — UX-contract-driven scope: FR-33–FR-38 (planned)

**Description:** The 2026-08-05 UX pass (DESIGN.md + EXPERIENCE.md) surfaced product scope beyond the v0.13 epic set — mostly backend capabilities the designed experience depends on. **Scheduled as the v0.14 wave (decided 2026-08-05)**; none is committed to v0.13, and epic/story breakdown happens at the v0.14 epics pass after v0.13 closes.

**Theme:** make the designed experience real end-to-end — availability truth (recheck, gone/resurrection, favourite-gone alerts), personal-decision surfaces (POI travel-time, sentiment filters, filter recall), and operator trust (run-history analytics).

**Exit criteria:** a starred Property's availability is verifiable on demand and watched automatically; a gone→returned Property is visible as such with annotated price history; POI travel-time bands render on the map; sentiment tags filter the grid; scraper anomalies surface with reason strings against both baselines.

#### FR-33: Listing availability verification (recheck)
On-demand per-listing recheck (`Verificar disponibilidade` in the detail panel / Favoritos) plus **automatic priority rechecks** (e.g. daily) for starred items, addressing the stale-availability frustration (property looks live in-system but is gone at the source). Safety rails are part of the FR: per-listing cooldown, a modest global recheck budget (rechecks burn the shared scraping identity), and honest tri-state results — a Cloudflare/403/timeout probe is `não foi possível verificar` (unknown), never marks gone, and never refreshes the freshness stamp.

#### FR-34: Gone/resurrection lifecycle + favourite-gone alerts
A gone Property reappearing in a coleta clears the gone state and bridges + annotates the price-history chart (`voltou ao mercado`). Favourite-gone becomes a first-class alert (on by default for starred items), and a resurrection of a previously starred Property is likewise alert-worthy. Gone heuristics are gated on **successful** runs; skip-unchanged still bumps last-seen.

#### FR-35: Personal POI travel-time layer
Named personal anchors (Igreja, Casa dos pais, …) on the map with **travel-time bands** (minutes, never km); proximity to these anchors is central to the shortlist decision. Card↔pin hover sync and explicit map-area filtering are UI-contract concerns; the FR is the POI/travel-time data capability behind them.

#### FR-36: Sentiment-dimension filters (extensible vocabulary)
Filterable sentiment/quality tags on Properties (`seguro`, `reformado`, `silencioso` as **seed suggestions, not a closed set**) built on FR-24/FR-26 signals; the filter system must handle a growing tag vocabulary.

#### FR-37: Scraper run-history behavioral analytics
Per-coleta duration and yield (processed/included/excluded/updated) compared against that scraper's **rolling baseline and a pinned long-window baseline** (so gradual drift can't rot the comparison); deviation turns the health-strip chip amber with a reason string, and "finished too early" is a first-class signal. In-app only — no external notification for anomalies.

#### FR-38: Recent-filter recall
Recently used neighbourhoods, property types, and price ranges resurface as reuse suggestions inside the filter pickers.

## 5. Non-Goals (Explicit)

- Cloud-hosted multi-tenant SaaS with billing.
- Making cloud AI **required** for any core path — the cloud assist is optional, quota-bounded, and batch-only; local enrichment is never removed (research invariant, 2026-08-05).
- Lift-and-shift of scraper, DB, or Celery/Redis to cloud free tiers — cloud may only ever hold a slim, regenerable read-model projection; scrapers must egress from the residential IP.
- Multi-city productization UX in v0.13/v0.14 (coverage stays opportunistic; v0.15+ candidate).
- Full brokerage CRM (leads, commissions, contracts).
- Guaranteed offline maps / offline OSM tileserver.
- Paid cloud AI tiers as a planning basis — v0.13 sizes against the free tier.

## 6. Scope

### 6.1 Baseline (shipped — v0.1–v0.12)

FR-1 through FR-26 as implemented and documented in `docs/features/` (58 BIN-prefixed feature docs), including all of the superseded PRD's planned scope (FR-18–FR-23).

### 6.2 In scope for v0.13 planning / delivery

- **Theme A:** FR-27, FR-28, FR-29 — cloud/local split productization. FR-28 surface decided at epics: admin-panel exposure is the target, built as slices (hardened runner control core → auth-gated admin API + panel); CLI-only remains the fallback slice.
- **Theme B:** FR-30 + FR-32 (cut decided at epics 2026-08-05; FR-31 deferred to the debt ledger).
- **UI stories consume the UX contract** (`ux-designs/ux-imoveis-2026-08-05/`) — admin backfill card, coverage telemetry, percentile presentation, saved-search alert toggles follow DESIGN.md/EXPERIENCE.md, not ad-hoc patterns.
- **Harness track (process, not FR): DONE** — landed 2026-08-05 as `v0.13-fu1` (main `8f5d885` + `f2da788`) before story execution, as gated: primary-safe validation (ephemeral test stack), PR-less local merge gate, BMad-only harness, doc surfaces rewritten.
- Architecture pass binds the cloud-assist path (AD-13 or AD-7 amendment) per sprint-change-proposal §4.2.

### 6.3 Out of scope for v0.13 (deferred)

- **FR-31** total-cost-of-occupancy normalization (deferred at epics — data-availability risk).
- **FR-33–FR-38** UX-contract-driven scope (§4.5) — **scheduled as the v0.14 wave**; not started before v0.13 closes.
- Multi-city productization (now a **v0.15+ candidate** — v0.14 carries FR-33–FR-38; revisit at v0.13 close).
- Export UI and auth/API-key management UI — **consciously undesigned** in the UX contract (export stays API/digest-only; auth stays the current key gate); Compare stays minimal/deprioritized.
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
| v0.13 outcome | Theme A shipped whole; Theme B cut (FR-30 + FR-32) shipped with feature docs | Scope churn without readiness check |

`[ASSUMPTION: numeric SLOs still not instrumented as first-class KPIs; FR-29 is the first step toward that for enrichment.]`

## 8. Non-Functional Requirements

- **NFR-1 Local-first with bounded cloud assist:** Core enrichment and storage run on operator hardware; no *required* cloud AI. The sanctioned exception is the quota-bounded, operator-triggered, batch-only cloud-assist path (Gemini/Gemma free tier) — it may accelerate backfill, never gate core function, and the local path is never removed. *(Posture change from the 2026-07-23 PRD documented per correct-course §4.1.)*
- **NFR-2 Config discipline:** Runtime settings via `AppConfig` / `configs/app_config.yaml` (+ env), not scattered `os.getenv` in feature code.
- **NFR-3 Security:** No hardcoded production secrets; forbid `imoveis_secret` / `dev-secret-key` in repo; admin routes require API key when configured; cloud API keys via env only.
- **NFR-4 Resilience:** Circuit breakers and checkpoints keep scrapes operable under partial platform failure; quota exhaustion degrades to local enrichment, not outage.
- **NFR-5 Testability:** Merge requires a green **local gate** — `scripts/agent/validate.sh all` (lint, unit, integration, contract, scrapers live gate, e2e, security) run by `finish-feature.sh`, which is the only path to `main` (validate → squash-merge → push). Validation runs against the ephemeral test stack and never touches the primary compose project — safe during a live backfill. GitHub Actions is docs deploy + nightly scraper drift canary only. *(Rewritten post-v0.13-fu1; gate contents preserved unchanged across the SoR pivot — CI was the vehicle, not the gate.)*
- **NFR-6 Observability:** Pipeline telemetry and system health support unattended operation, extended in v0.13 to enrichment coverage and backfill pacing (FR-29). Coverage is a first-class SLO on the front-door health strip (scrapers · backend/model · workers · coverage; coverage % = minimum across signal types), with detail in Admin (UX contract, resolves old Q4).
- **NFR-7 i18n:** **pt-BR is the UI default** (UX contract 2026-08-05, superseding the earlier "English default"); the engineering rule is unchanged — every string ships in both `en` and `pt-BR` catalogs, locale switchable via preference (`ui.locale` / Redis). Canonical DB/API wire values remain English. Further locales additive via `docs/i18n/add-a-locale.md`.
- **NFR-8 Geography & tenancy posture:** BH/MG primary geography with opportunistic SP/Campinas data; single-tenant personalization (nullable `owner`) until multi-city / multi-profile is explicitly productized.

## 9. Open Questions

**Answered by shipping since 2026-07-23** (kept for the record): v0.5 priority order → delivered in full; digest necessity → shipped notifier registry + export; auth depth → API-key gate shipped; BH polygon source → GeoJSON path shipped; ZapImóveis timing → shipped (BIN-127).

**Answered since finalization (2026-08-05, kept for the record):**

1. FR-28 surface → **answered at epics:** admin-panel exposure is the target, built as slices (runner control core → admin API + panel); CLI-only is the fallback slice.
2. Theme B cut → **answered at epics:** FR-30 + FR-32 in; FR-31 deferred (worst data-availability risk).
4. Coverage as SLO → **answered by the UX contract:** yes — enrichment coverage % joins the front-door health strip; detail in Admin (NFR-6).
5. FR-33–FR-38 scheduling → **answered (Felipe, 2026-08-05): the v0.14 wave** (§4.5). Milestone definition + epic breakdown when v0.14 planning opens.

**Open:**

3. Multi-city: revisit at v0.13 close — promote to product intent or keep opportunistic? With v0.14 now carrying FR-33–FR-38, promotion would target **v0.15+**.

## 10. References

- `README.md`, `docs/index.md`, `docs/architecture.md`, `docs/features/*` (58 feature docs)
- `_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/` — UX contract (DESIGN.md + EXPERIENCE.md, merged `a9058a7`); source of the FR-33–FR-38 flags and the NFR-7 pt-BR default
- `_bmad-output/planning-artifacts/epics.md` — v0.13 epic set (stories v0.13-s1.1…s2.4; Theme B cut + FR-28 surface decisions of record)
- ADR 0005 (BMad artifacts as sole tracker); `v0.13-fu1` harness surgery (main `8f5d885` + `f2da788`)
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-08-05.md` (drift analysis + §4.1 edit basis)
- `_bmad-output/planning-artifacts/research/technical-imoveis-local-vs-cloud-hybrid-stack-research-2026-08-05.md` (topology invariants)
- `_bmad-output/project-context.md` (agent rules incl. Gemma quota, Redis surfaces)
- ADR 0002 (agent workflow), ADR 0003 (BMad planning bridge), ADR 0004 (parallel workspaces)
- Superseded: `prds/prd-imoveis-2026-07-23/` (FR-1–FR-17 definitions remain of record there)
- Linear: historical archive only (milestones v0.1–v0.12 all Done; dropped 2026-08-05 per ADR 0005 — v0.13 tracked in epics.md + sprint-status.yaml)
