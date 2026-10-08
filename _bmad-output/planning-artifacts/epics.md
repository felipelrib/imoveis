---
status: final
completed: 2026-10-07
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
planningTarget: 'v0.14'
created: 2026-10-07
supersedes: 'epics-delivered-2026-10-07.md (v0.13 plan of record — Epics 1 and 3 delivered, Epic 2 partly delivered; its open items are carried into this set)'
inputDocuments:
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-10-07/prd.md'
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-10-07/addendum.md'
  - '_bmad-output/planning-artifacts/prds/prd-imoveis-2026-10-07/change-signal.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/COMPANION-architecture-delta.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/DESIGN.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/EXPERIENCE.md'
  - '_bmad-output/planning-artifacts/epics-delivered-2026-10-07.md'
  - '_bmad-output/implementation-artifacts/sprint-status.yaml'
  - '_bmad-output/implementation-artifacts/deferred-work.md'
  - '_bmad-output/planning-artifacts/NEXT-bmad-create-epics-prompt.md'
excludedDocuments:
  - 'prds/prd-imoveis-2026-07-23 and prds/prd-imoveis-2026-08-05 (superseded; FR-1–FR-38 definitions of record are cited, not re-extracted — FR-33–FR-38 text is quoted from the 2026-08-05 PRD §4.5 as the 2026-10-07 PRD directs)'
  - 'epics-delivered-2026-07-27.md (historical Epics 1–5)'
  - 'implementation-readiness-report-2026-07-23.md, implementation-readiness-report-2026-08-05.md, sprint-change-proposal-2026-08-05.md'
  - 'ux-designs/ux-imoveis-2026-08-05/review-*.md, validation-report.md (findings already folded into the spines)'
  - 'research/*.md (harness cut is recorded in AGENTS.md + ADR 0007)'
decisions: >
  Locked by Felipe on 2026-10-07 (hand-off note adopted as written):
  (1) FR-31 Total Monthly Cost is UN-DEFERRED — Tier 1 foundation; AD-3 cost columns bind.
  (2) Anchor coordinate invalidation = overlay version lock (AD-16 as written); the
  coordinate-hash alternative is rejected.
  (3) Cohort price/m² basis = fee-exclusive rent_monthly once FR-31 lands, stamped
  price_basis on metrics_scoring (headline until then), behind a characterization lock;
  the percentile pipeline story consumes that single definition and never hardcodes price.
  (4) There is NO separate v0.13 in-flight wave: every pending v0.13 item is carried into
  this set as ONE carry-over epic and re-keyed with v0.14 story keys; old v0.13 keys are
  marked superseded in sprint-status.yaml (a `done` is never downgraded).
  (5) Transit provider (PRD Q2) = AD-18: local OSRM + OpenTripPlanner 2.10 behind one
  port; cloud transit optional and off by default.
  (6) Strata is a spike (PRD §6.4), not an FR; it only flips .env.local routing values.
  (8) PRD Q5: compra-2028 is a Belo Horizonte search with no soft preferences (confirmed).
  (9) PRD Q4: home-office-capable = second enclosed bedroom OR explicit office mention (confirmed).
  (7) This file replaces the v0.13 epics.md (archived, option A); PRD §9 patched in this pass.
tracking: >
  BMad artifacts are the sole tracker (ADR 0005). This document is the plan of record;
  execution status lives in _bmad-output/implementation-artifacts/sprint-status.yaml with
  BMad-standard keys (epic-N, N-M-slug). Story ids v0.14-sN.M drive branch names
  (feat/v0.14-sN.M-…) and feature docs. Sequencing gates are recorded here once the
  stories exist (step 3) and verified against the real bmad-loop parser.
  GATES (2026-10-07): 1.2←1.1, 1.3←1.1, 1.6←1.3+1.4+1.5, 1.7←1.6, 1.8←1.2+1.7, 1.9←1.6,
  1.10←1.9; 2.2←2.1, 2.3←2.2, 2.4←2.2+1.1, 2.5←2.4, 2.6←2.5+1.2, 2.7←2.6, 2.8←2.7+1.3,
  2.9←2.8, 2.10←2.9; 3.2←3.1, 3.5←3.4+3.3, 3.6←3.2+3.3+2.2, 3.7←3.5+3.6, 3.8←3.3+2.7,
  3.9←1.8+3.7+2.7; 4.1←2.1, 4.2←4.1, 4.3←4.2, 4.4←4.2+2.8, 4.5←4.4; 5.2←5.1, 5.3←5.2, 5.4←5.1,
  5.5←1.16+5.4, 5.6←5.5, 5.7←5.4, 5.8←5.7+1.8, 5.9←5.5+1.8, 5.10←5.6+2.9; 6.1←2.2+2.5+3.3,
  6.2←6.1+2.8, 6.3←6.2. src/api/schemas.py edits are serial. 1.6 must not start before 1.5
  is done (operator step; not machine-enforced). Old-key mapping: 2-7→1.5, 2-1→1.6, 2-2→1.7,
  2-5→1.8, 2-3→1.9, 2-4→1.10, fu12+fu13→1.11. Full wave plan: section
  "Sequencing gates and Parallel work plan".
---

# imoveis - Epic Breakdown (v0.14)

## Overview

This document provides the complete epic and story breakdown for **imoveis v0.14**, decomposing the requirements from the PRD (2026-10-07) and its addendum, the Architecture Spine (AD-1..19, updated 2026-10-07) and the UX design contract (2026-08-05) into implementable stories. The v0.13 plan of record is archived at `epics-delivered-2026-10-07.md`; this is a fresh set that **carries every pending v0.13 item** as one carry-over epic so a single deliverable plan exists.

**What this version is for:** the product's primary job is now a decision engine for two concrete searches (`aluguel-2027`, `compra-2028`) run by one operator, with an AI agent (Claude Code) as the main query client and the React UI as a secondary surface.

## Requirements Inventory

### Functional Requirements

**Shipped baseline (no new stories; definitions of record in the superseded PRDs and `docs/features/`):** FR-1–FR-26 (v0.1–v0.12), FR-27–FR-29 (v0.13 Epics 1 and 3, done).

**Carried from v0.13 (in flight, re-keyed into this set):**

FR-30: Price-per-m² percentile views. User sees where a Property's price/m² falls within its neighbourhood × listing-type cohort (percentile on card and detail side panel, filterable). Cohorts come from FR-22 polygons + FR-25 dual-type scoring. Status: a per-cohort `percentile_rank` column exists since BIN-84; the pipeline story and the badge/filter story are backlog. **New binding (AD-3):** the percentile is computed on the single cohort price basis (`rent_monthly` fee-exclusive for rent cohorts once FR-31 lands, stamped `price_basis`); it never hardcodes `price`.

FR-32: Saved-search new-match alerts. A saved search notifies when a new matching Property appears; fires only once verdict and percentile exist; per-search toggle and per-search minimum-drop threshold; every alert email states the threshold that fired it; email batches into one daily window per search; the weekly digest excludes already-alerted Properties. v1 is email-only. **The in-app Alertas panel and desktop push remainder rides with FR-34's alert surface in this version.**

**v0.14 — decision engine for two searches:**

FR-41: Search Profiles as first-class product objects. Operator defines Search Profiles in versioned config (`aluguel-2027`: rent, apartment, BH, bedrooms ≥ 2 with one usable as home office, parking ≥ 1, Total Monthly Cost ≤ R$ 4.000, unfurnished; soft: lower total cost, gym in building, elevator, split-AC neutral-to-positive; horizon 2027-03. `compra-2028`: sale, BH, 3 ≤ bedrooms ≤ 4, parking ≥ 2; no soft preferences yet; horizon ~mid-2028). The system evaluates every active Property against every active profile and stores a Fit status (`fits` / `fits-pending-verification` / `fails` / `out-of-scope`) with the failing or unverified constraints named. Testable consequences:
- A profile with an unknown attribute key, an unparseable constraint or a missing listing type fails config validation at startup with the offending key named.
- Changing constraints requires a version bump; Fit statuses are re-evaluated for the new version and the previous version's statuses are retained.
- An `unknown` relevant Attribute never yields `fails`; it yields `fits-pending-verification` with the Attribute named.
- Total Monthly Cost `unknown` cannot be `fits` for `aluguel-2027`; it is `fits-pending-verification`.
- Soft preferences never change Fit status; each evaluates to `satisfied` / `not-satisfied` / `unknown`; soft score = satisfied ÷ (satisfied + not-satisfied), `unknown` excluded and reported as a count; lower complete Total Monthly Cost ranks higher within equal soft scores.
- With several active rent Listings, the lowest **complete** Total Monthly Cost decides the cap; with none complete the Property is `fits-pending-verification`; the deciding Listing is recorded.
- `out-of-scope` geography: the Property's point lies within the profile's city polygon union or its address city equals the profile city; otherwise `out-of-scope`.
- Non-goals: profiles editable from the UI; per-user profiles.

FR-39: Structured Attribute extraction with provenance. System extracts and stores, per active Property, every Attribute a profile references — bedrooms, parking, furnished, elevator, gym in building, split-AC, home-office-capable second room — plus bathrooms, pets, suites and floor, each with provenance (`scraper` / `text` / `photo` / `unknown`), using scraper structured fields first, then description text (new `attributes` task class), then Photo evidence (extension of the `visual` pass). Testable consequences:
- A `scraper` value is never overwritten by `text` or `photo`; a disagreeing lower-provenance value is stored as a conflict beside it.
- On a fixture set of ≥ 50 hand-labelled BH listings, text extraction reaches ≥ 85% exact-match on bedrooms/parking/elevator/gym/furnished and 100% schema-valid JSON after the retry policy (planning thresholds; the spike A/B calibrates them).
- `home_office_capable` is never `scraper`; it is `unknown` unless a second enclosed room is evidenced (default definition: second enclosed bedroom OR explicit office mention — PRD Q4, revisit at this story).
- A Property that fails the photo gate gets `text`/`scraper` values only; photo-derived Attributes are `unknown`, not degraded.
- Platform amenity codes map through a committed, test-covered vocabulary table; an unmapped code is logged and ignored.

FR-31: Total Monthly Cost normalization (un-deferred 2026-10-07). System computes, per rent Listing, Total Monthly Cost = rent + condo fee + IPTU/month, each component itemized, `unknown` when unpublished, `bundled` when the platform publishes an unsplittable combined figure. Sale Listings carry condo fee and IPTU/month as carrying-cost context; no total. Testable consequences:
- For the same fixture Listing on two Platforms the total agrees within the published component differences; base rent is never counted twice.
- An annual IPTU is converted to monthly with the conversion recorded; ambiguous periodicity is `unknown`, not divided.
- A missing component is `unknown`, never zero; a total with any `unknown` component is marked incomplete.
- The `aluguel-2027` cap compares against the complete total only.
- Sale Listings expose monthly condo fee and IPTU under the same rules.

FR-35: Travel time to personal Anchors. System computes, per active Property, minutes to each Anchor (igreja — Palmares; casa da Nala — Santo Antônio; casa da mãe — Planalto; Centro; aulas de música — current home, walking budget) by `car` and `transit`, and by `walk` only for Anchors declaring a walking budget, stored with provider stamp and departure assumption (default weekday 08:00 local, per-Anchor override). Map travel-time bands are a secondary UI consumer. Testable consequences:
- Anchors are versioned config beside the profiles; an Anchor without coordinates fails validation; coordinates load from a git-ignored local file; a committed file containing coordinates fails a unit test.
- Every active BH Property has, per Anchor, `car` and `transit` minutes or `unknown` with a reason (`no-provider`, `unroutable`, `outside-coverage`).
- A haversine estimate is never presented as a travel time.
- Minutes are the only unit anywhere (API, Dossier data, UI); no km field.
- Recompute happens on Property location change or Anchor version change, not per scrape.

FR-36: Sentiment facets as structured, agent-readable dimensions. System exposes named facets with an extensible vocabulary (seed: `seguro`, `reformado`, `silencioso`) derived from FR-24 neighbourhood quality, FR-26 sentiment flags and FR-39 Attributes; filterable in the API and usable as profile soft preferences; the grid filter picker is a UI consumer. Testable consequences:
- A facet value is tri-state (`yes` / `no` / `unknown`) with optional confidence in [0, 1]; filters match `yes` unless `unknown` is requested.
- The vocabulary is a committed, versioned list where each facet names its derivation rule; a new facet is a vocabulary change, not a code change; an unknown facet name in a filter returns 4xx with the allowed set.
- Each facet value states what produced it; wire names are canonical English; pt-BR labels come from the catalogs.
- Free-text flags that normalize to no facet stay flags.

FR-40: Decision data for Dossiers. System produces, per Property × Search Profile, a Fit bundle (Fit status with per-constraint checks and provenances, soft score, Total Monthly Cost breakdown, travel times per Anchor and mode, existing verdicts, price-history summary, availability state, Photo evidence reference, listing links, `unknown_count`) and inside it a Fit summary generated by a profile-aware text task class. Testable consequences:
- The bundle is complete or marks each missing part `unknown` with a reason (`not-computed` vs `unavailable`) and carries `unknown_count`.
- The Fit summary names at least one hard constraint and one unverified Attribute when any exist and never contradicts the structured status.
- Bundles for the same Property under two profile versions are both retrievable.
- With the text backend down the bundle is still served with the Fit summary `unknown`.

FR-42: Agent query surface. The agent client reads everything a Dossier needs through documented, stable, API-key-gated read endpoints: profiles and Anchors (with versions), Fit-status listings per profile (sortable by soft score, Total Monthly Cost, minutes to an Anchor, price drop, freshness), the Fit bundle per Property, a per-profile cohort summary, facets, enrichment coverage and health. Agent writes are limited to star/unstar with optional reason and trigger Recheck (default pending PRD Q7, revisit at this story). Testable consequences:
- Every Fit bundle field is reachable through `src/api/schemas.py` with contract tests; no agent path reads the DB or scrapes the UI.
- Responses carry canonical English wire values and ISO dates.
- "Everything that fits aluguel-2027 sorted by Total Monthly Cost" is one call.
- The cohort summary returns in one call: counts per Fit status, price/m² distribution (median, p25, p75) per neighbourhood for the `fits` + `fits-pending-verification` cohort, and the distribution of minutes per Anchor and mode.
- ≤ 2 s per Fit bundle; ≤ 5 s for a 200-row listing or a cohort summary (planning numbers).
- Transport is the existing REST API, documented in `docs/api.md` with example calls; an MCP wrapper is later.

