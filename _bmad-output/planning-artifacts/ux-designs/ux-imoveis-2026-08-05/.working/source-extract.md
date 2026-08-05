# Source Extract for UX Design — Imoveis (2026-08-05)

Sources read in full: `prds/prd-imoveis-2026-08-05/` (prd.md, addendum.md, .memlog.md), `epics.md`, `architecture/architecture-imoveis-2026-07-23/` (ARCHITECTURE-SPINE.md, COMPANION-architecture-delta.md, .memlog.md, all 7 reviews/). Everything below is quoted or paraphrased from those files; nothing invented.

## 1. Product scope & users

- **What it is (PRD §1):** "a **local-first** deal tracker for Brazilian real-estate listings. It continuously scrapes multiple platforms, merges the same physical property into one record, watches prices over time, and enriches listings with AI … so a human can shortlist and act before a good deal disappears." Turns fragmented QuintoAndar/OLX/ZapImóveis noise "into a single score-coloured view with alerts."
- **Geography:** "Belo Horizonte / MG is the primary product geography"; SP/Campinas data is opportunistic; spine convention: "config may allow more, UX stays BH-first."
- **Deployment posture:** "single-operator, privacy-preserving, runs on the user's machine (Docker + host Ollama)" — the React app is opened "on localhost" (UJ-1).
- **Tenancy:** single-tenant, nullable `owner` (NFR-8); one principal model (AD-11).
- **Jobs To Be Done (PRD §2.1):** discover/compare rent + sale listings across platforms without tab-hopping; know when a watched property drops in price or "looks cheap vs neighbourhood peers"; judge listing quality from photos + text + stats without pasting into a cloud chat; emotional: "Feel in control of a chaotic market; reduce FOMO and second-guessing."
- **Personas (User Journeys, PRD §2.3):**
  - **UJ-1 Ana** (renting in BH, "checks listings most evenings after work"): Opens Properties → filters neighbourhood/price → scans score-coloured cards → opens modal for price history + deal verdict → stars a favourite. Climax: same flat from QuintoAndar and OLX shown as **one** property with comparable platform prices. Resolution: "she can return tomorrow without rebuilding filters." Edge: one platform circuit-broken — "she still sees the other listing and a degraded platform set."
  - **UJ-2 Bruno** (buying in BH, "watches 8–12 candidates"): authenticated via API-key gate; beat scrapes → dedupe detects lower price → notifier fires on his configured channel → he "confirms the drop on the price-history chart." Edge: "Drop is below his min threshold — no alert (noise control)."
  - **UJ-3 Felipe** (builder/operator): "Admin panel → check queue/GPU → trigger scrape or wait for beat → watch AI enrichment throughput on Dashboard." Pipeline runs unattended overnight.
  - **UJ-4 Felipe** (cloud backfill): kicks off quota-paced backfill; "checks coverage telemetry mid-run and sees % enriched climbing and a credible ETA."
- **Non-users (§2.2):** agencies needing SSO/RBAC/client portals; users needing fully offline maps; national multi-city power users.

## 2. Stated UI surfaces (named in the sources)

