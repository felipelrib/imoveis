# Epic 1 Context: Deal intelligence, finished (v0.13 carry-over + FR-31)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Finish the deal-intelligence layer for the v0.14 decision engine: every Listing carries rent, condo fee and IPTU as separate monthly components with an honest total (itemized, `unknown` or `bundled`, never imputed); price/m² percentiles are computed per neighbourhood × listing-type cohort on one cross-platform-comparable basis; saved searches email new matches only once they are decidable; and the detail surface becomes the contract's right-side panel. The epic also absorbs every pending v0.13 item (corpus repair, the open deferred-work ledger bundled by surface, two UI follow-ups, open retro actions) so one plan of record exists. The cost story is Tier 1 foundation: the `aluguel-2027` profile's R$ 4.000 cap in Epic 2 depends on it.

## Stories

- Story 1.1: Total Monthly Cost on the persist path
- Story 1.2: Cost in the canonical projection and coverage
- Story 1.3: One cohort price basis for rent
- Story 1.4: Primary migration cannot bypass the backfill guard
- Story 1.5: Corpus repair applied and verified
- Story 1.6: Cohort price-per-m2 percentiles computed in the pipeline
- Story 1.7: Percentile badge on cards and percentile filter
- Story 1.8: Detail side panel with percentile sentence and cost breakdown
- Story 1.9: Saved-search new-match detection on the pipeline
- Story 1.10: Saved-search alert management UI
- Story 1.11: UI follow-ups — dashboard plurals and the shared bottom strip
- Story 1.12: Backfill liveness is visible for the whole run
- Story 1.13: Runner lifecycle ends honestly
- Story 1.14: Transport-quota inference holds across a throttle
- Story 1.15: Dependency and image scanning restored
- Story 1.16: The admin audit trail names who acted
- Story 1.17: Ledger and loop hygiene

## Requirements & Constraints

- **Total Monthly Cost** = rent + condo fee + IPTU/month per rent Listing, each component itemized. A component the platform does not publish is `unknown`, never zero; a combined figure that cannot be split is `bundled`. A total with any `unknown` (non-bundled) component is incomplete and has no value. Sale Listings carry monthly condo fee and IPTU as carrying-cost context under the same rules, with no total.
- Annual IPTU is converted to monthly with the source periodicity recorded; ambiguous periodicity is `unknown`, never divided. Base rent is never counted twice; the same home on two platforms must agree within published component differences.
- Known platform hazards the cost rules must correct: QuintoAndar and OLX fold fees into the headline price while ZapImóveis does not; ZapImóveis IPTU is often annual; OLX sums a missing fee as zero.
- Success measure: for the rent cohort, at least 90% of Listings have a total that is complete or explicitly incomplete/bundled, zero imputed components; cost completeness is reported per Platform in coverage telemetry.
- **Percentiles**: per neighbourhood × listing type, one per type for dual rent/sale Properties; null below a config-owned minimum cohort size or when area/neighbourhood is missing — never defaulted. Must not be computed over the known-fabricated scores the corpus repair removes.
- **Saved-search alerts** (email only in this epic): fire only for genuinely new Properties, at most once per search × property, held (not dropped) until the verdict exists and the percentile has been evaluated; per-search toggle and minimum-drop threshold, no global threshold; one daily batch window per search; the weekly digest excludes already-alerted Properties; a platform outage yields no spurious matches. The in-app Alertas panel and desktop push belong to Epic 5.
- Provenance and honesty: every derived cost fact records where it came from; nothing is imputed. Outages degrade to `unknown`, not failures.
- Local-first: committed AI routing stays all-local; cloud is backfill-only under the single pacer.
- Cost ships with a labelled fixture set across the three platforms; new API fields ship with contract tests; all UI strings land in both `en` and `pt-BR` catalogs with canonical English wire values.

## Technical Decisions