FR-33: Listing availability verification (Recheck). On-demand per-listing recheck plus automatic priority rechecks for starred items, with a per-listing cooldown, a modest global recheck budget and tri-state results. Testable consequences: a starred Property is rechecked at least daily; a Property within its cooldown is not re-probed; a 403/Cloudflare/timeout probe yields `unknown` and leaves the freshness stamp untouched; the daily global budget is config-driven and never exceeded.

FR-34: Gone/resurrection lifecycle + favourite-gone alerts. Testable consequences: a Listing absent from N consecutive **successful** coletas of its Platform (N config-driven) becomes gone; a Platform outage never marks Listings gone; a reappearance clears gone, annotates the price-history series and fires an alert if the Property was starred; the gone→returned transition is visible in the Fit bundle's availability state. Carries the FR-32 UI remainder: a gone-favourite alert is visible in-app (Alertas) without opening email; desktop push is opportunistic.

FR-37: Scraper run-history behavioral analytics. Testable consequences: per coleta, duration and yield (processed/included/excluded/updated) are stored; deviation beyond a config-driven band from the rolling baseline **or** the pinned long-window baseline produces a reason string; below the calibration count the state is `calibrating`, not ok; no external notification fires.

FR-38: Recent-filter recall. The last N neighbourhoods, property types and price ranges used are offered in the pickers; cleared with the filter reset. UI-only; lowest priority in the wave.

**Spike (decision, not an FR):**

SPIKE-1: Strata as local text backend (PRD §6.4). A/B Strata (via the `lmstudio` backend, `.env.local` routing values only) against `qwen2.5vl:7b` on ~50 hand-labelled BH listings: Attribute exact-match, JSON validity (first try and after retry), seconds per Property with Ollama co-resident. First step: check host RAM (≥ 32 GB, 64 recommended) and ~80 GB free NVMe. Verdict (adopt / reject / defer) with the numbers recorded under `planning-artifacts/research/` and the ledger. `visual` and `embedding` stay on Ollama in every outcome. Time-boxed; runs before the FR-39 text-extraction stories (PRD Q6 default).

**Priority tiers (what slips first):** Tier 1 — FR-41, FR-39, FR-31, FR-35 (`car`), FR-40, FR-42, FR-33, SPIKE-1. Tier 2 — FR-35 (`transit`, map bands), FR-36, FR-34, FR-37, FR-38, the FR-32 Alertas/push remainder.

### NonFunctional Requirements

NFR-1: Local-first with bounded cloud assist — binding. Operator hardware is AMD RX 7900 XT 20 GB + Ollama; any new text backend is local and routed through `enrichment_routing`; the committed config stays all-local; cloud assist is batch-only backfill. No cloud service becomes required, for enrichment or for routing.

NFR-2: Config discipline — runtime settings only through `AppConfig`; Search Profiles and Anchors are `AppConfig`-loaded versioned files in `configs/`, validated at startup. Personal coordinates load from a git-ignored local file; only their schema is committed.

NFR-3: Security — no secrets in the repo; the agent client authenticates with the same API key; no new auth surface.

NFR-4: Resilience — a routing-provider or text-backend outage degrades to `unknown` fields, never to a failed bundle; circuit breakers and checkpoints keep scrapes operable.

NFR-5: Testability — merge requires the green local gate. *(PRD text names `validate.sh` via `finish-feature.sh`; since the 2026-10 harness cut (ADR 0007) the gate is `scripts/agent/validate.py` (tiered) and the merge path is `scripts/agent/ship.py`, with the push re-checked by hook.)* Adds: Attribute extraction and Total Monthly Cost ship with labelled fixture sets; FR-42 endpoints ship with contract tests.

NFR-6: Observability — coverage telemetry (FR-29) gains per-Attribute, per-Anchor-mode and total-cost completeness rows; the Fit-status distribution per profile is a reportable figure.

NFR-7: i18n — pt-BR UI default, every string in both `en` and `pt-BR` catalogs; facet names, Attribute keys, Fit statuses and provenance values are canonical English on the wire with pt-BR catalog labels.

NFR-8: Geography & tenancy — BH primary, single-tenant nullable `owner`.

NFR-9: Agent-readability (new) — every operator-facing decision datum is available as structured, documented JSON with stable field names and explicit `unknown` semantics; no datum exists only as rendered UI. Breaking changes to FR-42 endpoints bump a documented API version.

NFR-10: Provenance & honesty (new) — every derived fact (Attribute, cost component, travel time, facet) carries where it came from and when; conflicts are retained; nothing is imputed.

### Additional Requirements

**No starter template** — brownfield; all work lands in the existing `src/` hexagonal layout.

**Architecture decisions binding story design (spine AD-1..19):**

- **AD-1:** new `core` modules (`core/attributes.py`, `core/fit.py`, cost and travel rules) are pure from day one — no adapter imports, no lazy imports.
- **AD-2 / AD-16:** one AppConfig loader, extended with sibling-file include for `configs/search_profiles.yaml`, `configs/anchors.yaml`, `configs/attribute_vocabulary.yaml`, `configs/facets.yaml`; each object carries an integer `version` that is its only invalidation key; these files are not env-overridable (unit test). Coordinates live only in git-ignored `configs/anchors.local.yaml`, merged by Anchor id; each overlay entry repeats the Anchor `version` and the loader fails when it differs (overlay version lock). Coordinate validation is enforced only when `travel_time.enabled` is true (committed default `false`). The suite uses `src/tests/fixtures/anchors.local.yaml`. A unit test fails if the committed anchors file carries `lat`/`lon` or `.gitignore` lacks `configs/anchors.local.yaml` and `data/routing/`. Attribute keys, types and allowed provenances are an enum in `core/attributes.py`; YAML maps onto keys and never mints them. A vocabulary bump is applied by a `scrapers`-queue remap task over stored `props_json` / `raw_json`.
- **AD-3:** cost is typed columns on `property_listings`, written only on the scrape → normalize → dedupe → persist path: `rent_monthly` (unbundled), `condo_fee_monthly`, `iptu_monthly`, `iptu_periodicity_source`, `fees_bundled`, `total_monthly_cost`, `cost_complete`. Legacy `price` / `base_price` are never inputs to the total. Cohort price basis = `rent_monthly` once FR-31 lands, stamped `price_basis` on `metrics_scoring` (`headline` until then); the `scoring.py` change ships behind a characterization lock.
- **AD-4 / AD-13:** no model call from an API thread; local GPU work only on the `ai` queue under the one semaphore (a co-resident Strata is a semaphore re-tune, not a second scheme); cloud only on the backfill path under the single pacer.
- **AD-6 / AD-11:** the agent uses the existing API key and resolves to the single principal; star reason is a nullable `favourites.reason`; Recheck is one principal-scoped route shared by UI and agent, audited in `admin_audit`; no actor/agent column.
- **AD-9:** gone-favourite and resurrection alerts ride the one notifier preference registry.
- **AD-10:** the enrichment authority is the only writer of `text`/`photo` Attribute rows, `property_facets` values and `fit_summary`.
- **AD-12:** one API-owned projection; exactly one `deciding_listing_id` with `deciding_rule` ∈ {`lowest-complete-total`, `lowest-headline-price`}; the Fit bundle and cohort summary are assemblies of persisted rows; read-time aggregation is allowed, read-time per-Property derivation is not; every missing part is `unknown` with a reason.
- **AD-14:** `property_attributes`, one row per (property, key, provenance, source) with typed source columns; `unknown` is the absence of current rows; conflicts are rows; resolution is implemented once in `core.attributes.resolve()` (no SQL view), precedence `scraper` > `text` > `photo` with a deterministic intra-provenance tie-break; staleness is a read-time predicate; rows are never deleted by feature code; legacy columns become row-backed and are a fallback only when no row exists.
- **AD-15:** `properties.gallery_fingerprint` = sha256 of sorted normalized URLs, persisted on the persist path; the fuzzy-merge path applies the same guard as the exact path (BIN-146 follow-up — **prerequisite of FR-39**); evidence set = content hashes of the files fed to the model, immutable per fingerprint directory; every photo fact is stamped; one visual candidate SQL fragment in `adapters/db` shared by backfill runner, selective rerun and coverage (`ai_score IS NULL` retired as a candidate key); legacy flat image directories are ignored; fix the MD5/SHA-256 docstring drift here.
- **AD-17:** `EnrichmentTaskClass` gains `attributes` and `fit_summary`; photo Attributes ride `visual`; the `stages` string literals are retired for `frozenset[EnrichmentTaskClass]` with per-class skip keys and one dependency table in `core` (`visual` → `attributes` → facets → `deal_verdict` → `fit_summary`); one Pydantic schema per text class is both validator and `json_schema`; the backfill runner's scope is derived per class from the routing map; `LMStudioClient` reaches parity (`response_format`, configurable `max_tokens`, `generate()`) before any production `lmstudio` route.
- **AD-18:** `property_travel_times` at grain (property, anchor id, anchor version, mode, departure assumption) → minutes or `unknown` + reason (adds `provider-error`); one `TravelTimeProvider` port and one `travel_time` config section; `car`/`walk` by self-hosted OSRM v26.10 (one `osrm-routed` per profile), `transit` by OpenTripPlanner 2.10 through the GTFS GraphQL API (`planConnection`; REST `/plan` no longer exists); compose `routing` profile, data under git-ignored `data/routing/`; cloud transit optional and off; recompute is a beat job over stale rows on the `scrapers` queue; the Anchor endpoint never returns coordinates and coordinates never appear in logs (schema test + logging-filter test).
- **AD-19:** `core/fit.py` is a pure function over persisted facts; `property_fit_status` at grain (property, profile id, profile version), history retained, carries `fit_summary`; fact writers never enqueue Fit — a beat sweep on `scrapers` selects rows where `max(input updated_at)` > `evaluated_at` (every fact table feeding Fit carries `updated_at`); `fit_summary` is enqueued on `ai` after the row commits; reads use the loaded profile version (older through `?version=`).
- **Facets convention:** `property_facets` written only by the facet stage (enrichment order and inside the fit sweep), skip key `inputs_hash`.
- **FR-37 storage:** durable `scraper_runs` table written by the existing `_record_scrape_run` seam.
- **API version scheme:** decided at the FR-42 story — one scheme for all routes, never `/v1` for new endpoints only.

**Prerequisite (foundation) stories the spine makes explicit — mostly file-disjoint:**

- BIN-146 fuzzy-merge gallery guard + `properties.gallery_fingerprint` + normalized-URL fingerprint (AD-15).
- `stages` literals → `frozenset[EnrichmentTaskClass]` scope with per-class skip keys and the dependency table; backfill scope derived from the routing map (AD-17).
- `LMStudioClient` parity (AD-17; also the Strata spike pre-work).
- AppConfig sibling-file include, overlay version check, `travel_time` section, anchors coordinate + `.gitignore` pin tests, fixture overlay (AD-16, AD-18).
- Migrations: `property_attributes`, `property_facets`, `property_travel_times`, `property_fit_status`, `scraper_runs`, `property_listings` cost columns.
- The shared visual candidate SQL fragment (AD-15).

**Sequencing constraints to encode as gates:**

- Foundation before consumers: migrations + config loader before the FR-39 / FR-41 / FR-35 stories.
- Percentile story ← AD-3 price-basis story (FR-31) + corpus repair (old 2-7) + DW-32.
- `src/api/schemas.py` edits stay serial across stories (one shared contract surface).
- Strata spike before the FR-39 text-extraction stories.
- Nothing in the suite depends on OSRM, OTP, Ollama, Strata or the operator overlay (in-repo fakes behind the ports).

**v0.13 carry-over inventory (one epic; re-keyed; a `done` is never downgraded):**

- Open Epic 2 stories: 2-7 corpus repair (`awaiting-operator`: operator runs `migrate-primary.sh`), 2-1 cohort percentile pipeline, 2-2 percentile badge + filter, 2-3 saved-search new-match detection, 2-4 saved-search alert management UI, 2-5 detail side-panel migration. Old gates: 2-1 ← 2-7 + DW-32; 2-2 ← 2-1; 2-3 ← 2-1; 2-4 ← 2-3; 2-5 ← 2-2 (2-6 is done).
- Open retro action items: `epic-1-retro-item-1-escalation-reverification`, `epic-1-retro-item-5-ledger-budget-per-epic`, `epic-3-retro-item-1-operator-actions-batch-per-wave`, `epic-3-retro-item-2-followup-review-flag-disposition`, `epic-3-retro-item-3-dw32-drain-before-epic-2`.
- Backlog follow-ups: `v0.13-fu12` plural-agreement sweep (dashboard keys), `v0.13-fu13` toast / compare-bar bottom strip. (`v0.13-fu14` is already `done` — moot since `setup-worktree.sh` was retired by ADR 0007 — and is **not** carried.)
- Open deferred-work ledger entries (21): DW-8, 9, 10, 12, 13, 14, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 30, 32, 34 — bundled by surface into a few stories or a sweep, not 21 stories. DW-32 and 2-7 gate the percentile story. **Each entry is re-verified against the post-harness-cut tree before it is bundled** (ADR 0007 retired scripts some entries cite; `scripts/start.sh` and `scripts/agent/migrate-primary.sh` still exist, so DW-32 and DW-8 remain live).

**Process requirements:**