| Surface | Named by |
| --- | --- |
| **Properties page / score-coloured property grid** ("score-coloured cards") | FR-12; UJ-1; CLAUDE-level framing "score-coloured deal dashboard" |
| **Filters** (neighbourhood/price; "filter bar", "existing filters state hooks") | FR-12; UJ-1; Story 2.2 |
| **Interactive map + viewport bbox** (maplibre-gl) | FR-13 (per prd-reconcile review §8); stack table |
| **Property detail modal** — price history + deal verdict | UJ-1; FR-5; Story 2.2 ("card/modal") |
| **Price-history chart** | UJ-2 |
| **Per-platform price comparison** on one Property | FR-6; UJ-1 climax |
| **Side-by-side comparison view** (2–4 properties) | FR-18 |
| **Favourites (starring) & saved searches** (named filter presets) | FR-14; Glossary |
| **Semantic search** free-text (`GET /properties?q=`) | FR-15; Glossary |
| **Watchlist + price-drop alerts** (threshold-gated) | FR-16; UJ-2 |
| **Export + weekly digest** | FR-21 |
| **Auth / API-key gate + key management** | FR-19; UJ-2 entry state |
| **Admin panel** — queue/GPU status, trigger scrape, schedules, health, enrichment throughput | FR-17; UJ-3 |
| **Dashboard** (AI enrichment throughput; distinct mention from admin in UJ-3) | UJ-3 |
| **Admin backfill card** — state (idle/running/paused/backing-off), progress, today's budget use, throughput, ETA, start/pause/resume controls | FR-28; Story 1.6 |
| **Per-signal-type coverage display** (% enriched) in admin panel | FR-29; Story 1.6 |
| **Percentile on card/modal + percentile filter** (e.g. "≤ 25th percentile in cohort") | FR-30; Story 2.2 |
| **Saved-search "notify-on-new-match" toggle** in saved-search list, "alert state visible at a glance" | FR-32; Story 2.4 |
| **Locale preference** (`ui.locale` / Redis override) | NFR-7 |
| **Non-blocking error toasts** | Spine conventions ("API errors non-blocking for UI toasts"); Stories 1.6, 2.4 |

## 3. Functional requirements with UX implications

- **FR-12–FR-15 "discovery UX"** (epics.md): "score-coloured grid, filters, favourites/saved searches, semantic search". FR-12 filter dimensions and FR-13 map/bbox exist but are only detailed in the *superseded* 2026-07-23 PRD (FR-1–17 "definitions of record" live there / `docs/features/`).
- **FR-16:** price-drop notifications "past a threshold"; counter-metric "alert spam (sub-threshold, duplicates)".
- **FR-18:** side-by-side comparison; consumes the AD-12 canonical projection.
- **FR-21:** export + digest — digest items use the same projection; one notifier preference registry (AD-9).
- **FR-24:** neighbourhood quality profiles (sentiment/quality per neighbourhood). **FR-25:** "rent and sale listings on one Property scored per listing type" — cards must respect `utils/primaryListing.ts` for dual-type Properties (Story 2.2). **FR-26:** listing-description enrichment (condition cues, amenity extraction, red flags).
- **FR-27:** routing config — UX-relevant consequence: "with cloud unavailable … enrichment degrades to the local path without operator intervention" (invisible degradation, no error state for the user).
- **FR-28:** backfill start/pause/resume; "an active backfill is operator-visible" is an invariant (AD-13); starting while lease held → "conflict response naming the active run" (Story 1.5), rendered as non-blocking toast (Story 1.6).
- **FR-29:** per-signal-type coverage %, throughput, projected completion date; "with no active backfill, throughput/ETA fields are absent or null — never fabricated" (Story 1.4).
- **FR-30:** percentile "on card/modal, filterable"; suppressed on cohorts below config-owned min size — "suppressed (null) percentiles render as absent — no fake '50th percentile' placeholder" (Story 2.2); per-listing-type percentile on dual rent/sale Properties; filter must respect `price_type`/listing-type semantics ("BIN-77 lesson — no cross-type leakage").
- **FR-32:** saved-search new-match alerts; "only genuinely new Properties fire … each search × property pair notifies at most once"; per-search toggle so the user controls "alert volume per search instead of all-or-nothing" (Story 2.4).
- **i18n (NFR-7):** "English default; pt-BR supported via catalogs + preference (`ui.locale` / Redis); canonical DB/API wire values remain English; new user-facing strings must land in both catalogs." Localized AI deal verdicts (Glossary: "localized").
- **Scoring data shape:** "AI scores are floats in [0.0, 1.0]" (CLAUDE + Story 1.2/1.4); percentile is "float, nullable" (Story 2.2).
- **Resilience UX:** circuit-broken platform → "degraded platform set" still usable (UJ-1 edge); quota exhaustion → back-off, "never outages" (NFR-4).

