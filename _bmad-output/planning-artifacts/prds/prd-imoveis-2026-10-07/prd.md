---
title: Imoveis — Deal Tracker
status: final
created: 2026-10-07
updated: 2026-10-07
supersedes: prds/prd-imoveis-2026-08-05/prd.md
---

# PRD: Imoveis — Deal Tracker

*Versioned refresh: baseline is everything shipped through v0.12 plus the finished v0.13 epics; planning target is a **re-scoped v0.14**. The product's primary job changes in this version.*

## 0. Document Purpose

This PRD is for Felipe (builder, operator, and the only user), the downstream BMad architecture and epics workflows, and bmad-loop execution. It supersedes the 2026-08-05 PRD. That PRD's planning target (v0.13) is mostly delivered: Epic 1 (FR-27–FR-29) and Epic 3 (enrichment hardening) are `done`; Epic 2 (FR-30, FR-32) is in flight and is **not re-litigated here** — its status is folded in as baseline/in-flight (§4.2).

**What changed (change signal, Felipe, 2026-10-07 — `[ASSUMPTION: the pasted Intent block is the signal of record; the named NEXT file is absent]`):** the product's primary job moves from *"generic deal tracker for Belo Horizonte"* to *"decision engine for two concrete searches run by one operator, with an AI agent (Claude Code) as the main query client and the React UI as a secondary surface."* The v0.14 wave (FR-33–FR-38) is kept but re-scoped around that signal: FR-35 and FR-36 are promoted and redefined, FR-33/34/37/38 stay as planned, FR-31 is proposed back from the debt ledger because one of the two searches has a total-cost hard constraint (confirmation requested, §9 Q1), and four new FRs (FR-39–FR-42) are minted.

Shipped implementation details live in `docs/features/` and `docs/architecture.md`, not here. Technical depth that belongs to architecture (backend candidates, routing mechanics, field-coverage matrices, photo-pipeline constraints) lives in `addendum.md`. Inferences made without explicit product confirmation are tagged `[ASSUMPTION]` and indexed in §11.

## 1. Vision

Imoveis is a **local-first decision engine** for two real searches: an apartment to rent in Belo Horizonte by March 2027 (**aluguel-2027**) and a larger home to buy around mid-2028 (**compra-2028**). It keeps scraping QuintoAndar, OLX and ZapImóveis, keeps merging the same physical home into one Property, keeps watching prices — but the question it now exists to answer is narrower and sharper: **"which of today's listings fit *my* search, how well, and what do I need to verify before visiting?"**

The operator's main way of asking that question is an **AI agent (Claude Code)** that queries the system and writes a **Dossier**: a ranked shortlist for a Search Profile, each candidate with its structured Attributes (and where each came from), its Total Monthly Cost, its travel time in minutes to the operator's personal Anchors, its verdicts, its price history, and its listing links. The React UI remains available for browsing, map context, Favoritos and operations, but it is a **secondary surface**: no new screens are built unless a requirement cannot be exercised any other way.

Two product truths carry over unchanged. **Local-first (NFR-1):** enrichment runs on the operator's AMD RX 7900 XT 20 GB through Ollama (host RAM and free NVMe are not recorded here — checking them against the Strata requirement in §6.4 is the spike's first step); a quota-bounded cloud assist exists only for batch backfill; nothing in this version makes cloud required. **Honest absence:** what the pipeline does not know, neither the UI nor the agent invents — an unknown Attribute is `unknown`, an unroutable travel time is `unknown`, a blocked availability probe is `unknown`, never a guess.

**Geographic focus:** Belo Horizonte / MG. Both Search Profiles are BH searches `[ASSUMPTION: compra-2028 is also BH — the change signal does not state a geography for it]`. SP/Campinas data still flows opportunistically; multi-city stays a v0.15+ candidate.

**Product language and surfaces:** pt-BR UI default (NFR-7) with en/pt-BR catalogs; canonical wire values English. Dossiers are written in the operator's language by the agent, from English wire data. Desktop browser only for the UI; the agent reads JSON.

## 2. Target User

### 2.1 Jobs To Be Done

- **Functional:** For each active Search Profile, know at any moment which Properties fit the hard constraints, which fit pending verification, and how they rank on the soft preferences.
- **Functional:** For any candidate, get one Dossier that answers the visit-or-skip question: Attributes with provenance, Total Monthly Cost, minutes to each Anchor by car and by transit, verdicts, price history, availability, links.
- **Functional:** Trust that a "2 quartos, 1 vaga, elevador, academia" claim is backed by scraper data, listing text, or photos — and know which.
- **Emotional:** Spend evenings deciding, not browsing. Reduce the fear of missing the one good flat.
- **Contextual:** Everything on the operator's machine; the agent talks to a local API; listing data never leaves the box except through the sanctioned batch backfill path.

### 2.2 Non-Users (current product)

- Anyone but the operator. Single-tenant by design (nullable `owner` stays; no multi-profile-per-user model).
- Multi-tenant agencies, brokerages, portals; national multi-city users.
- Users who need a fully offline map or a mobile surface.

### 2.3 Key User Journeys

The operator is the single persona; earlier generic personas (Ana, Bruno) are retired. UJ-3 and UJ-4 (operate the pipeline unattended; cloud-quota backfill) remain of record in the 2026-08-05 PRD and are unchanged.