- **Cost is typed columns on `property_listings`**, written only on the scrape → normalize → dedupe → persist path: `rent_monthly` (the platform's unbundled rent), `condo_fee_monthly`, `iptu_monthly`, `iptu_periodicity_source` (`monthly`/`annual`/`unknown`), `fees_bundled`, `total_monthly_cost` (rent only; NULL when incomplete), `cost_complete`. Legacy `price` / `base_price` stay as published headline values and are never inputs to the total. Existing rows are populated by re-running the normalize mapping over stored `raw_json` on the `scrapers` queue, not by a second writer.
- Fact tables feeding the later Fit sweep carry `updated_at`; the cost columns must be covered by it.
- Cost rules live in a pure `src/core/` module (no adapter or lazy imports), built test-first.
- **Single cohort price basis**: rent cohorts use fee-exclusive `rent_monthly` for price/m², stamped `price_basis` on `metrics_scoring` (`headline` when `rent_monthly` is absent). Defined in one place; the percentile pipeline consumes it and never hardcodes `price`. Total Monthly Cost is a separate comparable, never the cohort basis. Sale cohorts are unchanged. Any `scoring.py` or brownfield scoring-SQL change ships behind a characterization lock landed first.
- **One API-owned projection**: API, compare and export are read-only; no cost value or per-Property fact is derived at read time (read-time aggregation is fine). Rent decisioning views expose exactly one `deciding_listing_id` with `deciding_rule` of `lowest-complete-total` or `lowest-headline-price`. Every cost sort/filter reads `total_monthly_cost` only.
- Percentiles and other enrichment/cohort fields are written only by the enrichment write authority.
- All outbound notifications go through Celery and the one notifier preference/channel registry; no UI-triggered or parallel notifier path. Saved searches belong to the single principal; matching is read-only against Property/Listing fields.
- Admin audit records the single principal id — no actor/agent column, no agent-only table; existing rows keep a null principal.
- Frontend talks only to the FastAPI surface.
- Backfill runner work stays within the bounded cloud-assist model: one pacer, one lease, no adapter imports in `backfill_runner.py`; the migration–backfill exclusion (Redis lock + heartbeat keys) is never bypassed and its keys are never deleted. `migrate-primary.sh` is the only path that migrates the primary DB.
- Migrations must pass the alembic check and are applied to the primary by the operator, batched per wave and recorded in the story's operator actions.

## UX & Interaction Patterns

- Meia-noite tokens, dark-only; serif only for price and neighbourhood name; tabular numerals; no pills.
- Honest absence: null renders as absent (a suppressed percentile shows nothing; an `unknown` cost component reads as not informed, never zero; a bundled figure is labelled as bundled). No progress bars or blocking spinners; errors are non-blocking bottom toasts, max two stacked, and must not cover the compare bar.
- Detail surface is a right-side panel over a partial scrim with the map rail visible, one level deep, `Esc` closes; map viewport, grid scroll and filter state survive refreshes and open/close. The centered modal is retired.
- Percentile microcopy: badge `entre os N% mais baratos`; panel sentence adds `do bairro` and names the cohort type on dual-type Properties. Never `P25`, "percentil" or `≤`; lower-is-better must be explicit. Badge uses the price-drop ink and tints, right-aligned on the price line.
- Percentile filter is the `Preço no bairro` select (25% / 50% / any, default any), filtered server-side, one chip under the 2-line ceiling, re-evaluated per listing type.
- Saved-search rows: card-surface rows with hairline separators, notify toggle plus inline minimum-drop threshold; alert emails state the threshold that fired them.

## Cross-Story Dependencies

- Gates: 1.2 ← 1.1; 1.3 ← 1.1; 1.6 ← 1.3 + 1.4 + 1.5; 1.7 ← 1.6; 1.8 ← 1.2 + 1.7; 1.9 ← 1.6; 1.10 ← 1.9. Stories 1.4, 1.11–1.17 have no gate.
- 1.5 waits on the operator applying migrations (batched with 1.1's); 1.6 must not start before 1.5 is done — not machine-enforced.
- 1.13 and 1.14 carry an advisory re-scope if the Strata spike verdict (Story 3.2) exists when they start.
- Do not run in parallel: any two stories editing `src/api/schemas.py` (in this epic 1.2, 1.7, 1.10, 1.13, 1.16 — story-number order); 1.3 with 1.6 (`scoring.py`); 1.12, 1.13, 1.14 with each other (backfill runner and Gemini client); 1.1 with Epic 2/5 stories that change the scraper normalize/persist path (2.3, 5.4); 1.4 with anything else touching `scripts/`; 1.8 with other detail-panel stories (3.9, 5.9); 1.7 with other filter-bar stories (4.5, 6.3, 6.4).
- Downstream consumers: Epic 2 needs 1.1 (cost columns), 1.2 (projection) and 1.3 (price basis); Epic 5 needs 1.16 (audited principal) and 1.8 (side panel); Story 3.9 needs 1.8.