## 4. v0.13 current work (in-flight epic set)

Theme B cut decided at epics: **FR-30 + FR-32 in; FR-31 (total-cost-of-occupancy) deferred** ("worst data-availability risk"). FR-28 surface decision: "admin-panel exposure **is** the v0.13 target… A CLI-only cut remains the fallback slice."

- **Epic 1 — Hybrid Enrichment, Productized (FR-27/28/29):** stories v0.13-s1.1…s1.6. UI touched only by **s1.6** (admin panel backfill card + coverage display; en + pt-BR strings; Playwright e2e). s1.1–s1.5 are config/pipeline/runner/API groundwork (s1.4 coverage endpoint, s1.5 admin control API feed s1.6).
- **Epic 2 — Deal-Intelligence Deepening (FR-30/32):** stories v0.13-s2.1…s2.4. UI touched by **s2.2** (percentile on card/modal + filter) and **s2.4** (saved-search alert toggle UI). s2.1 (pipeline percentiles) and s2.3 (new-match detection) are backend.
- Sequencing gates (frontmatter): s1.2/s1.3/s1.4←s1.1, s1.5←s1.3, s1.6←s1.4+s1.5, s2.2←s2.1, s2.4←s2.3. Epics 1 and 2 "share no core files and can run in parallel."
- epics.md **UX Design Requirements** section, verbatim: "No UX design contract exists for this wave… UI work in FR-28 (admin backfill card), FR-29 (coverage telemetry display), FR-30 (percentile on card/modal + filter), and FR-32 (saved-search alert toggle) follows the shipped admin-panel and property-grid patterns plus NFR-7 i18n conventions."

## 5. Technical constraints shaping UX

- **Frontend stack:** React 19.2.8, Vite 8.1.5, TypeScript strict (v0.11 migration), maplibre-gl 6.1.0. **AD-8:** "React talks only to the FastAPI surface" — no Redis/DB/Ollama from the browser (e.g. frontend cannot poll Redis for backfill state; must use API status endpoint).
- **AD-12 canonical projection:** one API-owned DTO defines primary-listing selection, price/m², enrichment fields, neighbourhood id/label for all decisioning views (grid, compare, export, digest) — UI shapes derive from this single projection, "no parallel ad-hoc flatteners".
- **Async enrichment (AD-4):** "The API never calls models inline"; AI scores/verdicts arrive later via Celery `ai` queue (single-GPU, low-concurrency) — freshly scraped listings will be visibly un-enriched for a while; skip-unchanged logic (FR-11).
- **Cloud backfill pacing:** free-tier Gemma ≈ 14,400 RPD, ~3 requests/property ⇒ ≈4,600 properties/day ⇒ "whole-DB backfill is inherently multi-day (~6 days observed planning basis)" — coverage UI is a slow-moving multi-day progress view with day-scale ETA.
- **Progress truth:** coverage/ETA derives from the **DB**, "runner Redis checkpoints are internal pacing state, never a second progress metric" (adversarial review F5 closed this two-dashboards-disagree hole).
- **Operational collision:** "a running multi-day backfill and a `validate.sh`/`finish-feature.sh` cycle must never overlap … FR-28's surface exists partly to make an active backfill visible" — visibility is part of the product contract, not ops trivia.
- **Data freshness:** scheduled beat scraping + manual scrape trigger; price history hangs on listings; per-platform failures degrade to partial platform sets.
- **Maps require network:** "Guaranteed offline maps / offline OSM tileserver" is an explicit non-goal.
- **Form factor:** localhost personal-workstation web app is the only stated context. Nothing in any source mentions mobile, responsive breakpoints, or multi-device use — **absent**.
- **Latency/AI backends:** host Ollama / LM Studio local default; cloud (Gemini/Gemma) is batch-backfill-only and never affects live UI paths.
- **Testing gate on UI stories:** Playwright e2e required per UI story (1.6, 2.2, 2.4); en + pt-BR catalogs mandatory.