- Gate and merge: `scripts/agent/validate.py` (tier chosen from the diff) and `scripts/agent/ship.py`; `bmad-loop/<run>/<story>` branches are merged by the orchestrator, never shipped by hand.
- Domain gates run by path: scrapers → cassette suite + live dry-run; AI prompts/clients → Ollama golden tests; `alembic/` → alembic check; API schema changes keep `src/api/schemas.py` and `src/tests/contract/` in sync.
- Primary DB migration is the operator step `bash scripts/agent/migrate-primary.sh`; this wave adds several migrations, so operator actions are batched per wave (epic-3 retro item 1).
- Risk-tiered testing: TDD for `src/core/` and scoring math; oracle-first for scrapers; characterization lock before changing brownfield SQL / dedupe / projection.
- Feature doc per story from `docs/features/_template.md`; conventional commits; every `fix:` ships a regression test.
- The wrap-up must include a Parallel work plan (waves, gates, start-here set, do-not-parallelize list) and the gates go into this file.

### UX Design Requirements

Extracted from the UX design contract `ux-designs/ux-imoveis-2026-08-05/` (DESIGN.md = visual identity and tokens; EXPERIENCE.md = IA, behavior, states). The contract predates the 2026-10-07 PRD: it has no specification for Search Profiles, Fit status, Attributes, Total Monthly Cost or Dossiers, which is consistent with the PRD making the UI a secondary surface ("no new screens"). UX-DR numbers 1–13 are kept stable because carried stories cite them.

**Foundation (bind every UI story in this set):**

UX-DR1: Meia-noite design tokens. All UI work uses the DESIGN.md token set — colors including blend variants, two type families (serif for price + neighbourhood name only), tabular numerals for all numbers, radii scale with no pills, 4-based spacing. Dark-only.

UX-DR2: pt-BR-default UI. Every string lands in both `en` and `pt-BR` catalogs; wire enums stay English; "coleta" is the user-facing word for a scrape run; the admin surface is **Operações**.

UX-DR3: Honest absence and no meters. No progress bars anywhere; no blocking spinners; null renders as absent; errors are non-blocking bottom-anchored toasts, max two stacked.

UX-DR4: Detail-surface posture. Right-side panel over a partial scrim, map rail visible, one level deep, `Esc` closes; map viewport, grid scroll and filter state survive refreshes and panel open/close.

**Delivered in v0.13 (pattern of record, no new story):**

UX-DR5: Backfill card (Operações) — delivered in story 1.6.

UX-DR6: Coverage display as text percentages only — delivered in story 1.6; **the pattern binds the NFR-6 coverage rows added in this version** (per-Attribute, per-Anchor-mode, cost completeness, Fit-status distribution).

UX-DR7: Front-door health-strip slice (backfill chip + `Cobertura de IA N%`) — delivered in story 1.6.

**Carried surfaces (FR-30):**

UX-DR8: Percentile microcopy hard rules. Badge `entre os 25% mais baratos`; sentence `entre os 25% mais baratos do bairro`, naming the cohort type on dual-type Properties (`…dos aluguéis do bairro` / `…das vendas do bairro`); never `P25`, "percentil" or `≤`; every phrasing makes lower-price-is-better explicit.

UX-DR9: Percentile badge visual. `price-drop` ink on `price-drop-tint-12` with `price-drop-tint-35` border, small radius, right-aligned on the serif price line; absent entirely when suppressed.

UX-DR10: Percentile filter control. `Preço no bairro` select in the Filtros panel (`entre os 25% mais baratos` / `entre os 50% mais baratos` / `qualquer preço` default); active value is one chip under the 2-line ceiling; cohorts are per listing type and switching tipo re-evaluates.

**Carried surfaces (FR-32):**

UX-DR11: Enrichment-gated alerts. New-match alerts fire only once verdict and percentile exist; an alert click never lands on `análise de IA pendente`.

UX-DR12: Channel posture and batching. Email is the guaranteed interrupt; in-app and desktop push are opportunistic; no Telegram; email new-match alerts batch into one daily window per search; the weekly digest excludes already-alerted Properties.

UX-DR13: Saved-search row. `surface-card` rows with hairline separators; name in body type, filter summary in meta type; per-search notify toggle plus inline minimum-drop threshold; no global threshold; every alert email states the threshold that fired it (`queda de R$ 240 — seu mínimo: R$ 100`).

**New in this set — availability (FR-33, FR-34):**

UX-DR14: Recheck control. `Verificar disponibilidade` in the detail side panel and on Favoritos rows; in progress renders inline `verificando…` on the button and blocks nothing; the per-listing cooldown (`verificado há 20 min`) and the global budget are surfaced in the button state.

UX-DR15: Recheck result states. `disponível` / `indisponível` / `não foi possível verificar`, each with its own timestamp (`verificado às 21:14` / `verificação falhou`); the unknown state is visually distinct from available and never refreshes the freshness stamp; `indisponível` flips the card to the gone treatment immediately with a toast `anúncio saiu do ar`.

UX-DR16: Gone treatment. Rust italic note per listing type — `provavelmente alugado — sem atualização há N dias` (aluguel) / `provavelmente vendido — …` (venda), dual-type follows the primary listing; photo desaturated (`grayscale ~0.7, brightness ~0.75`), caption at ~65% opacity, no verdict shown; map point hollow and desaturated; excluded from the default grid and visible via filter; the map legend gains a gone entry when the gone filter is active.

UX-DR17: Voltou ao mercado. A reappearing Property clears the gone state; the price-history chart bridges the gap with a dashed segment and an annotation, never silently interpolated; the chart keeps platform-neutral inks, no area fills.

UX-DR18: Degraded platform is not gone. Cards of a circuit-broken Platform show `plataforma sem coleta há N dias` instead of the gone treatment; the health chip reflects the degraded Platform.

UX-DR19: Favoritos availability stamps. Every Favoritos row carries `disponibilidade verificada há Xh` or `última verificação falhou` (own amber state); a failed batch never wears a verified stamp; rows keep comparable columns (price, verdict, percentile, R$/m², bairro).

