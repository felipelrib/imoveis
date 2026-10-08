# Epic 1 Context: Deal intelligence, finished (v0.13 carry-over + FR-31)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Finish the deal-intelligence layer of the v0.14 decision engine: every Listing carries rent, condo fee and IPTU as separate monthly components with an honest total (itemized, `unknown` or `bundled`, never imputed); price/m² percentiles are computed per neighbourhood × listing-type cohort on one cross-platform-comparable basis; saved searches email new matches once they are decidable; and the detail surface becomes the right-side panel. The epic also absorbs every pending v0.13 item (corpus repair, the deferred-work ledger bundled by surface, UI follow-ups, open retro actions) and one operator-observed pipeline defect: short periodic tasks starved for hours behind long scrapes. Cost is Tier 1 foundation — Epic 2's rent-cap profile depends on it.

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
- Story 1.18: Periodic tasks are not blocked by scrapes

## Requirements & Constraints

- **Total Monthly Cost** = rent + condo fee + IPTU/month per rent Listing, each itemized. An unpublished component is `unknown`, never zero; an unsplittable combined figure is `bundled`. A total with any `unknown` component is incomplete and has no value. Sale Listings carry condo fee and IPTU as context under the same rules, with no total.
- Annual IPTU is converted to monthly with source periodicity recorded; ambiguous periodicity is `unknown`, never divided. Base rent is never counted twice. Platform hazards to correct: QuintoAndar and OLX fold fees into the headline price, ZapImóveis does not and often publishes annual IPTU, OLX sums a missing fee as zero.
- Success measure: at least 90% of rent Listings have a total that is complete or explicitly incomplete/bundled, zero imputed components; cost completeness is reported per Platform in coverage telemetry.
- **Percentiles**: per neighbourhood × listing type (one per type on dual rent/sale Properties); null below a config-owned minimum cohort size or when area/neighbourhood is missing; never computed over the fabricated scores the corpus repair removes.
- **Saved-search alerts** (email only here): only genuinely new Properties, at most once per search × property, held (not dropped) until verdict and percentile exist; per-search toggle and minimum-drop threshold; one daily batch window per search; the weekly digest excludes already-alerted Properties; a platform outage yields no spurious matches. In-app Alertas panel and desktop push belong to Epic 5.
- **Periodic-task timeliness**: every periodic task (alert matcher and sender, watchlist evaluation, digests, metrics snapshot, queue monitor, availability recheck, refresh tasks) runs within its own interval on capacity a scrape cannot occupy. Idempotent housekeeping must not pile up unbounded (stale runs discarded or coalesced); runs that must not be lost (hourly alert sender, digests) are never discarded. A scrape for a platform and scope already queued or in flight is not queued again. Deploy must drain, not strand, messages already queued under the old routing; operator steps go in the feature doc.
- Provenance on every derived cost fact; outages degrade to `unknown`, not failures. Committed AI routing stays all-local; cloud is backfill-only under the single pacer.
- Cost ships with a labelled three-platform fixture set; new API fields ship with contract tests; UI strings land in both `en` and `pt-BR` with canonical English wire values.

## Technical Decisions