- **UJ-5. Felipe asks the agent for tonight's aluguel-2027 shortlist.**
  - **Persona + context:** Felipe, after work, in Claude Code, not in the browser.
  - **Entry state:** Stack scraping on schedule; Search Profile `aluguel-2027` active; Anchors configured.
  - **Path:** Asks the agent "o que apareceu de novo para o aluguel-2027 esta semana?" → agent queries the profile-fit surface (FR-41/FR-42) → gets candidates with Fit status, Total Monthly Cost (FR-31), Attributes with provenance (FR-39), travel minutes to each Anchor (FR-35) → asks for a Dossier (FR-40) of the top three → opens the listing links.
  - **Climax:** One candidate reads `fits` on every hard constraint, R$ 3.650 total with condo and IPTU itemized, 12 min by car to igreja, 25 min by transit to casa da Nala, elevator and gym confirmed by scraper amenities, second bedroom suitable as home office confirmed by photos — and the price dropped 6% in September.
  - **Resolution:** Felipe stars it; automatic rechecks (FR-33) keep watching availability; the agent asserts nothing it did not read from the system.
  - **Edge case:** A candidate's elevator is `unknown` (not in scraper fields, not in text, not visible in photos). The Dossier says so and lists it under "verify on visit"; it does not fail the candidate.

- **UJ-6. Felipe runs the slow compra-2028 scan.**
  - **Persona + context:** Same operator, a monthly check, buying is 18+ months out.
  - **Entry state:** Search Profile `compra-2028` active; no alerts expected — watch the market, not the inbox.
  - **Path:** Asks the agent for the compra-2028 picture: how many sale Properties fit (3–4 bedrooms, ≥ 2 parking), neighbourhood price/m² percentiles, which neighbourhoods keep the Anchors within acceptable minutes.
  - **Climax:** The answer is a market read, not a shortlist: price/m² by neighbourhood for the fitting cohort and a handful of standout Properties with Dossiers.
  - **Resolution:** Nothing is starred; the Search Profile version is bumped if the constraints changed.

- **UJ-7. Felipe checks a candidate's claims against evidence.**
  - **Persona + context:** Same operator, one candidate, deciding whether a visit is worth an evening.
  - **Entry state:** A Fit bundle already fetched by the agent.
  - **Path:** For one Property the agent presents each Attribute with provenance (`scraper` / `text` / `photo` / `unknown`) and the photo set the visual pass used. Where the scraper says "mobiliado: não" but the photos show furniture, the conflict is surfaced, not resolved silently.
  - **Climax:** Felipe decides whether to visit knowing exactly which claims are unverified.
  - **Resolution:** The unverified items become the visit checklist; nothing in the system is marked verified until Felipe says so.

## 3. Glossary

Downstream workflows use these terms exactly. Terms defined in the 2026-08-05 PRD and unchanged here (Property, Listing, Platform, Dedupe, Deal verdict, Stat score, Cloud assist, Backfill runner, Quota pacer, Watchlist / starred = watched, Favourite / Saved search, Recheck, Gone / voltou ao mercado, Enrichment, Semantic search) remain of record there.

- **Search Profile** (short form in this document: *profile*) — A versioned, operator-owned definition of one real search: listing type, geography, **hard constraints** (must hold or the Property fails), **soft preferences** (desirable; contribute to ranking), and a horizon date. Lives in `configs/` under version control; two exist: `aluguel-2027` and `compra-2028`. A Saved search (FR-14) is a UI filter preset; a Search Profile is a product object with evaluation semantics.
- **Fit status** — The result of evaluating one Property against one Search Profile: `fits` (all hard constraints hold on known data), `fits-pending-verification` (no hard constraint fails, at least one relevant Attribute is `unknown`), `fails` (with the failing constraint named), `out-of-scope` (wrong listing type or geography).
- **Attribute** — A structured, typed fact about a Property or Listing relevant to a Search Profile (bedrooms, bathrooms, suites, parking spots, furnished, elevator, gym in building, split-AC, floor, home-office-capable room, pets). Every Attribute value carries a **provenance**: `scraper` (platform structured field), `text` (extracted from listing description), `photo` (inferred from the photo set), or `unknown`. Conflicts between provenances are kept, not collapsed.
- **Total Monthly Cost** — Rent + condo fee + IPTU, normalized to a monthly amount per Listing, with each component itemized or marked `unknown` and a `bundled` flag when the platform publishes a combined figure. Never imputed.
- **Anchor** — A named personal place the operator travels to (igreja — Palmares; casa da Nala — Santo Antônio; casa da mãe — Planalto; Centro; aulas de música — walking distance from the current home). The UX contract's **POI** — same object. Versioned beside the Search Profiles; the **schema** is committed, the **coordinates are personal data and live in a git-ignored local config file** (same posture as `.env.local`), never in the pushed repository.
- **Travel time** — Minutes from a Property's location to an Anchor, per **mode** (`car`, `transit`, and `walk` for Anchors that declare a walking budget), with a departure-time assumption and a provider stamp; `unknown` when no provider can route it. Never expressed in km.
- **Fit bundle** — The machine-readable FR-40 payload for one Property × Search Profile: Fit status with the per-constraint check list (Attribute values + provenances), soft score, Total Monthly Cost breakdown, travel times per Anchor and mode, existing verdicts (stat, visual, sentiment, Deal verdict), price-history summary, availability state, Photo evidence reference, listing links, and an `unknown_count`. The agent reads Fit bundles; it never reads the DB.
- **Fit summary** — The short natural-language, profile-aware sentence generated by a text task class and carried inside the Fit bundle; distinct from the Deal verdict (which is profile-agnostic).
- **Dossier** — An agent-produced decision document for one Search Profile or one Property, assembled only from machine-readable system data (FR-42) and written for the operator. The system produces the data; the agent writes the prose.
- **Agent query client** — Claude Code (or any HTTP client acting for the operator) reading the system through the API-key-gated interface (transport is the FR-42 `[ASSUMPTION]`: existing REST API). The primary consumer of this version's capabilities.
- **Sentiment facet** — A named, filterable quality dimension of a Property (e.g. `seguro`, `reformado`, `silencioso`) derived from FR-24/FR-26 signals and FR-39 Attributes; the vocabulary is extensible, not closed.
- **Photo evidence** — The downloaded, gated photo set of a Property that AI passes read; subject to the photo gate (minimum gallery size) and the per-property image cap.
- **Spike** — A time-boxed technical evaluation with stated exit criteria that produces a decision, not product scope. The **Strata spike** (§6.4) is the one spike in this version.