## 6. Existing naming / vocabulary (mirror verbatim)

From PRD Glossary + epics/spine:
- **Property** (canonical real-world home after dedupe) vs **Listing** (platform-specific offer with own price, URL, listing type) vs **Platform**.
- **Listing types:** rent / sale (a Property can be dual; "scored per listing type", FR-25).
- **Deal verdict** — "short natural-language summary combining score, visual, and sentiment signals (localized)."
- **Stat score** — "neighbourhood-relative statistical valuation signal."
- **Description enrichment** — "condition cues, amenity extraction, red flags."
- **Dedupe**, **Enrichment**, **Semantic search**, **Watchlist**, **Favourite / Saved search** (starred shortlist / named filter preset), **Cloud assist**, **Backfill runner**, **Quota pacer**.
- **Score-coloured** (grid/cards/dashboard) — the sources' only visual-design term.
- **Enrichment task classes / signal types** — canonical enum minted in s1.1; illustrative sets in sources: routing "text signals → cloud-eligible, visual → local"; signals "visual + sentiment + verdict" (backfill config comment), plus description signals and embedding (review F3). Exact enum is s1.1's to define.
- **Backfill states:** "idle/running/paused/backing-off" (Story 1.6).
- **Cohort** — "neighbourhood × listing type" cohort for price/m² percentiles; "min-cohort size"; percentile "suppressed".
- **New match** (FR-32); **circuit breaker / circuit-broken platform**; **degraded platform set**; **skip-unchanged**.
- **Principal / owner** (AD-11) — the identity behind favourites, watchlist, saved searches, digest.
- UI-adjacent code names: `utils/primaryListing.ts`, `price_type` filter param, `public_id` (vs UUID), `ui.locale`.

## 7. Open UX questions (unresolved by the sources; a UX spine must answer or consciously defer)

1. **No visual identity exists anywhere.** No source defines colors, typography, layout, branding, tone, or what "score-coloured" concretely maps to (which scores → which colors, thresholds, ramps). Absent entirely.
2. **Accessibility:** never mentioned in any source. Absent.
3. **Dark mode / theming:** never mentioned. Absent.
4. **Responsiveness / form factors:** never mentioned beyond "opens the React app on localhost". Absent.
5. **No UX design contract for v0.13** — epics.md says UI work "follows the shipped admin-panel and property-grid patterns", but those patterns are only defined by the existing frontend code, not by any planning document.
6. **Percentile presentation:** Story 2.2 fixes data behavior (nullable, per-listing-type, filterable) but not how a percentile reads on a card ("25th percentile" vs "cheaper than 75% of Savassi rentals"), how it coexists with the existing stat score / deal verdict (review F6 warned two things named "percentile" can collide on one card), or the filter control's form.
7. **How the backfill card conveys the validate-collision warning:** visibility is mandated ("unmistakably visible"), presentation is not designed.
8. **Coverage-as-SLO:** PRD §9 Q4 open — "Should enrichment coverage targets (FR-29) become the first numeric SLOs on the dashboard?"
9. **Degraded/absent states:** sources mandate honesty (null ETA "never fabricated", suppressed percentile "renders as absent", degraded platform set) but no unified empty/degraded-state design exists.
10. **Alert/notification UX beyond delivery:** channels live in a notifier registry (AD-9); "his configured channel" (UJ-2) — which channels exist and how alert history/noise is presented in-app is unstated. Threshold configuration UX (per-watchlist min drop) unstated.
11. **Dashboard vs Admin split:** UJ-3 names both a "Dashboard" (enrichment throughput) and an "Admin panel" (queue/GPU/scrape) — the boundary between them is not defined in these sources.
12. **BH-first framing in the UI:** convention says "UX stays BH-first" while data may include SP/Campinas — how opportunistic non-BH data appears (shown? filtered? labeled?) is unstated.