- **Cost is typed columns on `property_listings`**, written only on the scrape → normalize → dedupe → persist path: `rent_monthly`, `condo_fee_monthly`, `iptu_monthly`, `iptu_periodicity_source`, `fees_bundled`, `total_monthly_cost` (rent only; NULL when incomplete), `cost_complete`. Legacy `price` / `base_price` stay as headline values and never feed the total. Existing rows are populated by re-running normalize over stored `raw_json` on the scrape path, not by a second writer. Cost columns are covered by the table's `updated_at`.
- Cost rules live in a pure `src/core/` module (no adapter or lazy imports), built test-first.
- **Single cohort price basis**: rent cohorts use fee-exclusive `rent_monthly`, stamped `price_basis` on `metrics_scoring` (`headline` when absent), defined in one place and consumed by the percentile pipeline. Total Monthly Cost is never the cohort basis. Sale cohorts are unchanged. Any `scoring.py` or brownfield scoring-SQL change lands behind a characterization lock first.
- **One API-owned projection**: API, compare and export are read-only; no cost or per-Property fact is derived at read time. Rent decisioning views expose one `deciding_listing_id` with `deciding_rule` (`lowest-complete-total` or `lowest-headline-price`); every cost sort/filter reads `total_monthly_cost` only.
- Percentiles and other enrichment/cohort fields are written only by the enrichment write authority.
- **Celery layout**: every beat task is listed in `task_routes`, and a test pins that no periodic task shares a queue with `scrape_listings`. GPU work stays only on `ai` behind the GPU semaphore — the new periodic queue is never a second GPU path. The queue monitor and pipeline metrics snapshot must report every queue. AGENTS.md, `docs/architecture.md` and `docs/setup.md` state the layout.
- All outbound notifications go through Celery and the one notifier preference/channel registry. Saved searches belong to the single principal; matching is read-only.
- Admin audit records the single principal id — no actor/agent column; existing rows keep a null principal.
- Backfill runner work stays within one pacer and one lease with no adapter imports in `backfill_runner.py`; the migration–backfill exclusion (Redis lock + heartbeat keys) is never bypassed or deleted. `migrate-primary.sh` is the only path that migrates the primary DB; migrations pass the alembic check and are applied by the operator, batched per wave.

## UX & Interaction Patterns

- Meia-noite tokens, dark-only; serif only for price and neighbourhood name; tabular numerals; no pills.
- Honest absence: a suppressed percentile shows nothing, an `unknown` component reads as not informed, a bundled figure is labelled. No progress bars or blocking spinners; errors are non-blocking bottom toasts (max two) that never cover the compare bar.
- Detail is a right-side panel over a partial scrim with the map rail visible, one level deep, `Esc` closes; map viewport, grid scroll and filters survive open/close. The centered modal is retired.
- Percentile microcopy: badge `entre os N% mais baratos`; the panel sentence adds `do bairro` and names the cohort type on dual-type Properties. Never `P25`, "percentil" or `≤`. Badge uses the price-drop ink, right-aligned on the price line.
- Percentile filter is the `Preço no bairro` select (25% / 50% / any), server-side, one chip, re-evaluated per listing type.
- Saved-search rows: notify toggle plus inline minimum-drop threshold; alert emails state the threshold that fired them.

## Cross-Story Dependencies

- Gates: 1.2 ← 1.1; 1.3 ← 1.1; 1.6 ← 1.3 + 1.4 + 1.5; 1.7 ← 1.6; 1.8 ← 1.2 + 1.7; 1.9 ← 1.6; 1.10 ← 1.9. Stories 1.4 and 1.11–1.18 have no gate.
- 1.5 waits on the operator applying migrations; 1.6 must not start before 1.5 is done (not machine-enforced).
- 1.13 and 1.14 carry an advisory re-scope if the Strata spike verdict (Story 3.2) exists when they start.
- Do not run in parallel: any two stories editing `src/api/schemas.py` (1.2, 1.7, 1.10, 1.13, 1.16 — story-number order); 1.3 with 1.6 (`scoring.py`); 1.12, 1.13, 1.14 with each other (backfill runner, Gemini client); 1.1 with 2.3 and 5.4 (normalize/persist path); 1.4 with anything else touching `scripts/`, including 1.18; 1.18 with any story editing `task_routes`, the beat schedule or the worker services in `docker-compose.yml` (2.3, 2.5, 4.2, 5.6 each add a routed beat task — one added while 1.18 is in flight goes to the queue 1.18 introduces, not `scrapers`); 1.8 with 3.9 and 5.9 (detail panel); 1.7 with 4.5, 6.3, 6.4 (filter bar).
- Downstream: Epic 2 needs 1.1, 1.2 and 1.3; Epic 5 needs 1.16 and 1.8; Story 3.9 needs 1.8.