## 4. Features

FR numbering is global and stable across PRD versions (FR-1–FR-38 keep their IDs; new IDs continue from FR-39). Section numbering restarts here.

### 4.1 Baseline — FR-1–FR-26 (shipped, v0.1–v0.12)

Unchanged; definitions of record in the 2026-07-23 and 2026-08-05 PRDs. Implementation truth in `docs/features/`.

### 4.2 v0.13 status — folded in, not re-litigated

| Epic | FRs | Status (sprint-status.yaml, 2026-10-07) |
|------|-----|------------------------------------------|
| Epic 1 — Hybrid enrichment, productized | FR-27 routing by task class, FR-28 quota-governed backfill surface, FR-29 coverage telemetry | **done** (s1.1–s1.6; retro done) |
| Epic 3 — Enrichment hardening & operability | hardening of FR-27–FR-29 (runner hosting, circuit breaker, budget accounting, checkpoint semantics, env contract) | **done** (s3.1–s3.5; retro done; 3 retro items open) |
| Epic 2 — Deal-intelligence deepening | FR-30 price/m² percentile views, FR-32 saved-search new-match alerts | **in flight / backlog**: s2.6 done, s2.7 `awaiting-operator` (primary migration via `migrate-primary.sh`), s2.1–s2.5 backlog; gate s2.1 ← s2.7 + DW-32 |

**Status note on FR-30:** the change signal describes FR-30 as done. The tracker disagrees — stories 2-1 (cohort percentile pipeline) and 2-2 (badge + filter) are `backlog`. A per-cohort `percentile_rank` **column** has existed since BIN-84 (rent/sale split) and is already in the API, which is likely what "done" refers to. This PRD records the tracker's state and leaves Epic 2's run order untouched. `[NOTE FOR PM]` Confirm whether Epic 2 finishes before v0.14 starts or runs beside it (§9 Q3).

FR-31 (total-cost normalization) was deferred at the 2026-08-05 epics pass. **This version proposes un-deferring it** (pending §9 Q1) — see FR-31 in §4.3 and the conflict note there.

### 4.3 v0.14 — Decision engine for two searches (planned, re-scoped)

**Description:** The 2026-08-05 PRD scheduled FR-33–FR-38 as "make the designed experience real end-to-end." The change signal keeps those FRs but re-centres the wave: the experience that must be real is the **operator asking an agent about two concrete searches and getting a trustworthy answer**. That requires the system to hold the operator's searches as product objects (FR-41), know the Attributes those searches depend on with provenance (FR-39), normalize what a flat really costs per month (FR-31), know how far each Property is from the operator's life in minutes (FR-35), expose quality dimensions as facets (FR-36), produce the decision data a Dossier is written from (FR-40), and do all of it through an interface an agent can read (FR-42). Availability truth (FR-33/34), operator trust (FR-37) and filter recall (FR-38) stay as planned because a Dossier is only as good as the liveness of the listings in it.

**Theme:** one operator, two searches, agent-readable truth.

**Exit criteria:**
- Both Search Profiles are versioned in `configs/`, load at startup with validation, and every active Property carries a Fit status per profile that the agent can list, sort and filter.
- For the aluguel-2027 cohort, ≥ 90% of Listings have a Total Monthly Cost with every component either itemized or explicitly `unknown`/`bundled` — none imputed.
- Every Attribute a Search Profile references is stored with provenance for every active Property; conflicts between provenances are visible.
- Every active BH Property has car and transit minutes to every Anchor, or an explicit `unknown` with the reason.
- A Dossier for a Property can be assembled by the agent from documented read endpoints alone — no screen scraping of the UI, no DB access.
- FR-33/34/37/38 exit conditions as stated in the 2026-08-05 PRD §4.5.
- The Strata spike has a recorded verdict (adopt / reject / defer) with the A/B numbers.

#### FR-41: Search Profiles as first-class product objects

Operator defines Search Profiles in versioned config; the system evaluates every active Property against every active profile and stores a Fit status with the failing or unverified constraints named. Realizes UJ-5, UJ-6.

The two profiles of record (Felipe, 2026-10-07):

| Profile | Listing type | Hard constraints | Soft preferences | Horizon |
|---------|--------------|------------------|------------------|---------|
| `aluguel-2027` | rent, apartment, BH | bedrooms ≥ 2 with one usable as home office `[ASSUMPTION: "2 bedrooms" read as at-least-two; a 3-bedroom flat under the cap is not excluded]`; parking ≥ 1; Total Monthly Cost ≤ R$ 4.000; unfurnished | lower total cost preferred; gym in building; elevator; split-AC acceptable (not required) `[ASSUMPTION: "split-AC allowed" means presence is neutral-to-positive, absence is not penalized]` | move-in by 2027-03 |
| `compra-2028` | sale, BH `[ASSUMPTION]` | 3 ≤ bedrooms ≤ 4; parking ≥ 2 | `[ASSUMPTION: none stated yet — price/m² percentile and Anchor minutes rank the cohort until Felipe adds preferences]` | purchase ~mid-2028 |

**Consequences (testable):**
- A profile with an unknown attribute key, an unparseable constraint, or a missing listing type fails config validation at startup with the offending key named.
- Changing a profile's constraints requires bumping its version; Fit statuses are re-evaluated for the new version and the previous version's statuses are retained for comparison.
- A Property whose relevant Attribute is `unknown` is never `fails` on that constraint; it is `fits-pending-verification` with the Attribute named.
- A Property with Total Monthly Cost `unknown` cannot be `fits` for `aluguel-2027`; it is `fits-pending-verification`.
- Soft preferences never change Fit status; they only order Properties within a status. Each soft preference evaluates to `satisfied` / `not-satisfied` / `unknown`; the **soft score** is satisfied ÷ (satisfied + not-satisfied) with `unknown` excluded from both terms and reported as a count, so an unknown never helps or hurts the order. "Prefer less" cost is a monotone preference: lower complete Total Monthly Cost ranks higher within equal soft scores.
- For a Property with several active rent Listings, the **lowest complete** Total Monthly Cost decides the cap; if no Listing's total is complete the Property is `fits-pending-verification`; the deciding Listing is recorded in the Fit bundle.
- Geography predicate for `out-of-scope`: the Property's point lies within the profile's city polygon union (FR-22 neighbourhood polygons) or its address city equals the profile city; otherwise `out-of-scope`.
- `[NON-GOAL for v0.14]` profiles are not editable from the UI; config + version control is the surface. `[NON-GOAL]` per-user profiles.