UX-DR20: Favoritos history and unstar reason. Default view is live favourites; the `mostrar indisponíveis` filter reveals gone favourites, each dated with when it left the market, and unstarred-with-reason favourites with the reason shown; unstar is one click with an **optional** reason, never mandatory (backed by the nullable `favourites.reason`, AD-6 — the same field the agent's star reason uses).

**New in this set — alert surface (FR-32 remainder, FR-34):**

UX-DR21: Alertas panel. Top-nav bell; hairline-separated rows with a type icon in the semantic ink (green drop, accent new-match, rust gone), property line and timestamp (`há 2h`) in `text-muted`; unread rows `text-primary`, read rows `text-secondary`; click opens the detail side panel and marks the alert read; rows are history and persist after the Property changes state; empty state `Nenhum alerta por enquanto.`

UX-DR22: Favourite-gone and resurrection alerts. Favourite-gone is on by default for starred items and fires email + desktop push; a `voltou ao mercado` resurrection of a previously starred Property is alert-worthy; desktop push only fires while the browser runs, so nothing critical rides on it alone.

**New in this set — operator trust (FR-37):**

UX-DR23: Per-scraper health chips. One chip per scraper on the Painel health strip: ok = green dot + last-run recency (`QuintoAndar · há 2h`); anomaly = `health-warn` dot with an italic reason string (`OLX: coleta 5× mais rápida que a mediana`), never a bare warning; calibrating = `calibrando baseline (3/10 coletas)` as a distinct state, not ok-green; chips are read-only and click through to Operações. The contract also specifies a **missed-cadence** state (`sem coleta há 26h (esperado: a cada 6h)`) that FR-37's testable consequences do not name — confirm in or out at epic design.

UX-DR24: Run-history table (Operações). Sans, tabular numerals, hairline row separators only; columns for duration, yield (processed/included/excluded/updated) and deviation as signed text against both the rolling and the pinned baseline; anomaly rows carry the italic `health-warn` reason string; calibrating rows use `pending`; no sparklines, no bars.

**New in this set — decision surfaces consumed by the UI (FR-35, FR-36, FR-38):**

UX-DR25: Travel time on the map. Travel-time bands in minutes, never km; dashed band outline in the POI colour with a solid label chip; teardrop POI pins with labeled scrim capsules in `poi-pin`. **Conflict to resolve at epic design:** AD-18 forbids Anchor coordinates in any API response, so the contract's pins and bands cannot be drawn from the API as specified. The contract's Anchor names (Casa dos pais, Casa da namorada) are superseded by the PRD's five Anchors.

UX-DR26: Facet filter picker. Bairro-style searchable typeahead picker for sentiment facets; `seguro` / `reformado` / `silencioso` are starting suggestions, not a closed set; suggestions live inside the picker, not the bar; active chips collapse (`Savassi +3` pattern) under the hard 2-line ceiling, then `Filtros (N)`.

UX-DR27: Recent-filter recall. Recently used neighbourhoods, property types and price ranges resurface as reuse suggestions inside the filter pickers; cleared with the filter reset.

**Contract items deliberately not extracted (superseded or out of this version's scope):**

- **POI management CRUD form in Operações** — superseded by AD-16 (Anchors are versioned config with a git-ignored coordinate overlay; no UI editor).
- **Since-panel** (`novos desde a última visita` / `quedas` / `saíram do ar`, 2-minute reset) — no FR in this version covers it; the PRD allows no new screens.
- **Dedupe stats with record differences, verdict explainability expansion, optimistic dismiss + `descartados` view, cold-load skeletons, grid-fetch / map-tile failure states** — contract items with no FR in this wave.
- **Detail-panel fields for Total Monthly Cost and Attributes** (PRD §6.3 allows them) — the contract has no spec; if a story adds them it applies UX-DR1–4 and shows provenance and `unknown` honestly. No new UX-DR is invented here.

### FR Coverage Map

FR-1–FR-29: Shipped baseline — no epic in this set.
FR-30: Epic 1 — cohort price/m² percentiles on the single AD-3 price basis; badge, filter, panel sentence.
FR-31: Epic 1 — Total Monthly Cost columns on the persist path; cohort price-basis change behind a characterization lock.
FR-32: Epic 1 — saved-search new-match alerts, email v1, per-search toggle and threshold. Remainder (Alertas panel, desktop push): Epic 5.
FR-33: Epic 5 — availability Recheck (on-demand + daily for starred, cooldown, global budget, tri-state).
FR-34: Epic 5 — gone / resurrection lifecycle, favourite-gone and resurrection alerts, in-app alert surface.
FR-35: Epic 4 — minutes to Anchors: car + walk (OSRM), transit (OTP), sort and cohort distribution, map consumer.
FR-36: Epic 6 — facets from a committed vocabulary, API filter, profile soft preferences, grid picker.
FR-37: Epic 5 — scraper run history, baselines, reason strings, calibrating and missed-cadence states.
FR-38: Epic 6 — recent-filter recall in the pickers.
FR-39: Epic 2 — attribute enum, `property_attributes`, resolver, `scraper` provenance through the amenity vocabulary. Epic 3 — `text` provenance (`attributes` class) and `photo` provenance (visual extension, evidence stamps).
FR-40: Epic 2 — Fit bundle projection. Epic 3 — Fit summary (`fit_summary` class).
FR-41: Epic 2 — Search Profiles as versioned config, `core/fit.py`, `property_fit_status`, fit sweep.
FR-42: Epic 2 — agent read endpoints, star reason, cohort summary, contract tests, `docs/api.md` agent section. Extended by Epic 4 (Anchor endpoint, sort by minutes), Epic 5 (principal-scoped Recheck route) and Epic 6 (facet filter).
SPIKE-1: Epic 3 — Strata A/B, verdict recorded.

**Decisions taken at epic design (Felipe, 2026-10-07):**

- FR-31 lives in Epic 1: it gates the percentile story and both change `scoring.py` behind the same characterization lock; Epic 2 depends on that one story.
- Map travel time (UX-DR25 vs AD-18): **no Anchor pins and no drawn bands.** The map and cards show minutes to a selected Anchor and can filter by a maximum, using only the minutes the API returns. AD-18 is not amended; Anchor coordinates stay off the wire.
- Missed-cadence health chip is **in** FR-37's scope (a scraper that stops running turns amber), as an acceptance criterion of the run-analytics UI story.
- Since-panel stays out of this version.

## Epic List

### Epic 1: Deal intelligence, finished (v0.13 carry-over + FR-31)

Felipe sees what a flat really costs per month (rent, condo, IPTU itemized or honestly `unknown`), sees where its price/m² sits in its neighbourhood cohort on one comparable basis, gets saved-search emails for new matches that arrive decidable, and opens the detail side panel the contract specifies. Every pending v0.13 item lands here so one plan exists: the corpus repair, the open deferred-work ledger bundled by surface, the two UI follow-ups and the open retro action items.

**FRs covered:** FR-31, FR-30, FR-32 (email v1)
**NFRs in play:** NFR-1, NFR-4, NFR-5, NFR-6, NFR-7, NFR-10
**Governed by:** AD-3 (cost columns, single price basis), AD-10, AD-12, AD-9, AD-11, AD-8, AD-13 (runner debt); UX-DR1–4, UX-DR8–13
**Carries:** old stories 2-7, 2-1, 2-2, 2-3, 2-4, 2-5; `v0.13-fu12`, `v0.13-fu13`; DW-8, 9, 10, 12, 13, 14, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 30, 32, 34; retro items epic-1-item-1, epic-1-item-5, epic-3-item-1, epic-3-item-2, epic-3-item-3

### Epic 2: Ask the agent which listings fit

Felipe asks Claude Code "what fits aluguel-2027?" and gets an answer read from the system: both Search Profiles are versioned config, every active Property carries a Fit status per profile with the failing or unverified constraints named, and the agent can list, sort and filter candidates, fetch a Fit bundle and a cohort summary, and star with a reason — all through documented, contract-tested read endpoints. Attributes come from scraper fields and the amenity vocabulary in this epic; anything only text or photos can prove (home office, split-AC) is `unknown` and yields `fits-pending-verification`. Realizes UJ-5 and UJ-6 on scraper-provenance data.

**FRs covered:** FR-41, FR-39 (scraper provenance), FR-40 (Fit bundle), FR-42
**NFRs in play:** NFR-2, NFR-3, NFR-5, NFR-6, NFR-9, NFR-10
**Governed by:** AD-1, AD-2, AD-16, AD-14, AD-19, AD-12, AD-6, AD-8, AD-11, AD-3
**Depends on:** Epic 1's FR-31 story (cost columns)

### Epic 3: Claims backed by evidence

Felipe can trust a "2 quartos, elevador, academia, cabe um escritório" claim because he sees where each part came from: Attributes are extracted from listing text and from photos with provenance, conflicts with scraper values are kept visible, photo facts are stamped with the evidence they read, and each Fit bundle carries a profile-aware Fit summary. The Strata spike settles the local text backend before the text extraction is built. Realizes UJ-7.

**FRs covered:** FR-39 (text and photo provenance), FR-40 (Fit summary), SPIKE-1
**NFRs in play:** NFR-1, NFR-4, NFR-5, NFR-6, NFR-10
**Governed by:** AD-14, AD-15, AD-17, AD-10, AD-4, AD-13
**Depends on:** Epic 2 (attribute store, resolver, fit rows)

### Epic 4: Minutes to my places

Felipe knows how far each candidate is from his life: every active BH Property has car, transit and walk-budget minutes to each Anchor or an honest `unknown` with a reason, the agent sorts candidates by minutes to a named Anchor, the cohort summary reports the distribution, and the map and cards show minutes to a selected Anchor. Coordinates never leave the box.

**FRs covered:** FR-35
**NFRs in play:** NFR-1, NFR-2, NFR-4, NFR-6, NFR-10
**Governed by:** AD-18, AD-16, AD-7, AD-12, AD-8; UX-DR25 as amended (no pins, no drawn bands)
**Depends on:** Epic 2 (config loader sibling files, fit sweep, agent listing)

### Epic 5: Listings that are still real

Felipe never plans a visit around a dead listing: starred Properties are rechecked daily and on demand with honest tri-state results, gone and returned listings are tracked and annotated, favourite-gone and resurrection alerts reach him in-app as well as by email, and a scraper that misbehaves or stops running says so with a reason. Realizes SM-6.

**FRs covered:** FR-33, FR-34, FR-37, FR-32 (Alertas panel + desktop push remainder)
**NFRs in play:** NFR-4, NFR-6, NFR-7
**Governed by:** AD-5, AD-3, AD-6, AD-9, AD-12, AD-14 (inactive Listing ⇒ stale `scraper` rows); UX-DR14–24
**Depends on:** baseline, plus two single-story links — Story 5.5 ← 1.16 (audited principal) and Story 5.10 ← 2.9 (`favourites.reason`); its availability state plugs into Epic 2's bundle

### Epic 6: Filter by quality

Felipe and the agent can filter and rank by quality dimensions — `seguro`, `reformado`, `silencioso`, extensible by a vocabulary change — each stating what produced it, usable as profile soft preferences; recently used filters resurface in the pickers.

**FRs covered:** FR-36, FR-38
**NFRs in play:** NFR-2, NFR-7, NFR-9, NFR-10
**Governed by:** AD-16, AD-10, AD-19, AD-12; facets convention; UX-DR26, UX-DR27
**Depends on:** Epic 2 (resolver, fit sweep); richer after Epic 3 (text and visual inputs)

**Epic dependencies:** Epic 2 ← Epic 1 (FR-31 story only). Epics 3, 4 and 6 ← Epic 2. Epic 5 ← baseline, plus 5.5 ← 1.16, 5.9 ← 1.8 and 5.10 ← 2.9. `src/api/schemas.py` is touched by every epic: incidental sharing, enforced as a serial gate between stories rather than by merging epics.

## Epic 1: Deal intelligence, finished (v0.13 carry-over + FR-31)

Felipe sees what a flat really costs per month, where its price/m² sits in its neighbourhood cohort on one comparable basis, gets saved-search emails for new matches, and opens the contract's detail side panel. Every pending v0.13 item lands here. Old-key mapping: 1.5 ← 2-7, 1.6 ← 2-1, 1.7 ← 2-2, 1.8 ← 2-5, 1.9 ← 2-3, 1.10 ← 2-4, 1.11 ← fu12 + fu13.

### Story 1.1: Total Monthly Cost on the persist path

As the operator,
I want every Listing to carry its rent, condo fee and IPTU as separate monthly components with an honest total,
So that costs are comparable across platforms and the aluguel-2027 cap can be evaluated without guessing (FR-31).

**Acceptance Criteria:**

**Given** `property_listings` has only `price`, `base_price`, `condo_fee`, `iptu`
**When** this story lands
**Then** a migration adds `rent_monthly`, `condo_fee_monthly`, `iptu_monthly`, `iptu_periodicity_source` ∈ {`monthly`, `annual`, `unknown`}, `fees_bundled`, `total_monthly_cost`, `cost_complete` and `updated_at` coverage for them (AD-3, AD-19), and it passes the alembic check
**And** the cost rules live in a pure `src/core/` module with no adapter import (AD-1), built test-first

**Given** a rent Listing from QuintoAndar, OLX or ZapImóveis
**When** it is normalized and persisted
**Then** `rent_monthly` is the platform's unbundled rent (QuintoAndar `rentPrice`, OLX `rent_base`, ZapImóveis `price`), a missing component is `unknown` and never zero, an annual IPTU is converted to monthly with the source periodicity recorded, an ambiguous periodicity is `unknown` and not divided, and a combined figure that cannot be split sets `fees_bundled`
**And** `total_monthly_cost` is `NULL` whenever a component is `unknown` and not bundled, with `cost_complete` false; legacy `price` / `base_price` are untouched and never inputs to the total

**Given** a sale Listing
**When** it is persisted
**Then** monthly condo fee and IPTU are stored under the same rules and no total is computed

**Given** a labelled fixture set covering the three platforms, including the same home on two platforms
**When** the unit suite runs
**Then** totals agree within the published component differences, base rent is never counted twice, and the OLX zero-for-missing-fee and Zap annual-IPTU cases each have a regression test
**And** Listings already in the DB are populated by re-running the normalize mapping over stored `raw_json` on the `scrapers` queue (not a second writer), the scraper cassette suite and live dry-run pass, and the operator migration step is recorded in the story's `operator_actions`

### Story 1.2: Cost in the canonical projection and coverage

As the operator and the agent,
I want cost components and the deciding Listing exposed through the one API projection,
So that every view and query reads the same total and can sort and filter by it (FR-31, AD-12).

**Acceptance Criteria:**

**Given** the cost columns from Story 1.1
**When** the property projection is serialized
**Then** each Listing exposes its components with explicit `unknown` / `bundled` states, and every rent-type decisioning view exposes exactly one `deciding_listing_id` with `deciding_rule` ∈ {`lowest-complete-total`, `lowest-headline-price`}
**And** no cost value is computed at read time

**Given** the property listing endpoint
**When** I sort or filter by total monthly cost
**Then** the query reads `total_monthly_cost` only, and Properties without a complete total are excluded from a cost filter unless incomplete totals are explicitly requested

**Given** FR-29 coverage telemetry
**When** I request coverage
**Then** a cost-completeness row reports the share of active rent Listings with a complete, bundled or incomplete total, per Platform (NFR-6, SM-3)
**And** `src/api/schemas.py` and `src/tests/contract/` cover the new fields

### Story 1.3: One cohort price basis for rent

As the operator,
I want rent cohorts scored on fee-exclusive rent on every platform,
So that the stat score and percentiles stop mixing fee-inclusive and fee-exclusive prices (AD-3).

**Acceptance Criteria:**

**Given** `scoring.py` computes price/m² from `price`, which is fee-inclusive on QuintoAndar and OLX and fee-exclusive on ZapImóveis
**When** this story starts
**Then** a characterization test locks the current cohort scoring output before any change

**Given** the cost columns from Story 1.1
**When** the metrics stage runs for a rent cohort
**Then** price/m² uses `rent_monthly`, the row is stamped `price_basis = rent_monthly` on `metrics_scoring`, and a Listing without `rent_monthly` keeps the `headline` basis and is stamped as such
**And** sale cohorts are unchanged, and the basis is defined in one place that later stories consume and never re-derive

**Given** the basis change shifts scores
**When** the story completes
**Then** the feature doc records the before/after distribution for the BH rent cohort, and the scoring math has unit coverage for mixed-basis cohorts

### Story 1.4: Primary migration cannot bypass the backfill guard

As the operator,
I want every path that migrates the primary database to honour the migration–backfill exclusion,
So that starting the stack or changing Redis settings cannot migrate under a live backfill (DW-32, DW-8; closes epic-3-retro-item-3).

**Acceptance Criteria:**

**Given** `scripts/start.sh` runs `alembic upgrade head` against the primary project
**When** this story lands
**Then** no helper script migrates the primary database outside `scripts/agent/migrate-primary.sh`, and a regression test fails if one does

**Given** `migrate-primary.sh` addresses Redis by a literal host, db 0 and literal key names
**When** `REDIS_URL` or `backfill.redis_prefix` differs from the defaults
**Then** the script resolves the same endpoint and keys the runner uses, and a test proves both sides see each other's key under a non-default prefix and db
**And** the Redis lock and heartbeat keys are never deleted by the change, and DW-32 and DW-8 are closed in the ledger

### Story 1.5: Corpus repair applied and verified

As the operator,
I want the fabricated-score repair confirmed on the primary corpus,
So that percentiles never compute over known-fabricated scores (old story 2-7, `awaiting-operator`).

**Acceptance Criteria:**

**Given** the repair migration from v0.13 story 2-7 ships un-applied
**When** the operator runs `bash scripts/agent/migrate-primary.sh` (batched with Story 1.1's migration)
**Then** a read-only verification reports zero rows carrying the fabrication signature and the count the repair touched, recorded in the feature doc
**And** the forensic predicate stays only in the one-off repair artifact, never in feature code

**Given** the verification passed
**When** sprint status is updated
**Then** this story is `done` and old key 2-7 is marked superseded, and Story 1.6 may start

### Story 1.6: Cohort price-per-m2 percentiles computed in the pipeline

As a user evaluating a listing,
I want each Property's price/m² percentile computed within its neighbourhood × listing-type cohort,
So that "cheap for Savassi rentals" is a stored, trustworthy signal (FR-30; old story 2-1).

**Acceptance Criteria:**

**Given** Stories 1.3, 1.4 and 1.5 are done
**When** the metrics pipeline stage runs
**Then** each Property's percentile is computed on the single price basis from Story 1.3 (never a hardcoded `price`), cohort-keyed neighbourhood × listing type, and persisted by the enrichment write authority (AD-10)
**And** dual rent/sale Properties get a percentile per listing type

**Given** a cohort below the config-owned minimum size
**When** percentiles are computed
**Then** the percentile is null, and Properties with missing area or unassigned neighbourhood are skipped with a null, not defaulted

**Given** this changes brownfield scoring SQL
**When** the story completes
**Then** a characterization test locks the existing projection first, the migration passes the alembic check, and the percentile math has unit coverage for a cohort exactly at minimum size, single-listing cohorts and ties

### Story 1.7: Percentile badge on cards and percentile filter

As a user scanning the grid,
I want the percentile on cards as the contract's badge and filterable through `Preço no bairro`,
So that I can shortlist statistically cheap properties in one pass (FR-30; UX-DR8–10; old story 2-2).

**Acceptance Criteria:**

**Given** stored percentiles from Story 1.6
**When** the grid renders
**Then** the badge reads `entre os N% mais baratos` from the AD-12 projection, right-aligned on the serif price line with the `price-drop` ink and tints (UX-DR9), never `P25`, "percentil" or `≤` (UX-DR8)
**And** a suppressed percentile renders as absent (UX-DR3)

**Given** the Filtros panel
**When** I choose `entre os 25% mais baratos`, `entre os 50% mais baratos` or `qualquer preço`
**Then** the API filters server-side on the stored value, the active value is one chip under the 2-line ceiling, and switching tipo re-evaluates against that type's cohort (UX-DR10)

**Given** contract, token and i18n obligations
**When** the story completes
**Then** schemas and contract tests cover the field and filter, strings land in `en` and `pt-BR`, and a Playwright e2e covers the badge, the filter and badge absence on a suppressed Property

### Story 1.8: Detail side panel with percentile sentence and cost breakdown

As a user opening a property,
I want the detail surface to be the contract's right-side panel, stating the percentile in plain language and the monthly cost itemized,
So that I judge a property with the map still in view and see what it really costs (UX-DR4, UX-DR8; FR-31 consumer; old story 2-5).

**Acceptance Criteria:**

**Given** the existing detail modal and the projection from Stories 1.2 and 1.7
**When** I open a property
**Then** the detail renders as a right-side panel over a partial scrim with the map rail visible, one level deep, closable with `Esc`, and the centered modal is retired with no dead code left
**And** it carries the modal's content restyled with the Meia-noite tokens plus the percentile sentence (`entre os N% mais baratos do bairro`, naming the cohort type on dual-type Properties)

**Given** a rent Listing's cost components
**When** the panel renders
**Then** rent, condo fee and IPTU show itemized with the total, an `unknown` component is shown as not informed rather than zero, and a bundled figure is labelled as bundled

**Given** the persistence contract
**When** the panel opens and closes across data refreshes
**Then** map viewport, grid scroll and filter state are preserved, a suppressed percentile is absent, existing modal e2e specs are migrated not deleted, and an e2e covers open → `Esc` → scroll preserved

### Story 1.9: Saved-search new-match detection on the pipeline

As a user with saved searches,
I want the pipeline to detect a newly created Property matching a notification-enabled saved search,
So that new deals reach me without re-running filters (FR-32; old story 2-3).

**Acceptance Criteria:**

**Given** a saved search with new-match notifications enabled
**When** the persist path creates a new matching Property
**Then** a notification is emitted through Celery and the single notifier registry on the email channel only (AD-9, UX-DR12), owned by the single principal (AD-11)
**And** matching is read-only against Property/Listing fields (AD-3)

**Given** a new match that is not yet decidable
**When** enrichment is pending
**Then** the alert is held until the verdict exists and the percentile has been evaluated (a value or a suppressed null both count), never dropped (UX-DR11)

**Given** noise control
**When** matches are delivered
**Then** only genuinely new Properties fire, each search × property pair notifies at most once, a disabled search never fires, emails batch into one daily window per search, the weekly digest excludes already-alerted Properties, and a platform outage produces no spurious matches
**And** the migration passes the alembic check, matcher logic has test-first unit coverage, and the Celery wrapper has one happy and one error test

### Story 1.10: Saved-search alert management UI

As a user managing saved searches,
I want a notify toggle and a minimum-drop threshold per saved search,
So that I control alert volume per search (FR-32; UX-DR13; old story 2-4).

**Acceptance Criteria:**

**Given** the capability from Story 1.9
**When** I view Buscas salvas
**Then** each row shows the toggle and an inline threshold that round-trip through the saved-searches API, with no global setting, immediate toggling and non-blocking error toasts

**Given** a drop alert fires
**When** the email is delivered
**Then** it states the threshold that fired it (`queda de R$ 240 — seu mínimo: R$ 100`)

**Given** contract, token and i18n obligations
**When** the story completes
**Then** the schema change has contract tests, rows follow the saved-search-row spec, strings land in both catalogs, and an e2e covers toggle-on + threshold edit persisting after reload

### Story 1.11: UI follow-ups — dashboard plurals and the shared bottom strip

As a user of the Painel,
I want Portuguese counts to agree with their nouns and toasts never to cover the compare bar,
So that the two v0.13 UI follow-ups are closed (`v0.13-fu12`, `v0.13-fu13`).

**Acceptance Criteria:**

**Given** `dashboard.enrichResultOk`, `enrichResultOkSkipped`, `rerunSkipPhotoGate`, `rerunWouldQueue` and `rerunQueued` use a single plural form
**When** the catalog is swept
**Then** each live key is split into One/Many variants in both catalogs, unreferenced keys are removed rather than split, and the catalog-parity unit test pins the new keys

**Given** the toast stack and `.compare-bar` share the bottom strip
**When** the viewport is narrower than ~1100px
**Then** a toast never covers the compare bar or swallows its clicks, the chosen sharing rule is recorded, and a narrow-viewport e2e case pins it

### Story 1.12: Backfill liveness is visible for the whole run

As the operator,
I want the backfill heartbeat, published state and lease kept alive for the entire run and supervisor lifetime,
So that a slow row, a long census or a Redis blip cannot make a live writer look idle (DW-9, DW-20, DW-21, DW-10, DW-34).

**Acceptance Criteria:**

**Given** the `:active` heartbeat and published state are refreshed only at row completion and the lease is renewed only inside `run_backfill`
**When** this story lands
**Then** one background ticker owns heartbeat, state and lease renewal across candidate fetch, census, in-flight rows and the inter-pass window
**And** a single enrichment slower than the TTL no longer reads as idle to `migrate-primary.sh` or to the status endpoint

**Given** Redis is unreachable for longer than the lease TTL
**When** the renewer cannot renew
**Then** the run stops launching new rows and exits as lease-lost instead of writing on a lapsed lease

**Given** the supervisor is mid-run
**When** I run `--status`
**Then** it reports the supervisor as running
**And** the state machine has unit coverage with a mocked Redis, `backfill_runner.py` gains no adapter import, and the five ledger entries are closed

### Story 1.13: Runner lifecycle ends honestly

As the operator,
I want a backfill that cannot proceed to stop and say why, on the surface I started it from,
So that a refused or crashed run is not silent (DW-19, DW-22, DW-23, DW-28).

**Acceptance Criteria:**

**Given** the provider refuses permanently
**When** `--continuous` has cycled with no progress past a config-owned limit
**Then** it exits with a distinct code a supervisor can act on, instead of alternating sleeps forever

**Given** a run requested through the admin API
**When** it is refused or crashes after the request is consumed
**Then** the outcome and reason are visible on the status endpoint and the Operações card

**Given** a pause request and a signal
**When** a pause is older than its TTL, or SIGINT/SIGTERM arrives
**Then** a pause never self-expires into resumed cloud spend without an operator action, and the signal handler performs no blocking Redis I/O
**And** each of the four cases has a regression test and the ledger entries are closed

**Sequencing note (advisory, not a gate):** if the SPIKE-1 verdict (Story 3.2) exists when this story starts, re-evaluate scope first. If Strata replaces Gemma for text classes, the cloud runner's remaining scope shrinks and parts of this story may be closed as not-needed with a recorded reason.

### Story 1.14: Transport-quota inference holds across a throttle

As the operator,
I want a provider throttle that arrives as resets or timeouts recognised for as long as it lasts,
So that a throttle window cannot burn attempts on good rows (DW-12, DW-13, DW-14, DW-15, DW-16).

**Acceptance Criteria:**

**Given** the recency licence added in v0.13-fu8
**When** a throttle turns silent mid-call, the provider goes fully silent past the recency window, or a `--continuous` cycle boundary is crossed
**Then** the storm is still classified as quota and no attempt is charged to the row

**Given** a 429 observed long after a transport storm began
**When** the recency test runs
**Then** it does not retroactively license that storm (the test is two-sided)

**Given** an inference fired during a run
**When** the run ends
**Then** the end-of-run banner states how many rows were classified by inference
**And** the AI golden tests pass and each case has a unit test

**Sequencing note:** same SPIKE-1 re-evaluation as Story 1.13.

### Story 1.15: Dependency and image scanning restored

As the operator,
I want known-vulnerable dependencies bumped and the filesystem/base-image scan back in the gate,
So that the accepted-risk register is read by a scanner again (DW-24, DW-25).

**Acceptance Criteria:**

**Given** `scripts/ops/audit-deps.sh` reported fixable advisories including a high-severity direct runtime dependency
**When** this story lands
**Then** the fixable advisories are bumped through the pip-compile lockfile and `package-lock.json`, with any deliberately unfixed one recorded with its reason

**Given** the Trivy filesystem and base-image scan was deleted with CI
**When** the full gate tier runs
**Then** an advisory scan stage reads `.trivyignore`, reports findings without changing the gate result, and degrades to a visible skip when the tool or network is absent

### Story 1.16: The admin audit trail names who acted

As the operator,
I want every audited admin action to record the principal that performed it,
So that the trail answers "who" before the agent starts writing through the same routes (DW-29; prerequisite for AD-6's audited Recheck).

**Acceptance Criteria:**

**Given** `admin_audit` records the action but not the actor
**When** an audited route is called with the API key or a JWT admin session
**Then** the row carries the single AD-11 principal id, with no actor or agent column and no agent-only table (AD-6)
**And** existing rows keep a null principal, the migration passes the alembic check, and contract tests cover the audit read model

### Story 1.17: Ledger and loop hygiene

As the operator running bmad-loop,
I want the spent-cap review flags disposed of and the open retrospective process items turned into bindings,
So that this version starts without inherited process debt (DW-26, DW-30; epic-3-retro-item-2, epic-3-retro-item-1, epic-1-retro-item-1, epic-1-retro-item-5).

**Acceptance Criteria:**

**Given** eight specs still carry `followup_review_recommended: true` with the damping cap spent (1-6, 2-7, 3-1 … 3-5, dw-decision-dw-2)
**When** this story lands
**Then** each flag is either reviewed once more with its findings ledgered, or cleared with a recorded reason, and DW-26 and DW-30 are closed

**Given** the three open process items
**When** the bindings are written
**Then** `_bmad/custom/*.toml` or `AGENTS.md` states: an escalated story's blocker is re-checked against the current tree before the loop advances; operator actions are presented as one deduplicated checklist per wave; and each epic close reports deferred-work opened versus closed and schedules a drain when net-positive
**And** the four retro keys are closed in sprint status with a pointer to the binding

### Story 1.18: Periodic tasks are not blocked by scrapes

As the operator,
I want short periodic tasks to run on time while long scrapes are in flight,
So that alerts, digests, metrics snapshots and queue monitoring are not delayed by hours (DW-63).

**Acceptance Criteria:**

**Given** `scrape_listings` runs that hold every slot of the scraper worker for hours
**When** a periodic task comes due (the saved-search matcher and sender, watchlist evaluation, digests, metrics snapshot, queue monitor, availability recheck, the refresh tasks)
**Then** it runs within its own schedule interval, on capacity a scrape cannot occupy
**And** a test pins that no periodic task shares a queue with `scrape_listings`

**Given** a beat entry whose previous run has not started yet
**When** the next tick fires
**Then** idempotent housekeeping runs do not accumulate without bound (stale runs are discarded or coalesced)
**And** a task whose missed run must not be lost (the hourly alert sender, the digests) is never discarded

**Given** `scrape_listings` itself is scheduled more often than a run completes
**When** a run for the same platform and scope is already queued or in flight
**Then** a duplicate is not queued behind it

**Given** the convention in AGENTS.md that every beat task is listed in `task_routes`
**When** this story lands
**Then** the convention still holds for the new queue, GPU work stays only on `ai` behind the GPU semaphore, and the queue monitor and the pipeline metrics snapshot report the new queue
**And** AGENTS.md, `docs/architecture.md` and `docs/setup.md` state the new layout

**Given** the primary stack already holds a backlog
**When** the operator deploys this
**Then** the feature doc gives the exact operator steps, including what happens to messages already queued on `scrapers` under the old routing (they must still be consumed, not stranded)
**And** DW-63 is resolved in the ledger

*Added 2026-10-08 from an operator observation on the primary stack (both scraper worker slots held by scrapes for more than two hours, about 11,400 messages waiting on `scrapers`); not part of the original Epic 1 breakdown.*

## Epic 2: Ask the agent which listings fit

Felipe asks Claude Code what fits a Search Profile and gets an answer read from the system: profiles are versioned config, every active Property carries a persisted Fit status per profile, and documented, contract-tested read endpoints serve the listing, the Fit bundle and the cohort summary. Attributes in this epic come from scraper fields and the amenity vocabulary; evidence-only Attributes are `unknown`.

### Story 2.1: Search Profiles as versioned config

As the operator,
I want my two searches defined in a versioned config file that is validated at startup,
So that the system holds `aluguel-2027` and `compra-2028` as product objects instead of ad-hoc filters (FR-41, AD-16).

**Acceptance Criteria:**

**Given** `AppConfig` loads only `configs/app_config.yaml`
**When** this story lands
**Then** the one loader in `src/infra/config.py` gains a sibling-file include and loads `configs/search_profiles.yaml`, each profile carrying an integer `version`, listing type, geography, hard constraints, soft preferences and a horizon date (AD-2)
**And** the file is not env-overridable — a unit test asserts an `IMOVEIS_*` override of a profile is rejected

**Given** canonical attribute keys must exist before a profile can reference them
**When** this story lands
**Then** `src/core/attributes.py` defines the attribute-key enum with each key's type and allowed provenances (`home_office_capable` never allows `scraper`), with no adapter import (AD-1)

**Given** a profile with an unknown attribute key, an unparseable constraint or a missing listing type
**When** the application starts
**Then** startup fails naming the offending key
**And** the committed file holds the two profiles of record, with `compra-2028` soft preferences empty and BH geography (PRD Q5, confirmed by Felipe 2026-10-07), and unit tests cover the valid and each invalid branch

### Story 2.2: Attribute store with one resolver

As the operator,
I want Attributes stored as provenance rows and resolved by one function,
So that a scraper fact is never overwritten and conflicts stay visible (FR-39, AD-14, NFR-10).

**Acceptance Criteria:**

**Given** no Attribute storage exists beyond legacy columns
**When** this story lands
**Then** a migration creates `property_attributes` with one row per (property, attribute key, provenance, source), typed value, optional confidence in [0, 1], `observed_at`, `updated_at` and the typed source columns of AD-14, and it passes the alembic check
**And** `unknown` is the absence of current rows, never a stored value

**Given** rows of several provenances for one key
**When** `core.attributes.resolve()` runs
**Then** it returns the winner by `scraper` > `text` > `photo` with the deterministic intra-provenance tie-break, the full conflict list, and reports stale rows as `stale` counting as `unknown` (a `scraper` row is stale when its Listing is inactive)
**And** there is no SQL view and no SQL-level precedence; the resolver is built test-first

**Given** a Property with no row for a legacy-column key (bedrooms, bathrooms, parking, furnished, pets)
**When** it is resolved
**Then** the legacy column is used as a fallback with synthetic source `properties.<column>`, and never competes when rows exist
**And** a dedupe merge re-parents rows by `property_id` without rewriting them, proven by a characterization test on the merge path

### Story 2.3: Scraper Attributes through the amenity vocabulary

As the operator,
I want scraper fields and platform amenity codes written as `scraper` Attribute rows,
So that elevator, gym and the structured fields are known with their source (FR-39 scraper provenance, AD-16).

**Acceptance Criteria:**

**Given** elevator, gym and pool exist only as raw codes in `props_json.amenities` on QuintoAndar and ZapImóveis
**When** this story lands
**Then** `configs/attribute_vocabulary.yaml` (versioned, loaded by the one loader) maps platform codes onto the `core` attribute keys, the loader rejects an entry whose key disallows `scraper`, and an unmapped code is logged and ignored

**Given** a Listing is normalized and persisted
**When** its structured fields and mapped codes are written
**Then** `scraper` rows are created with `source_listing_id`, `source_field` and `vocabulary_version`, only on the scrape → normalize → persist path (AD-3)
**And** the keys with legacy columns are row-backed from this story on

**Given** the vocabulary version is bumped
**When** the remap task runs on the `scrapers` queue
**Then** it re-applies the normalize mapping over stored `props_json` / `raw_json` for rows with an older stamp, and the same task populates rows for the existing corpus
**And** the vocabulary table is test-covered, the task is listed in `task_routes`, and the scraper cassette suite and live dry-run pass

### Story 2.4: Fit evaluation as a pure function

As the operator,
I want one tested function that decides how a Property fits a profile,
So that Fit logic exists in exactly one place with fixed semantics (FR-41, AD-19).

**Acceptance Criteria:**

**Given** resolved Attributes, Listing cost columns, scope facts and optional travel and facet rows
**When** `core.fit.evaluate()` runs for a Property and a profile
**Then** it returns a `FitResult` with status ∈ {`fits`, `fits-pending-verification`, `fails`, `out-of-scope`}, the named failing or unverified constraints, the soft score with its unknown count, and the deciding Listing

**Given** the fixed semantics
**When** the labelled fixture set runs
**Then** an `unknown` relevant Attribute or an incomplete Total Monthly Cost never yields `fails`; soft preferences never change status; soft score = satisfied ÷ (satisfied + not-satisfied) with `unknown` excluded; lower complete total ranks higher within equal soft scores; the lowest complete total among active rent Listings decides the cap
**And** `out-of-scope` follows listing type and persisted city membership only

**Given** AD-1
**When** the story completes
**Then** `core/fit.py` imports nothing from `adapters` or `api`, is built test-first, and absent travel or facet inputs evaluate as `unknown` so the function works before Epics 4 and 6

### Story 2.5: Fit status persisted per profile version

As the operator,
I want every active Property's Fit status stored and kept current for each profile version,
So that listing and filtering read stored rows and a profile change never rewrites history (FR-41, AD-19).

**Acceptance Criteria:**

**Given** the function from Story 2.4
**When** this story lands
**Then** a migration creates `property_fit_status` at grain (property, profile id, profile version) with status, named constraints, soft score, unknown count, `deciding_listing_id`, `evaluated_at` and a `fit_summary` field defaulting to `not-computed`
**And** city membership used for `out-of-scope` is resolved on the persist path and stored, never queried spatially at read time

**Given** a fact that feeds Fit changes, or a Property has no row for the loaded profile version
**When** the beat sweep runs on the `scrapers` queue
**Then** it selects Properties where `max(input updated_at)` > `evaluated_at` or no row exists, writes `property_fit_status` only, and no fact writer enqueues Fit
**And** the task is listed in `task_routes`

**Given** a profile version is bumped
**When** the sweep completes
**Then** rows exist for the new version and the previous version's rows are retained
**And** an integration test covers re-evaluation after an Attribute change and after a version bump

### Story 2.6: Agent reads profiles and the Fit-status listing

As the agent client,
I want to list a profile's candidates sorted and filtered in one call,
So that "everything that fits aluguel-2027 sorted by Total Monthly Cost" needs no second request (FR-42, NFR-9).

**Acceptance Criteria:**

**Given** the API key gate
**When** I request the profiles endpoint
**Then** I get each profile's id, version, constraints, soft preferences and horizon with canonical English values and ISO dates

**Given** persisted Fit rows
**When** I request a profile's Fit-status listing
**Then** I can filter by Fit status and sort by soft score, Total Monthly Cost, price drop and freshness, with pagination, reading only `property_fit_status` and Listing rows for the loaded profile version (older versions through `?version=`)
**And** a Property without a row appears as `unknown` / `not-computed` and is counted as such

**Given** the agent-facing contract
**When** the story completes
**Then** the API version scheme is decided and documented as one scheme for all routes, `src/api/schemas.py` and contract tests cover both endpoints, and a 200-row listing returns within 5 s on the test stack

### Story 2.7: Fit bundle per Property

As the agent client,
I want one payload holding everything a Dossier needs for a Property under a profile,
So that I write the Dossier from system data alone (FR-40, AD-12).

**Acceptance Criteria:**

**Given** a Property and a profile
**When** I request the Fit bundle
**Then** it carries Fit status with per-constraint checks, each Attribute's resolved value, provenance and conflicts, soft score, the cost breakdown with `deciding_listing_id` and `deciding_rule`, existing verdicts, price-history summary, listing links and `unknown_count`
**And** it is assembled from persisted rows through the one projection, with no per-Property fact computed at read time

**Given** a part that is missing
**When** the bundle is serialized
**Then** that part is `unknown` with reason `not-computed` or `unavailable`, including travel times, facets, availability state, Photo evidence reference and Fit summary until their epics land

**Given** two profile versions
**When** I request each
**Then** both bundles are retrievable
**And** contract tests cover every field and a bundle returns within 2 s on the test stack

**Sequencing note:** Stories 5.4 (availability state) and 3.7 (Photo evidence reference) are scheduled before this story. Where their persisted rows already exist when this story lands, the bundle reads them here instead of emitting `unknown`; the wiring belongs to this story, not to a later patch.

### Story 2.8: Cohort summary per profile

As the agent client,
I want a profile's market read in one call,
So that the compra-2028 scan answers with a distribution instead of a shortlist (FR-42, UJ-6).

**Acceptance Criteria:**

**Given** persisted Fit rows for a profile
**When** I request the cohort summary
**Then** I get counts per Fit status including `not-computed`, and price/m² median, p25 and p75 per neighbourhood for the `fits` + `fits-pending-verification` cohort, with the `price_basis` stated

**Given** read-time aggregation is allowed and per-Property derivation is not
**When** the summary is computed
**Then** it aggregates persisted facts only, a neighbourhood below the minimum cohort size is suppressed rather than shown, and the minutes distribution block is `unknown` / `not-computed` until Epic 4
**And** contract tests cover the schema and it returns within 5 s on the test stack

### Story 2.9: Agent stars with a reason, and the agent guide

As the operator working through the agent,
I want the agent to star and unstar a Property with an optional reason, and a documented way to call the surface,
So that the agent's only writes are my own single-Property actions (FR-42, AD-6).

**Acceptance Criteria:**

**Given** the favourites routes
**When** the agent stars or unstars with a reason
**Then** the reason is stored in a nullable `favourites.reason` on the principal-owned row, with no actor or agent column, and the migration passes the alembic check

**Given** the agent surface is complete for this epic
**When** the story completes
**Then** `docs/api.md` has an "Agent usage" section with example calls (list fits for a profile, fetch a bundle, cohort summary, star with reason), stating that the agent never reads the DB or scrapes the UI and that write scope is star/unstar and Recheck only (PRD Q7 default)
**And** contract tests cover the reason field

### Story 2.10: Coverage for Attributes and Fit

As the operator,
I want coverage telemetry to say how much of the corpus has each Attribute and how each profile's Fit statuses are distributed,
So that I can judge how much of a shortlist is still unverified (NFR-6, SM-2, SM-5).

**Acceptance Criteria:**

**Given** FR-29 coverage
**When** I request coverage
**Then** a per-attribute-key row reports the share of active Properties whose resolved value is non-`unknown`, computed with the same `core` resolver, and a per-profile row reports the Fit-status distribution
**And** both derive from the DB through the existing coverage queries module with the same "active Properties" denominator

**Given** Operações renders coverage
**When** the new rows are present
**Then** they render as text percentages only, per the delivered coverage pattern (UX-DR6), with strings in both catalogs

## Epic 3: Claims backed by evidence

Attributes are extracted from listing text and photos with provenance, photo facts are stamped with the evidence they read, each Fit bundle carries a Fit summary, and the Strata spike settles the local text backend first.

### Story 3.1: LM Studio client parity

As the operator,
I want the OpenAI-compatible local client to support structured output, configurable token limits and plain generation,
So that any text class can route to a local OpenAI-compatible server (AD-17; spike pre-work).

**Acceptance Criteria:**

**Given** `LMStudioClient` sends no `response_format`, hardcodes `max_tokens` and lacks `generate()`
**When** this story lands
**Then** it sends `response_format` as `json_object` or `json_schema` built from the class's Pydantic schema, reads `max_tokens` from config, and implements `generate()` so the OLX location path works on this backend
**And** a `502 structured_output_failed` is handled as a client-side retry under the one invalid-JSON retry policy

**Given** the committed routing map
**When** the story completes
**Then** it is still all-local and unit-pinned, the AI golden tests pass, and the client has unit coverage against a fake server for each new behaviour

### Story 3.2: Strata spike — A/B and verdict

As the operator,
I want a measured answer on whether Strata can be the local text backend,
So that text extraction is built and calibrated against the winning backend (SPIKE-1, PRD §6.4).

**Acceptance Criteria:**

**Given** the host requirement
**When** the spike starts
**Then** host RAM and free NVMe are checked against ≥ 32 GB and ~80 GB first, and a shortfall ends the spike as `reject` or `defer` with that reason

**Given** `scripts/dev/ab_gemini_vs_ollama.py` adapted to compare `lmstudio` (Strata, exact release pinned) against `ollama` (`qwen2.5vl:7b`)
**When** it runs on ~50 hand-labelled BH listings with Ollama co-resident
**Then** it reports Attribute exact-match, JSON validity on first try and after retry, and seconds per Property, with the VRAM observation and any `gpu.semaphore_limit` / `OLLAMA_NUM_PARALLEL` re-tune

**Given** the measurements
**When** the spike closes
**Then** a verdict (adopt / reject / defer) with the numbers is recorded under `_bmad-output/planning-artifacts/research/` and in the ledger, only `.env.local` routing values were changed, and no code path or committed config was touched
**And** the labelled set is committed as the fixture set Story 3.6 reuses, and the time box is five working days

### Story 3.3: Task-class scopes replace stage literals

As the operator,
I want enrichment scope expressed as a set of task classes with a per-class skip key,
So that new classes can be added, skipped and backfilled without a second vocabulary (AD-17).

**Acceptance Criteria:**

**Given** `run_enrichment`, the `ai_enrich` task, the selective rerun and the backfill runner pass `stages` string literals
**When** this story lands
**Then** they pass a `frozenset[EnrichmentTaskClass]`, the enum gains `attributes` and `fit_summary`, and the dependency order (`visual` → `attributes` → facets → `deal_verdict` → `fit_summary`) is one table in `core`
**And** a characterization test locks current enrichment behaviour before the refactor

**Given** each class is separately skippable
**When** a class's inputs are unchanged
**Then** it is skipped by its own persisted skip key, as listed in AD-17

**Given** the routing map
**When** the backfill runner resolves its scope
**Then** a class routed to a local backend is excluded from the cloud runner, any strict subset is accepted, and a scope resolving to different cloud backends still refuses
**And** the routing validator covers the two new classes, the committed map stays all-local, and the AI golden tests pass

### Story 3.4: Gallery fingerprint and the fuzzy-merge guard

As the operator,
I want a Property's gallery identified by a stable fingerprint and protected on merge,
So that a photo fact can be tied to the gallery it was read from (AD-15; BIN-146 follow-up).

**Acceptance Criteria:**

**Given** `core/dedupe.py` overwrites `image_urls` and `props_json` unguarded on a fuzzy match
**When** this story starts
**Then** a characterization test locks the current exact-path and fuzzy-path merge behaviour

**Given** one `core` URL normalizer (lowercase scheme and host, query string and fragment dropped)
**When** a Property is persisted
**Then** `properties.gallery_fingerprint` = sha256 of the sorted normalized URLs is stored on the persist path, `_is_unchanged` and the fuzzy path compare the same normalized list, the fuzzy path applies the same guard as the exact path, and a change logs a `gallery_changed` event
**And** the photo gate is evaluated once at persist on that list

**Given** the existing corpus
**When** the migration is applied
**Then** fingerprints are populated for existing rows, the migration passes the alembic check, and a regression test proves CDN query-string churn does not change the fingerprint

### Story 3.5: Immutable, stamped photo evidence

As the operator,
I want every visual pass to record exactly which photos the model read,
So that a stale gallery can never silently back a photo fact (AD-15).

**Acceptance Criteria:**

**Given** `ImageStore.download_images` returns cached files regardless of which gallery they came from
**When** this story lands
**Then** files are stored under `<image_storage_path>/<property_id>/<gallery_fingerprint>/`, the cached-files shortcut reuses only the current fingerprint's directory, legacy flat directories are ignored, and the MD5/SHA-256 docstring is corrected

**Given** a visual pass
**When** it completes
**Then** `meta.visual` is stamped with `evidence_set_id`, `gallery_fingerprint`, `evidence_count`, model id and prompt version

**Given** the backfill runner, the selective rerun and FR-29 coverage each decide which Properties need a visual pass
**When** this story lands
**Then** all three use one SQL fragment owned by `adapters/db` (active, gate passed, and no stamp or stale fingerprint or older prompt version), `ai_score IS NULL` is retired as a candidate key, and visual coverage equals stamp-is-current
**And** unstamped legacy `meta.visual` keeps its score, and the one-off catch-up is operator-triggered through the existing rerun surface

### Story 3.6: Attributes extracted from listing text

As the operator,
I want Attributes extracted from the listing description with provenance,
So that elevator, gym, furnished and home-office claims in the text are captured where the scraper has no field (FR-39 `text`).

**Acceptance Criteria:**

**Given** Stories 3.2 and 3.3 are done
**When** the `attributes` class runs for a Property on the `ai` queue
**Then** one Pydantic schema validates the output and is sent as the `json_schema`, and `text` rows are written only by the enrichment authority with `source_hash` (description SHA-256), `model_id` and `prompt_version`
**And** a `text` value disagreeing with a `scraper` value is stored as a conflict and never overwrites it

**Given** the description changes or the prompt version rises
**When** the resolver reads the row
**Then** the old row is `stale` and counts as `unknown`, and the class's skip key (description hash + prompt version) re-runs it

**Given** the labelled fixture set of ≥ 50 BH listings
**When** the golden tests run on the backend chosen by the spike
**Then** exact-match on bedrooms, parking, elevator, gym and furnished is ≥ 85% and schema validity after retry is 100%, or the thresholds are re-baselined in the feature doc with the spike's numbers
**And** `home_office_capable` is `unknown` unless a second enclosed bedroom or an explicit office mention is evidenced (PRD Q4, confirmed by Felipe 2026-10-07)

### Story 3.7: Attributes inferred from photos

As the operator,
I want the visual pass to report the Attributes photos can show,
So that a home office, furniture or split-AC visible in the gallery is recorded with the evidence it came from (FR-39 `photo`).

**Acceptance Criteria:**

**Given** the stamped visual pass from Story 3.5
**When** the `visual` class runs
**Then** photo-derived Attributes are an output extension of the same call and backend, written as `photo` rows stamped with `evidence_set_id`, `gallery_fingerprint` and `evidence_count`; thin evidence lowers confidence and never withholds rows

**Given** a Property that fails the photo gate
**When** Attributes are resolved
**Then** it has no `photo` rows, so photo-derived Attributes are `unknown`, not degraded

**Given** a gallery change
**When** the resolver reads a `photo` row whose stamped fingerprint differs from the current one
**Then** the row is `stale` and counts as `unknown`
**And** a scraper "furnished: no" against photos showing furniture is kept as a conflict, the Fit bundle's Photo evidence reference is populated, and golden tests guard false positives on elevator, gym and home office (SM-C2)

**Sequencing note:** this story is scheduled before Story 2.7 (the bundle). It persists the evidence reference on the stamped visual rows; if the bundle does not exist yet, Story 2.7 reads it into the bundle and this story's bundle assertion moves there.

### Story 3.8: Fit summary in the bundle

As the operator reading a Dossier,
I want a short profile-aware sentence for each candidate,
So that the bundle says in words what fits and what is unverified (FR-40).

**Acceptance Criteria:**

**Given** a Fit row has committed
**When** the sweep enqueues the `fit_summary` class on `ai`
**Then** the summary is generated from the persisted `FitResult` only, stored on `property_fit_status.fit_summary`, and reset to `unknown` whenever the row is re-evaluated

**Given** a Fit row with a hard constraint and an unverified Attribute
**When** the summary is generated
**Then** it names at least one of each and never contradicts the structured status, checked by golden tests

**Given** the text backend is down
**When** the bundle is requested
**Then** it is served with the Fit summary `unknown`
**And** the class routes through `enrichment_routing` and its skip key is (profile version, `evaluated_at`, prompt version)

### Story 3.9: Attributes with provenance in the detail panel

As the operator browsing the UI,
I want the detail panel to show each Attribute with where it came from,
So that the secondary surface tells the same truth as the agent (FR-39 UI consumer; PRD §6.3).

**Acceptance Criteria:**

**Given** the detail side panel from Story 1.8 and the projection from Story 2.7
**When** the panel renders a Property
**Then** each profile-referenced Attribute shows its value with a provenance label (scraper, text, photo), an `unknown` Attribute reads as not verified rather than absent or false, and a conflict is shown beside the winning value

**Given** token and i18n obligations
**When** the story completes
**Then** it uses existing tokens and components only (UX-DR1, UX-DR3), strings land in both catalogs with wire values in English, and an e2e covers a conflict and an `unknown`

## Epic 4: Minutes to my places

Every active BH Property has car, transit and walk-budget minutes to each Anchor or an honest `unknown`, the agent sorts by minutes, and coordinates never leave the box.

### Story 4.1: Anchors as versioned config with a local coordinate overlay

As the operator,
I want my Anchors defined in versioned config with their coordinates kept out of the repository,
So that the system knows my places without publishing where they are (FR-35, AD-16).

**Acceptance Criteria:**

**Given** the loader from Story 2.1
**When** this story lands
**Then** `configs/anchors.yaml` defines the five Anchors with id, label, modes, optional walking budget, optional departure override and integer `version`, with no coordinates, and `configs/anchors.local.yaml` (git-ignored) supplies coordinates and the current-home location merged by Anchor id
**And** each overlay entry repeats the Anchor's `version`, and the loader fails naming the id when it differs

**Given** `travel_time.enabled` is false (committed default)
**When** the application starts without an overlay
**Then** it starts; with `travel_time.enabled` true and a missing coordinate it fails validation

**Given** privacy pins
**When** the unit suite runs
**Then** a test fails if the committed anchors file carries `lat`/`lon` or `.gitignore` lacks `configs/anchors.local.yaml` and `data/routing/`, the suite uses `src/tests/fixtures/anchors.local.yaml` with synthetic coordinates, and a logging-filter test proves coordinates are dropped from logs

**Given** the agent surface
**When** I request the Anchors endpoint
**Then** it returns id, label, modes, budgets and version and never coordinates, enforced by a schema test

### Story 4.2: Car and walk minutes from a local router

As the operator,
I want car minutes to every Anchor and walk minutes where a walking budget is declared,
So that distance is expressed in routed minutes, never km and never an estimate (FR-35 `car`, AD-18).

**Acceptance Criteria:**

**Given** no per-Property travel data exists
**When** this story lands
**Then** a migration creates `property_travel_times` at grain (property, anchor id, anchor version, mode, departure assumption) holding minutes or `unknown` with reason ∈ {`no-provider`, `unroutable`, `outside-coverage`, `provider-error`}, plus `provider`, `provider_version`, `computed_at`, `updated_at`, and no distance column

**Given** one `TravelTimeProvider` port in `adapters/geo` and one `travel_time` config section
**When** the OSRM adapter is configured (`osrm_car_url`, `osrm_foot_url`)
**Then** `car` is computed for every Anchor and `walk` only for Anchors declaring a walking budget; with no provider the value is `unknown` / `no-provider`; haversine is never written to this table

**Given** stale rows (absent, Property location changed, Anchor version changed, provider version changed, or `provider-error` past its backoff)
**When** the beat recompute runs on the `scrapers` queue
**Then** only stale rows are recomputed, never per scrape and never on `ai`, and the task is listed in `task_routes`

**Given** deployment
**When** the story completes
**Then** the compose `routing` profile adds two `osrm-routed` services (image `ghcr.io/project-osrm/osrm-backend:v26.10.0-debian`), routing data lives under git-ignored `data/routing/`, `docs/setup.md` records the operator fetch-and-build steps, the ephemeral test stack never runs the profile, and the suite uses an in-repo fake provider

### Story 4.3: Transit minutes from a local schedule-aware router

As the operator,
I want transit minutes to every Anchor at a stated departure time,
So that a flat's bus commute is known without sending my places to a cloud service (FR-35 `transit`, NFR-1).

**Acceptance Criteria:**

**Given** the port from Story 4.2
**When** the OpenTripPlanner adapter is configured (`otp_url`)
**Then** `transit` minutes are computed through the GTFS GraphQL API (`POST /otp/gtfs/v1`, `planConnection` with `earliestDeparture`) at the departure assumption (default weekday 08:00 local, per-Anchor override), which is part of the row key
**And** an unroutable or out-of-coverage pair is `unknown` with its reason

**Given** deployment
**When** the story completes
**Then** the `routing` profile adds `opentripplanner/opentripplanner:2.10.0` with heap set through `JAVA_TOOL_OPTIONS`, fed by the PBH GTFS feed and the same OSM extract, with build time and memory recorded in `docs/setup.md`

**Given** the cloud transit option
**When** it is not explicitly enabled
**Then** no request leaves the box; the adapter slot exists behind the same port, off by default, documented as sending Property and Anchor coordinates off-box
**And** the adapter has unit coverage against recorded responses and no gate depends on OTP

### Story 4.4: Minutes in Fit, the bundle and the agent listing

As the agent client,
I want to sort candidates by minutes to a named Anchor and see travel times in each bundle,
So that proximity to my places ranks the shortlist (FR-35, FR-42, FR-41 soft preferences).

**Acceptance Criteria:**

**Given** travel rows exist
**When** I request the Fit-status listing sorted by minutes to an Anchor and mode
**Then** it sorts on persisted `property_travel_times` rows, with `unknown` last and counted, and I can filter by a maximum number of minutes to an Anchor and mode

**Given** the Fit bundle and cohort summary
**When** they are serialized
**Then** the bundle carries minutes per Anchor and mode with provider and departure assumption, or `unknown` with its reason, and the cohort summary carries the distribution of minutes per Anchor and mode

**Given** a profile soft preference on minutes to an Anchor
**When** the fit sweep runs
**Then** the preference evaluates from travel rows (`unknown` excluded from the score), a travel row change triggers re-evaluation, and coverage gains a per-Anchor-mode row (SM-4, transit reported as its own percentage)
**And** contract tests cover the new fields and no km or coordinate field exists anywhere in the schema

### Story 4.5: Minutes to a selected Anchor on the map and cards

As the operator browsing the UI,
I want to pick one of my Anchors and see each property's minutes to it,
So that the map answers "how far from church" without drawing my places (FR-35 UI consumer; UX-DR25 as amended).

**Acceptance Criteria:**

**Given** the Anchors endpoint and travel times in the projection
**When** I select an Anchor and a mode on the Painel
**Then** each card and map point shows minutes to that Anchor, an `unknown` shows as not available rather than a number, and I can filter by a maximum number of minutes server-side

**Given** AD-18
**When** the feature renders
**Then** no Anchor pin and no band is drawn, no coordinate is requested or stored in the browser, and minutes are the only unit shown

**Given** the filter-bar contract
**When** the minutes filter is active
**Then** it renders as one removable chip under the 2-line ceiling, strings land in both catalogs, and an e2e covers select → minutes shown → filter applied

## Epic 5: Listings that are still real

Starred Properties are rechecked daily and on demand, gone and returned listings are tracked and alerted in-app, and a scraper that misbehaves or stops running says so with a reason.

### Story 5.1: Durable scraper run history

As the operator,
I want every coleta's duration, yield and outcome stored durably,
So that run history survives restarts and other features can ask whether a platform's coleta succeeded (FR-37 foundation).

**Acceptance Criteria:**

**Given** `_record_scrape_run` writes a capped Redis telemetry list
**When** this story lands
**Then** the same seam also writes a `scraper_runs` row per coleta (platform, start, duration, processed/included/excluded/updated, outcome incl. circuit-broken and failed), the Redis list becomes a feed and not the store, and the migration passes the alembic check
**And** no second telemetry bus is introduced, and the write has one happy and one failure test

### Story 5.2: Run analytics with reasons

As the operator,
I want each coleta compared against the scraper's own baselines with a reason when it deviates,
So that "finished too early" is a stated signal and not a hunch (FR-37).

**Acceptance Criteria:**

**Given** run history from Story 5.1
**When** analytics are computed for a scraper
**Then** deviation of duration or yield beyond a config-driven band from the rolling baseline or the pinned long-window baseline produces a reason string key with its values; below the calibration count the state is `calibrating` with progress, not ok

**Given** each scraper's configured schedule
**When** no coleta has run within the expected cadence
**Then** the state is missed-cadence with the hours since the last coleta and the expected interval

**Given** the admin surface
**When** I request scraper health and run history
**Then** both are served from the DB with states as canonical English enums, no external notification fires for any anomaly, the baseline math is built test-first, and contract tests cover the schemas

### Story 5.3: Scraper health chips and the run-history table

As the operator,
I want the health strip and Operações to show each scraper's state with its reason,
So that I see why a scraper is amber without opening a terminal (FR-37; UX-DR23, UX-DR24).

**Acceptance Criteria:**

**Given** the API from Story 5.2
**When** the Painel health strip renders
**Then** each scraper has one chip: ok with last-run recency (`QuintoAndar · há 2h`), anomaly with an italic `health-warn` reason (`OLX: coleta 5× mais rápida que a mediana`), missed cadence (`sem coleta há 26h (esperado: a cada 6h)`), or `calibrando baseline (3/10 coletas)`; chips are read-only and click through to Operações

**Given** Operações
**When** the run-history table renders
**Then** it shows duration, yield and signed deviation against both baselines in tabular numerals with hairline separators, anomaly rows carry the reason, calibrating rows use `pending`, with no sparklines or bars
**And** "coleta" is the user-facing word, strings land in both catalogs, and an e2e covers the anomaly and calibrating states

### Story 5.4: Gone and returned listings

As the operator,
I want a listing marked gone only after its platform's successful coletas stop including it, and un-marked when it returns,
So that an outage never manufactures false deaths and a comeback is visible (FR-34).

**Acceptance Criteria:**

**Given** run outcomes from Story 5.1
**When** a Listing is absent from N consecutive successful coletas of its Platform (N config-driven)
**Then** it becomes gone on the persist path (AD-3); failed or circuit-broken coletas never count, and skip-unchanged still bumps last-seen

**Given** a gone Listing reappears in a coleta
**When** it is persisted
**Then** the gone state clears, the price-history series is annotated with the gap, and the transition is recorded with its dates

**Given** the projection
**When** a Property is serialized
**Then** its availability state (live, gone since, returned on) is exposed, the Fit bundle's availability part is populated, and a gone Listing's `scraper` Attribute rows resolve as stale (AD-14)
**And** a characterization test locks current last-seen behaviour first, and unit tests cover outage, N−1, N and resurrection

**Sequencing note:** this story is scheduled before Story 2.7 (the bundle) and has no gate on Story 2.2 (the resolver). It exposes the availability state in the property projection and marks a gone Listing inactive; the bundle part is wired by Story 2.7, and the stale-`scraper`-row assertion is added by whichever of 5.4 and 2.2 lands second.

### Story 5.5: Recheck a listing on demand

As the operator or the agent,
I want to trigger an availability check on one listing and get an honest answer,
So that I know a candidate is still real before acting on it (FR-33, FR-42 write scope).

**Acceptance Criteria:**

**Given** Story 1.16's audited principal
**When** I call the one principal-scoped Recheck route
**Then** the probe runs through the scraper runtime contract (AD-5), returns `available`, `unavailable` or `unknown` with its own timestamp, and is audited in `admin_audit` with the principal id; the UI and the agent call the same route

**Given** a 403, Cloudflare block or timeout
**When** the probe returns
**Then** the result is `unknown`, the Listing is not marked gone, and the freshness stamp is untouched

**Given** the per-listing cooldown and the config-driven daily global budget
**When** a Recheck is requested inside the cooldown or with the budget spent
**Then** no probe is sent and the response states which limit applied and when it clears
**And** `unavailable` marks the Listing gone immediately, contract tests cover the route, and the scraper cassette suite and live dry-run pass

### Story 5.6: Daily rechecks for starred Properties

As the operator,
I want my favourites checked automatically every day,
So that a starred Property never goes stale unnoticed (FR-33, SM-6).

**Acceptance Criteria:**

**Given** starred Properties
**When** the beat task runs on the `scrapers` queue
**Then** each starred Property's active Listings are rechecked at least once every 24 h through the same probe, cooldown and global budget as Story 5.5, with starred items prioritised when the budget is short
**And** the budget is never exceeded and the task is listed in `task_routes`

**Given** a batch in which probes failed
**When** the results are stored
**Then** each Listing records its own last-verification outcome and time, so a failed check is distinguishable from a verified one

### Story 5.7: Favourite-gone and resurrection alerts

As the operator,
I want to be alerted when a favourite leaves the market or comes back,
So that I hear about it without checking (FR-34, AD-9).

**Acceptance Criteria:**

**Given** a starred Property's Listing becomes gone, by coleta or by Recheck
**When** the lifecycle transition commits
**Then** a favourite-gone alert is emitted through Celery and the single notifier registry, on by default for starred items, by email

**Given** a previously starred Property returns to the market
**When** the resurrection is persisted
**Then** a resurrection alert is emitted the same way, at most once per transition

**Given** alerts must be readable in-app
**When** any alert fires (price drop, new match, favourite gone, resurrection)
**Then** it is stored as a history row owned by the single principal with type, Property, timestamp and read state, served by an alerts endpoint with contract tests, and the row persists after the Property changes state
**And** no second notifier path or preference tree is added

### Story 5.8: Alertas panel and desktop push

As the operator,
I want a bell with my alert history in the app and an optional desktop notification,
So that a gone favourite is visible without opening email (FR-32 remainder, FR-34; UX-DR21, UX-DR22).

**Acceptance Criteria:**

**Given** the alerts endpoint from Story 5.7
**When** I open Alertas from the top-nav bell
**Then** rows show a type icon in the semantic ink (green drop, accent new-match, rust gone), the property line and a relative timestamp; unread rows use `text-primary`, read rows `text-secondary`; a click opens the detail side panel and marks the alert read; the empty state reads `Nenhum alerta por enquanto.`

**Given** the browser is running and permission was granted
**When** a favourite-gone or resurrection alert fires
**Then** a desktop notification is shown; without permission or with the browser closed nothing fails and email remains the guaranteed channel

**Given** token and i18n obligations
**When** the story completes
**Then** strings land in both catalogs and an e2e covers open → row click → panel opens → row read

### Story 5.9: Availability in the detail panel, cards and chart

As the operator,
I want to check availability from the detail panel and see gone and returned listings for what they are,
So that the UI never shows stale hope (FR-33, FR-34; UX-DR14–18).

**Acceptance Criteria:**

**Given** the Recheck route
**When** I press `Verificar disponibilidade` in the detail panel
**Then** the button shows inline `verificando…` and blocks nothing, then `disponível`, `indisponível` or `não foi possível verificar` with its own timestamp; the cooldown (`verificado há 20 min`) and a spent budget are shown in the button state; the unknown state is visually distinct and never changes the freshness stamp

**Given** a gone Listing
**When** cards, map and panel render
**Then** the card shows the rust italic note per listing type (`provavelmente alugado — sem atualização há N dias` / `provavelmente vendido — …`), a desaturated photo and no verdict; the map point is hollow; gone listings are excluded from the default grid and reachable by filter, with a legend entry when that filter is active; an `indisponível` result flips the card immediately with the toast `anúncio saiu do ar`

**Given** a returned Listing and a degraded Platform
**When** the price-history chart and cards render
**Then** the gap is bridged by a dashed segment with a `voltou ao mercado` annotation, and cards of a circuit-broken Platform show `plataforma sem coleta há N dias` instead of the gone treatment
**And** strings land in both catalogs and an e2e covers each Recheck result and the gone card

### Story 5.10: Favoritos shows what is verified and what left

As the operator curating favourites,
I want each favourite stamped with its last verification, and the ones that left kept in a history,
So that the live list is verified and nothing vanishes silently (UX-DR19, UX-DR20).

**Acceptance Criteria:**

**Given** per-Listing verification outcomes from Story 5.6
**When** Favoritos renders
**Then** each row carries `disponibilidade verificada há Xh` or `última verificação falhou` in its own amber state, with comparable columns for price, verdict, percentile, R$/m² and bairro, and a Recheck control per row

**Given** `favourites.reason` from Story 2.9
**When** I unstar a favourite
**Then** it takes one click, a reason is optional and never required, and the same field holds a reason set by the agent

**Given** the `mostrar indisponíveis` filter
**When** it is on
**Then** gone favourites appear dated with when they left the market, and unstarred-with-reason favourites appear with the reason; by default only live favourites show
**And** strings land in both catalogs and an e2e covers unstar-with-reason and the history filter

## Epic 6: Filter by quality

Quality dimensions are filterable by the agent and the grid, usable as profile soft preferences, and recently used filters resurface in the pickers.

### Story 6.1: Facets derived from a committed vocabulary

As the operator,
I want quality facets derived by rules I can read and extend in a config file,
So that `seguro`, `reformado` and `silencioso` are stable facts with a stated origin, and a new facet needs no code (FR-36, AD-16).

**Acceptance Criteria:**

**Given** the loader from Story 2.1
**When** this story lands
**Then** `configs/facets.yaml` (versioned) defines each facet with its derivation rule naming its inputs — neighbourhood sub-score thresholds, normalized flag sets, resolved Attributes, visual condition category, description-text matches — seeded with the three facets from the PRD addendum
**And** a rule referencing an unknown input fails startup naming the facet

**Given** a Property's inputs
**When** the facet stage runs
**Then** it writes `property_facets` rows (facet, value ∈ `yes`/`no`/`unknown`, optional confidence in [0, 1], `derived_from`, `inputs_hash`, `facets_version`, `updated_at`), skips when `inputs_hash` is unchanged, and yields `unknown` when an input is stale
**And** rows are written only by the facet stage, never into `metrics_scoring.meta` and never at read time; free-text flags that map to no facet stay flags

**Given** the stage runs in the enrichment order and inside the fit sweep
**When** a neighbourhood signal changes
**Then** the facet is re-derived without a model call
**And** the migration passes the alembic check and each seed rule has a unit test for `yes`, `no` and `unknown`

### Story 6.2: Facets as filters and soft preferences

As the agent client,
I want to filter candidates by facet and have profiles prefer them,
So that quality dimensions rank and narrow the shortlist (FR-36, FR-42).

**Acceptance Criteria:**

**Given** persisted facet rows
**When** I filter the property or Fit-status listing by a facet
**Then** it matches `yes` only unless `unknown` is explicitly requested, using the canonical English name, and an unknown facet name returns a 4xx with the allowed set

**Given** a profile soft preference on a facet
**When** the fit sweep runs
**Then** the preference evaluates from `property_facets` (`unknown` excluded from the score) and a facet change triggers re-evaluation

**Given** the Fit bundle and the facets endpoint
**When** they are serialized
**Then** each facet value states what produced it, and the vocabulary with its version is listable
**And** contract tests cover the filter, the error and the bundle part

### Story 6.3: Facet picker in the filter bar

As the operator browsing the grid,
I want to filter by quality tags from a searchable picker,
So that the grid narrows by the same facets the agent uses (FR-36 UI consumer; UX-DR26).

**Acceptance Criteria:**

**Given** the facets endpoint
**When** I open the sentiment tag picker
**Then** it is a searchable typeahead listing the vocabulary with pt-BR labels from the catalogs, with suggestions inside the picker and not in the bar

**Given** active facet filters
**When** the filter bar renders
**Then** chips collapse under the hard 2-line ceiling and overflow into `Filtros (N)`, the header height stays constant, and filters round-trip through the existing filter state
**And** a new facet added to the vocabulary appears without a frontend change beyond its catalog label, and an e2e covers pick → grid filtered → chip removed

### Story 6.4: Recent filters resurface in the pickers

As the operator,
I want my recently used neighbourhoods, property types and price ranges offered again,
So that repeating a search takes one click (FR-38; UX-DR27).

**Acceptance Criteria:**

**Given** I have applied filters before
**When** I open the neighbourhood, property type or price picker
**Then** the last N values used (N config-owned in the frontend) are offered as reuse suggestions inside the picker, with price ranges remembered per listing type

**Given** the filter reset
**When** I clear filters
**Then** the recent suggestions are cleared too
**And** the feature is frontend-only (AD-8), strings land in both catalogs, and an e2e covers reuse and reset

## Sequencing gates and Parallel work plan

Gates are written `story ← prerequisites`. Stories from different epics run in the same wave when their gates allow.

**Gates**

- Epic 1: `1.2←1.1`, `1.3←1.1`, `1.6←1.3+1.4+1.5`, `1.7←1.6`, `1.8←1.2+1.7`, `1.9←1.6`, `1.10←1.9`; `1.18` has no gate (added 2026-10-08, runs as soon as it is minted). Stories 1.13 and 1.14 carry an advisory re-scope on the spike verdict (Story 3.2); it is not a gate.
- Epic 2: `2.2←2.1`, `2.3←2.2`, `2.4←2.2+1.1`, `2.5←2.4`, `2.6←2.5+1.2`, `2.7←2.6`, `2.8←2.7+1.3`, `2.9←2.8`, `2.10←2.9`.
- Epic 3: `3.2←3.1`, `3.5←3.4+3.3`, `3.6←3.2+3.3+2.2`, `3.7←3.5+3.6`, `3.8←3.3+2.7`, `3.9←1.8+3.7+2.7`.
- Epic 4: `4.1←2.1`, `4.2←4.1`, `4.3←4.2`, `4.4←4.2+2.8`, `4.5←4.4`.
- Epic 5: `5.2←5.1`, `5.3←5.2`, `5.4←5.1`, `5.5←1.16+5.4`, `5.6←5.5`, `5.7←5.4`, `5.8←5.7+1.8`, `5.9←5.5+1.8`, `5.10←5.6+2.9`.
- Epic 6: `6.1←2.2+2.5+3.3`, `6.2←6.1+2.8`, `6.3←6.2`, `6.4` has no gate.
- Added at the readiness gate (2026-10-07): `3.9←2.7` (its AC reads the Story 2.7 projection), `5.8←1.8` (an alert click opens the detail side panel), `6.1←2.5+3.3` (the facet stage runs inside the fit sweep and in the enrichment dependency table). Bundle parts whose source story lands before Story 2.7 (availability from 5.4, Photo evidence reference from 3.7) are wired into the bundle by 2.7; see the sequencing notes on those stories.

**Serial surface — `src/api/schemas.py`:** edited by 1.2, 1.7, 1.10, 1.13, 1.16, 2.6–2.10, 4.1, 4.4, 5.2, 5.4, 5.5, 5.7 and 6.2. Only one of these is in flight at a time; inside a wave they run in story-number order, and the chain 2.6 → 2.7 → 2.8 → 2.9 → 2.10 is strictly serial.

**Waves** (a story appears in the first wave its gates allow; stories in the same wave that share a do-not-parallelize entry run one after the other)

- **Wave 0 — start here (file-disjoint):** 1.1, 1.4, 1.11, 1.15, 1.16, 1.17, 1.18 (added 2026-10-08), 2.1, 3.1, 3.4, 5.1, 6.4.
- **Wave 1:** 1.2, 1.3, 1.5 (operator applies migrations; this also applies the 2-7 repair), 1.12, 2.2, 3.2 (spike), 3.3, 4.1, 5.2, 5.4.
- **Wave 2:** 1.6, 1.13, 2.3, 2.4, 3.5, 4.2, 5.3, 5.5, 5.7.
- **Wave 3:** 1.7, 1.9, 1.14, 2.5, 3.6, 4.3, 5.6.
- **Wave 4:** 1.8, 1.10, 2.6, 3.7, 6.1.
- **Wave 5:** 2.7, 5.8, 5.9.
- **Wave 6:** 2.8, 3.8, 3.9.
- **Wave 7:** 2.9, 4.4, 6.2.
- **Wave 8:** 2.10, 4.5, 5.10, 6.3.

**Tier 1 critical path (aluguel-2027 decision, first usable at the end of Wave 5):** 1.1 → 2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6 → 2.7, with 3.1 → 3.2 → 3.6 → 3.7 for evidence, 4.1 → 4.2 → 4.4 for car minutes and 5.4 → 5.5 → 5.6 for liveness. Tier 2 (slips first): 4.3, 4.5, all of Epic 6, 5.1–5.3, 5.7–5.8, 5.10, 1.12–1.15.

**Do not parallelize**

- Any two stories editing `src/api/schemas.py` (order above).
- 1.3 with 1.6 (both change `scoring.py`; 1.3's characterization lock must land first).
- 1.6 before 1.5 is `done` (percentiles over known-fabricated scores) — this gate is not machine-enforced while 1.5 waits on the operator.
- 3.3 with 3.5, 3.6, 3.7 or 3.8 (all touch `run_enrichment` and the enrichment pipeline; 3.3 retires the `stages` literals first).
- 3.4 with 2.2 or 2.3's merge-path work (all touch `core/dedupe.py` and the persist path).
- 1.1 with 2.3 and 5.4 (all change the scraper normalize/persist path).
- 1.12, 1.13 and 1.14 with each other (`backfill_runner.py` and the Gemini client).
- 1.4 with anything else touching `scripts/` (harness-marked tests run about 14 minutes serial).
- 1.18 with any story that edits `task_routes`, the beat schedule or the worker services in `docker-compose.yml` (2.3, 2.5, 4.2 and 5.6 each add a routed beat task; a task added while 1.18 is in flight must be routed to the queue 1.18 introduces, not to `scrapers`), and with 1.4 (both touch `scripts/`).
- 2.1, 4.1 and 6.1 with each other (`src/infra/config.py` loader).
- 1.8, 3.9 and 5.9 with each other (detail side panel); 1.7, 4.5, 6.3 and 6.4 with each other (filter bar).
- Anything requiring the primary migration while a backfill is running — `migrate-primary.sh` enforces it; never delete its Redis keys.

**Operator actions, batched per wave:** migrations land in 1.1, 1.6, 1.9, 1.10, 1.16, 2.2, 2.5, 2.9, 3.4, 4.2, 5.1, 5.4, 5.7 and 6.1. Apply once per wave with `bash scripts/agent/migrate-primary.sh`. Other operator-only steps: author `configs/anchors.local.yaml` (4.1), fetch the OSM extract and GTFS feed and build routing graphs (4.2, 4.3), install Strata on the host for the spike (3.2), trigger the one-off visual catch-up rerun (3.5).