#### FR-39: Structured Attribute extraction with provenance

System extracts and stores, per active Property, every Attribute a Search Profile references — bedrooms, parking spots, furnished, elevator, gym in building, split-AC, home-office-capable second room — plus the attributes scrapers already structure (bathrooms, pets) and two cheap siblings `[ASSUMPTION: suites and floor are included because compra-2028 soft preferences are expected to need them; drop if Q5 says otherwise]` — each with provenance (`scraper` / `text` / `photo` / `unknown`), using scraper structured fields first, then listing description text, then the Photo evidence. Realizes UJ-5, UJ-7.

Today, bedrooms/bathrooms/parking/furnished/pets come from scrapers; elevator and gym exist only as raw platform amenity codes (QuintoAndar, ZapImóveis) or nowhere (OLX); floor, suites and split-AC are not extracted at all; no AI pass extracts Attributes from text or photos (the sentiment pass produces free-text flags only). FR-39 closes that gap. The text extraction is a new **enrichment task class** (`attributes`) routed like the others (FR-27) — the Strata spike (§6.4) decides its local text backend; the photo-derived Attributes extend the existing visual pass.

**Consequences (testable):**
- A scraper-provided Attribute is never overwritten by a `text` or `photo` value; a disagreeing lower-provenance value is stored as a conflict beside it.
- For a fixed fixture set of ≥ 50 BH listings with hand-labelled Attributes, text extraction reaches ≥ 85% exact-match on bedrooms/parking/elevator/gym/furnished and 100% schema-valid JSON after the pipeline's retry policy `[ASSUMPTION: thresholds set here as the planning basis; the spike's A/B calibrates them]`.
- `home-office-capable` is a photo-or-text inference, never `scraper`; it is `unknown` unless a second enclosed room is evidenced.
- An Attribute pass on a Property that fails the photo gate (gallery below the floor) produces `text`/`scraper` values only and marks photo-derived Attributes `unknown`, not degraded.
- Platform amenity codes are mapped through a committed, test-covered vocabulary table; an unmapped code is logged and ignored, never guessed.

**Out of scope:** any other Attribute (e.g. view, orientation, sun exposure) — add when a profile needs it.

#### FR-31: Total Monthly Cost normalization (un-deferral proposed, redefined)

System computes, per rent Listing, a Total Monthly Cost = rent + condo fee + IPTU/month, with each component itemized, `unknown` when the platform does not publish it, and `bundled` when the platform publishes a combined figure that cannot be split. Realizes UJ-5. Sale Listings carry condo fee and IPTU/month as carrying-cost context, not a total.

Today QuintoAndar and OLX fold condo and IPTU into the Listing `price`, ZapImóveis does not; ZapImóveis IPTU is often annual and stored as published; OLX uses zero for a missing fee in the sum while storing `None`. FR-31 makes the figure comparable across platforms and honest about gaps.

**Consequences (testable):**
- For the same fixture Listing on two Platforms, Total Monthly Cost agrees within the published component differences — the base rent is never counted twice.
- An annual IPTU is converted to monthly with the conversion recorded; a value whose periodicity is ambiguous is `unknown`, not divided.
- A missing component is `unknown`; it is never treated as zero in the total. A total with any `unknown` component is itself marked incomplete.
- The `aluguel-2027` cap compares against the complete total only; incomplete totals yield `fits-pending-verification`.
- A sale Listing exposes monthly condo fee and IPTU with the same `unknown`/periodicity rules; no total is computed for sale.

`[NOTE FOR PM]` **Conflict with a prior decision:** FR-31 was deferred at the 2026-08-05 epics pass for data-availability risk. The aluguel-2027 hard constraint is a total-cost cap, so the capability is now load-bearing. This PRD un-defers it; the risk is handled by the `unknown`/`bundled` semantics rather than by waiting for coverage. Confirm (§9 Q1).

#### FR-35: Travel time to personal Anchors (promoted, redefined)

System computes, per active Property, the travel time in minutes to each Anchor by `car` and by `transit` (and by `walk` for Anchors that declare a walking budget), stores each with a provider stamp and a departure assumption (default **weekday 08:00 local**, configurable per Anchor `[ASSUMPTION: default departure time]`), and exposes them to the agent and to Search Profile soft preferences. Realizes UJ-5, UJ-6. Map travel-time bands (the 2026-08-05 FR-35) become a secondary UI consumer of this data, not the FR's definition.

Today travel minutes exist only per **neighbourhood** (polygon representative point → two fixed BH hubs, driving only, OSRM when configured or a haversine estimate otherwise). FR-35 moves the origin to the Property, the destinations to the operator's Anchors, and adds a transit mode.

**Consequences (testable):**
- Anchors are defined in versioned config beside the Search Profiles; an Anchor without coordinates fails validation. Anchor coordinates (and the current-home location) load from a git-ignored local file; a committed file containing coordinates fails a unit test, mirroring the all-local `app_config.yaml` pin.
- Every active BH Property has, per Anchor, a `car` and a `transit` value in minutes or `unknown` with a reason (`no-provider`, `unroutable`, `outside-coverage`).
- A haversine estimate is never presented as a travel time; if no routing provider is available the value is `unknown`, and the estimate (if kept) is labelled as such.
- Minutes are the only unit anywhere the value is shown — API, Dossier data, UI. No km field is exposed.
- Travel times are recomputed when a Property's location changes or an Anchor version changes, not on every scrape.
- `aulas de música` is modelled as an Anchor at the current home with a walking budget, so `walk` is computed for that Anchor only `[ASSUMPTION: the constraint "walking distance from current home" is really a constraint on distance to the current home; modelled as an Anchor with a walking-minutes budget rather than a special case]`.

**Notes:** transit routing needs a schedule-aware router (GTFS) — the local-first choice and its fallback are an architecture decision with a product tension recorded in §9 Q2.

#### FR-36: Sentiment facets as structured, agent-readable dimensions (promoted, redefined)

System exposes quality dimensions of a Property as named Sentiment facets with an extensible vocabulary — seeded with `seguro`, `reformado`, `silencioso` — derived from FR-24 neighbourhood quality, FR-26/sentiment flags and FR-39 Attributes; facets are filterable in the API (and therefore by the agent) and usable as Search Profile soft preferences. Realizes UJ-5, UJ-6. The grid filter picker from the 2026-08-05 definition remains a UI consumer.

Today the sentiment pass yields a 5-value category and free-text green/red flags in the output language; neighbourhood quality yields four numeric sub-scores and a small risk-flag vocabulary. FR-36 turns these into a stable facet vocabulary with provenance, without closing the set.

**Consequences (testable):**
- A facet value is tri-state (`yes` / `no` / `unknown`) with an optional confidence in [0, 1]; filters match `yes` only unless `unknown` is explicitly requested.
- The facet vocabulary is a committed, versioned list where each facet names its **derivation rule** (which sub-score threshold, which normalized flag set, which Attribute); a new facet is added by a vocabulary change, not a code change, and unknown facet names in a filter return a 4xx with the allowed set. Seed derivations are in `addendum.md`.
- Each facet value on a Property states what produced it (neighbourhood signal, text flag normalization, Attribute) and is filterable with the canonical English wire name; pt-BR labels come from the i18n catalogs.
- Free-text flags that normalize to no facet are kept as flags and never silently become a facet.

#### FR-40: Decision data for Dossiers (Fit bundle + Fit summary)

System produces, per Property × Search Profile, a **Fit bundle** (glossary §3) and, inside it, a **Fit summary** generated by a profile-aware text task class alongside `deal_verdict`. Realizes UJ-5, UJ-6, UJ-7.

The Dossier itself is written by the agent (FR-42 client) from Fit bundles. The system never fabricates a field the Fit bundle does not hold.

**Consequences (testable):**
- The Fit bundle is complete or explicitly marks each missing part `unknown` (`not-computed` vs `unavailable` are distinct reasons) and carries `unknown_count`.
- The Fit summary names at least one hard constraint and one unverified Attribute when any exist; it never contradicts the structured Fit status.
- Fit bundles for the same Property under two profile versions are both retrievable.
- Generating the Fit summary routes through `enrichment_routing` like every text class; with the text backend down, the Fit bundle is still served with the Fit summary `unknown`.

#### FR-42: Agent query surface

Operator's agent client (Claude Code) can read everything a Dossier needs through documented, stable, API-key-gated **read** endpoints: profiles and Anchors (with versions), Fit-status listings per profile (sortable by soft score, Total Monthly Cost, minutes to an Anchor, price drop, freshness), the Fit bundle per Property, a per-profile **cohort summary**, Sentiment facets, enrichment coverage and health. Write actions available to the agent are limited to the operator's existing single-Property actions (star/unstar with optional reason, trigger Recheck) `[ASSUMPTION: write scope is a default pending §9 Q7]`. Realizes UJ-5, UJ-6, UJ-7.

**Consequences (testable):**
- Every field in the Fit bundle is reachable through the public API schema (`src/api/schemas.py`) with contract tests; no agent path reads the DB or scrapes the UI.
- Responses carry canonical English wire values and ISO dates; the agent localizes.
- Pagination, filtering and sorting on the Fit-status listing are sufficient to fetch "everything that fits aluguel-2027 sorted by Total Monthly Cost" in one call.
- The per-profile cohort summary returns, in one call, counts per Fit status, the price/m² distribution (median, p25, p75) per neighbourhood for the `fits` + `fits-pending-verification` cohort, and the distribution of minutes per Anchor and mode — the data behind UJ-6's market read.
- Listing a profile's candidates and fetching ten Fit bundles completes within the operator's patience on the local stack: ≤ 2 s per Fit bundle, ≤ 5 s for a 200-row listing or a cohort summary `[ASSUMPTION: planning numbers; no SLO instrumented yet]`.
- `[ASSUMPTION: transport is the existing REST API consumed by Claude Code over HTTP, documented in docs/api.md with example calls; an MCP server wrapper is a later convenience, not a v0.14 requirement]`.

#### FR-33, FR-34, FR-37, FR-38 — unchanged

Definitions of record remain the 2026-08-05 PRD §4.5: FR-33 availability Recheck (on-demand + automatic priority rechecks for starred Properties, cooldown and global budget, tri-state result), FR-34 gone/resurrection lifecycle + favourite-gone alerts, FR-37 scraper run-history behavioral analytics (rolling + pinned baselines, reason strings, in-app only), FR-38 recent-filter recall. Their relation to this version: FR-33/34 keep Dossiers truthful about liveness; FR-37 keeps the operator trusting the corpus a Dossier is drawn from; FR-38 is UI-only and lowest priority in the wave. Minimum testable consequences for this wave (the epics pass may add more):

- **FR-33:** a starred Property is rechecked at least daily; a Property rechecked within its cooldown is not re-probed; a 403/Cloudflare/timeout probe yields `unknown` and leaves the freshness stamp untouched; the daily global recheck budget is config-driven and never exceeded.
- **FR-34:** a Listing absent from N consecutive **successful** coletas of its Platform (N config-driven) becomes gone; a Platform outage never marks Listings gone; a reappearance clears gone, annotates the price-history series, and fires an alert if the Property was starred; the gone→returned transition is visible in the Fit bundle's availability state. The FR-32 UI remainder (Alertas panel, desktop push) rides with FR-34's alert surface — exit: a gone-favourite alert is visible in-app without opening email.
- **FR-37:** per coleta, duration and yield are stored; deviation beyond a config-driven band from the rolling baseline **or** the pinned long-window baseline produces a reason string; below the calibration count the state is `calibrating`, not ok; no external notification fires.
- **FR-38:** the last N neighbourhoods, property types and price ranges used are offered in the pickers; cleared with the filter reset.

### 4.4 Photo evidence constraints (cross-cutting for FR-39/FR-40)

The photo pipeline shapes what FR-39's `photo` provenance can promise: galleries below the photo gate floor (currently 8) are persisted inactive and never enriched; at most 8 images per Property are downloaded, stored by content hash, and downscaled to 768 px for the model. Two carried constraints matter to this version: (a) **BIN-146 follow-up, still open** — fuzzy-dedupe merges overwrite a Property's `image_urls` and `props_json` unconditionally, so a `photo`-provenance Attribute may have been inferred from a gallery that a later merge replaced; FR-39 must either stamp the Photo evidence it used or be re-run on gallery change. (b) The visual pass on AMD is Ollama-only — the Strata candidate has no Windows vision path — so photo-derived Attributes stay on the existing visual route regardless of the spike outcome. Mechanics in `addendum.md`.

## 5. Non-Goals (Explicit)

- Cloud-hosted SaaS, multi-tenant, billing — unchanged.
- Making any cloud service **required**: not for enrichment (NFR-1), and not for routing — if transit routing needs a cloud API, it is a bounded, optional provider with `unknown` as the local fallback, never a gate (§9 Q2).
- A general-purpose "search profile builder" UI, or per-user profiles. Two profiles, in config, for one operator.
- New React screens or redesigns in v0.14. Compare stays minimal. UI changes are limited to consuming new data where an existing surface already shows the concept (map bands, filter picker, detail panel fields).
- Expressing any distance in km anywhere the operator reads it.
- Imputing missing fees, attributes, or travel times to make a Property look complete.
- Adopting Strata (or any new text backend) as an FR — it is a spike with exit criteria (§6.4); the product requirement is the capability (FR-39/FR-40), routed through the existing backend abstraction.
- Multi-city productization (v0.15+ candidate); new scrape platforms; brokerage CRM; offline maps; hot-reload of `app_config.yaml`.

## 6. Scope

### 6.1 Baseline (shipped)

FR-1–FR-29 as implemented and documented (v0.1–v0.12 + v0.13 Epics 1 and 3), including coverage telemetry, routing by task class, and the hosted backfill runner.

### 6.2 In flight — v0.13 Epic 2 (not re-planned here)

s2.7 (operator applies the corpus-repair migration) → s2.1 → (s2.2 ∥ s2.3) → (s2.4 ∥ s2.5), per epics.md. FR-30 and FR-32 deliver here. FR-32 v1 is email-only; the Alertas panel and desktop push were already deferred to v0.14 and remain so.

### 6.3 In scope for v0.14 planning / delivery

- **Foundation:** FR-41 Search Profiles + Anchors as versioned config; FR-39 Attribute schema with provenance; FR-31 Total Monthly Cost (un-deferral proposed, §9 Q1).
- **Decision data:** FR-35 travel minutes (car + transit) per Property × Anchor; FR-36 Sentiment facets; FR-40 Fit bundle + Fit summary.
- **Agent surface:** FR-42 read endpoints + contract tests + `docs/api.md` agent section (REST transport per the FR-42 `[ASSUMPTION]`).
- **Carried as planned:** FR-33, FR-34, FR-37, FR-38; the Alertas panel + desktop push leftover from FR-32.
- **Architecture inputs required before stories:** the Attribute/photo-evidence schema (storage, provenance, conflict model, gallery stamping) and the routing decision for the `attributes` text class and travel-time providers — hence `bmad-architecture` runs before `bmad-create-epics-and-stories` for this wave.
- UI consumption limited to existing surfaces: travel-time bands on the existing map, facet filter picker, detail-panel fields for Total Monthly Cost and Attributes.

**Priority tiers (what slips first):**
- **Tier 1 — needed for an aluguel-2027 decision:** FR-41, FR-39, FR-31, FR-35 (`car` mode), FR-40, FR-42, FR-33, the Strata spike.
- **Tier 2 — slips first if the wave is too large:** FR-35 (`transit` mode, map bands), FR-36, FR-34, FR-37, FR-38, the FR-32 Alertas/push remainder. compra-2028 needs nothing beyond Tier 1 plus the cohort summary.

### 6.4 Spike — Strata as local text backend (decision, not scope)

**Question:** can Strata (Qwen3.8-Flash-Next, 125B MoE, IQ2/Q2, served OpenAI-compatible with `response_format` json_object/json_schema via schema prompting + server validation) replace `qwen2.5vl:7b` on Ollama as the **text** route (`sentiment`, `attributes`, `deal_verdict`/fit summary) on the operator's RX 7900 XT, with Ollama co-resident for `visual` and `embedding`?

**Integration constraint:** config-only — the existing `lmstudio` backend + `enrichment_routing`; no new backend class. Known gaps the spike will hit (LM Studio client sends no `response_format`, hardcodes `max_tokens`, lacks `generate()` for the OLX location path) are addendum notes for architecture.

**Exit criteria (Felipe, 2026-10-07):** A/B against `qwen2.5vl:7b` on ~50 listings — Attribute extraction accuracy, JSON validity rate, seconds per Property with Ollama co-resident — using `scripts/dev/ab_gemini_vs_ollama.py` adapted. **Pass** ⇒ Strata becomes the text route for FR-39/FR-40 and the local replacement for the Gemma cloud backfill on text classes. **Fail/defer** ⇒ `[ASSUMPTION: not stated in the signal]` text classes stay on Ollama; FR-39/FR-40 ship on `qwen2.5vl:7b` with the accuracy thresholds re-baselined. The verdict is recorded in `_bmad-output/planning-artifacts/research/` and the deferred-work ledger.

**Bounds:** vision on AMD is Linux-only through a CPU encoder and unavailable on Windows — `visual` never routes to Strata; no embeddings endpoint — `embedding` stays on Ollama; host needs ≥ 32 GB RAM (64 recommended; model loads 35–55 GB) and ~80 GB NVMe; one request at a time by default (`parallel: 2` opt-in) — `gpu.semaphore_limit` and `OLLAMA_NUM_PARALLEL` must be re-tuned for co-residency; AMD path marked "not validated" upstream for images and answer quality.

### 6.5 Out of scope for v0.14 (deferred)

- Multi-city (v0.15+); per-user profiles; profile-builder UI; MCP server wrapper for FR-42 (convenience, later); km anywhere.
- Walking/cycling modes beyond the `aulas de música` walk budget `[ASSUMPTION]`.
- Historical Fit-status analytics ("how many fits per week") — the agent can derive it; no product surface.
- Export UI, auth-management UI, Compare redesign — consciously undesigned (unchanged).
- Dead-listing URL pruning, config hot-reload, image-store docstring drift (says MD5, code is SHA-256) — ledger debt.

## 7. Success Metrics

| Metric | Intent | Validates | Counter-metric (do not optimize) |
|--------|--------|-----------|----------------------------------|
| **SM-1 Decision latency** | From "what's new for aluguel-2027?" to a Dossier of the top 3 in one agent session, ≤ 10 min of operator time, weekly | FR-40, FR-41, FR-42 | **SM-C1** Dossiers that look complete by hiding `unknown`s — every Fit bundle must expose its `unknown_count` |
| **SM-2 Attribute truth** | On a hand-checked sample (≥ 50 BH listings), ≥ 85% exact-match on profile-referenced Attributes; conflicts surfaced not collapsed | FR-39 | **SM-C2** Over-confident `photo` inferences (false positives on elevator/gym/home-office) |
| **SM-3 Cost comparability** | ≥ 90% of aluguel-2027-cohort Listings with a complete or explicitly incomplete Total Monthly Cost; zero imputed components; `fits-pending-verification` share reported per Platform (ZapImóveis has no furnished field, so its share is structurally higher) | FR-31, FR-41 | **SM-C3** Totals that silently treat a missing fee as zero |
| **SM-4 Anchor coverage** | ≥ 95% of active BH Properties with car minutes to all Anchors; transit coverage reported honestly as its own % | FR-35 | **SM-C4** Haversine estimates shown as travel times |
| **SM-5 Visit yield** | Of Properties the operator visits, share that matched the Dossier's claims on hard constraints (target: no surprise on a `fits` constraint) | FR-39, FR-40, FR-41 | **SM-C5** Shortlist shrink by over-strict profile (watch `fails` reasons distribution) |
| **SM-6 Liveness** | Starred Properties verified within 24 h; gone favourites alerted | FR-33, FR-34 | **SM-C6** Recheck budget burn / shared identity blocks |
| **SM-7 Local independence** | Core pipeline + FR-39/40 text classes fully functional with cloud disabled; Strata spike verdict recorded | NFR-1, §6.4 | **SM-C7** A cloud routing or AI dependency creeping into the live path |

`[ASSUMPTION: SM-1/SM-5 are operator-reported, not instrumented; SM-2–SM-4 derive from DB queries that FR-29-style coverage telemetry can extend.]`

## 8. Non-Functional Requirements

- **NFR-1 Local-first with bounded cloud assist** — unchanged and binding. The operator hardware is AMD RX 7900 XT 20 GB + Ollama; any new text backend is local and routed through `enrichment_routing`; the committed config stays all-local; cloud assist remains batch-only backfill.
- **NFR-2 Config discipline** — unchanged; Search Profiles and Anchors are `AppConfig`-loaded, versioned files in `configs/`, validated at startup. Personal coordinates (Anchors, current home) are loaded from a git-ignored local file; only their schema is committed.
- **NFR-3 Security** — unchanged; the agent client authenticates with the same API key (per the FR-42 transport `[ASSUMPTION]`); no new auth surface.
- **NFR-4 Resilience** — unchanged; a routing provider or text backend outage degrades to `unknown` fields, never to a failed bundle.
- **NFR-5 Testability** — unchanged (`validate.sh` via `finish-feature.sh`); adds: Attribute extraction and Total Monthly Cost ship with labelled fixture sets; FR-42 endpoints ship with contract tests.
- **NFR-6 Observability** — extended: coverage telemetry (FR-29) gains per-Attribute, per-Anchor-mode and total-cost completeness rows; the Fit-status distribution per profile is a reportable figure.
- **NFR-7 i18n** — unchanged; facet names, Attribute keys, Fit statuses and provenance values are canonical English on the wire with pt-BR catalog labels.
- **NFR-8 Geography & tenancy** — unchanged (BH primary, single-tenant nullable `owner`).
- **NFR-9 Agent-readability (new)** — every operator-facing decision datum is available as structured, documented JSON with stable field names and explicit `unknown` semantics; no datum exists only as rendered UI. Breaking changes to FR-42 endpoints bump a documented API version.
- **NFR-10 Provenance & honesty (new)** — every derived fact (Attribute, cost component, travel time, facet) carries where it came from and when; conflicts are retained; nothing is imputed to fill a gap.

## 9. Open Questions

**Carried answered (for the record):** the 2026-08-05 PRD's Q1–Q2 (FR-28 surface, Theme B cut), Q4 (coverage SLO) and Q5 (FR-33–38 → v0.14) remain answered. Numbering below restarts for this PRD.

**Blocking for downstream (resolve at or before the epics pass):** Q1, Q2, Q3, Q5. **Decided unless overridden** at the named revisit point: Q4, Q6, Q7.

**Open:**

1. **FR-31 un-deferral** — this PRD reverses the 2026-08-05 epics-time deferral because aluguel-2027 has a total-cost cap. Confirm the reversal. *Owner: Felipe. Revisit: v0.14 epics pass.*
2. **Transit routing provider vs NFR-1** — transit minutes need a schedule-aware router. Options: local GTFS router (OpenTripPlanner / r5) fed by BH GTFS — heavier ops, fully local; or a cloud directions API as a bounded optional provider — simpler, sends property coordinates off-box. Product preference stated here: local first, cloud only as an explicitly enabled provider with `unknown` as default. Note that a cloud provider receives Property **and Anchor** coordinates — the Anchor egress is the sharper privacy cost. *Owner: architecture pass. Revisit: before FR-35 stories.*
3. **Epic 2 vs v0.14 ordering** — finish Epic 2 (s2.7 → s2.1 → …) before opening v0.14 stories, or run the v0.14 foundation (FR-41/FR-39/FR-31) in parallel? Shared files (`metrics_scoring`, API schemas, detail panel) argue for a gate. *Owner: Felipe at epics. Revisit: v0.14 sprint planning.*
4. **Home-office-capable room** — definition for the extractor: a second enclosed bedroom (any size)? a room with a desk visible? a described "escritório"/"home office"? Default here: second enclosed bedroom OR explicit office mention. *Owner: Felipe. Revisit: FR-39 story.*
5. **compra-2028 preferences and geography** — only hard constraints were given. BH assumed; soft preferences empty. *Owner: Felipe. Revisit: when FR-41 config is authored.*
6. **Strata spike timing** — before FR-39 stories (so accuracy thresholds are set against the winning backend) or after a first `qwen2.5vl:7b` baseline? Default here: spike first, time-boxed, since the host RAM/NVMe requirement may rule it out quickly. *Owner: Felipe. Revisit: v0.14 wave plan.*
7. **Agent write scope** — keep the agent read-only plus star/recheck, or allow it to bump profile versions / discard Properties? Default here: read + star/unstar + recheck. *Owner: Felipe. Revisit: FR-42 story.*
8. **Multi-city** — unchanged from the 2026-08-05 PRD's Q3: v0.15+ candidate.

## 10. References

- `_bmad-output/planning-artifacts/prds/prd-imoveis-2026-08-05/` — superseded PRD (FR-18–FR-38 definitions of record; UJ-3/UJ-4) and its addendum
- `_bmad-output/planning-artifacts/prds/prd-imoveis-2026-07-23/` — FR-1–FR-17 definitions of record
- `_bmad-output/planning-artifacts/epics.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml`, `deferred-work.md` — v0.13 status basis for §4.2
- `_bmad-output/planning-artifacts/ux-designs/ux-imoveis-2026-08-05/` — UX contract; origin of FR-33–FR-38; POI/band and facet-picker interaction detail
- `docs/features/BIN-182-photo-gate-floor-8.md`, `docs/features/BIN-146-tighten-fuzzy-dedup-matching.md`, `docs/features/BIN-114-bundled-condo-iptu.md`, `docs/features/BIN-127-zapimoveis-scraper.md` — photo and fee constraints behind §4.4 and FR-31
- `src/adapters/ai/{prompts,enrich_pipeline,image_store,client}.py`, `src/core/enrichment.py`, `src/core/photo_gate.py` — enrichment surface grounding
- `src/adapters/metrics/scoring.py`, `src/core/neighbourhood_quality.py`, `src/core/neighbourhood_access.py`, `src/adapters/geo/osrm_client.py` — scoring/travel grounding
- `src/adapters/scrapers/{quintoandar,olx,zapimoveis}.py` — field coverage grounding
- `configs/app_config.yaml` (`ai.*`, `scoring.*`, `neighbourhood_quality.*`, `transit.*`, `photo_gate.*`)
- `scripts/dev/ab_gemini_vs_ollama.py` — A/B harness to adapt for the Strata spike
- Strata: `github.com/Niko1221/Strata` (caller-supplied facts; see addendum)
- ADR 0002/0003/0004/0005/0006; `_bmad-output/project-context.md`

## 11. Assumptions Index

- §1 / FR-41 — `compra-2028` is a Belo Horizonte search (geography not stated in the signal).
- FR-41 — "split-AC allowed" = neutral-to-positive presence, no penalty for absence.
- FR-41 — `compra-2028` has no soft preferences yet; percentile + Anchor minutes rank the cohort.
- FR-39 — 85% exact-match / 100% schema-valid thresholds are planning numbers calibrated by the spike A/B.
- FR-35 — `aulas de música` is modelled as an Anchor at the current home with a walking-minutes budget.
- FR-42 — transport is the existing REST API over HTTP from Claude Code; MCP wrapper is later.
- FR-42 — ≤ 2 s per bundle / ≤ 5 s per 200-row listing are planning numbers, not instrumented SLOs.
- FR-42 — agent write scope (star/unstar + Recheck) is a default pending §9 Q7.
- FR-39 — suites and floor are extracted on the expectation that compra-2028 preferences will need them (§9 Q5).
- §6.4 — the fail/defer outcome (text classes stay on Ollama, thresholds re-baselined) is this PRD's default, not a stated decision.
- FR-41 — "2 bedrooms" is read as bedrooms ≥ 2 (a 3-bedroom flat under the cap is not excluded).
- FR-35 — default departure time weekday 08:00 local, configurable per Anchor.
- §7 — SM-1/SM-5 operator-reported; SM-2–SM-4 DB-derived.
- §6.5 — walking/cycling modes beyond the music-lessons walk budget are out of scope.
- §0 — the change-signal file named in the invocation (`NEXT-bmad-prd-update-2026-10-07.md`) does not exist in the checkout; the pasted Intent block is the signal of record.
