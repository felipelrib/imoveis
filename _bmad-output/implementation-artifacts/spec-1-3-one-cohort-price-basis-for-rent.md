---
title: 'Story 1.3 — One cohort price basis for rent'
type: 'feature'
created: '2026-10-08'
status: 'awaiting-operator'
baseline_revision: 'a50865464d3d2202ddf671c792ccc7bc8c2e54be'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      67 active QuintoAndar rent Listings on the primary carry a rent_monthly above their headline
      price, which the cost rules of Story 1.1 should not produce (the headline is rent plus fees).
    evidence: |-
      Read-only probe of the primary on 2026-10-08:
      count(*) FILTER (WHERE rent_monthly > price) over active rent Listings = 67 for quintoandar,
      0 for olx and zapimoveis. Scoring now reads rent_monthly for these rows, so their rent
      price/m2 rises instead of falling. Not checked: the raw payloads of those 67 rows
      (rentPrice against totalCost), which would say whether the platform publishes them that way
      or the legacy-row reconstruction in core/listing_cost.py picked the wrong field.
    location: >-
      src/core/listing_cost.py
    severity: low
  - summary: >-
      The cached cohort statistics and the bulk scoring stage disagree on which Listing-less
      Properties fall back to properties.price.
    evidence: |-
      Pre-existing, unchanged by this story. compute_neighborhood_stats uses the fallback when the
      Property has no active priced rent/sale Listing (NOT EXISTS in has_listing);
      get_neighborhood_stats_cached uses it only when the Property has no active Listing at all.
      A Property whose only active Listing has price 0 is scored from properties.price by the bulk
      path and left out of the cohort by the cached path, so the single-property z-score is
      computed against a slightly different cohort.
    location: >-
      src/adapters/metrics/scoring.py:617
    severity: low
operator_actions:
  - "Wait for the orchestrator to merge this story into main, then from the primary checkout in Git Bash run: bash scripts/agent/migrate-primary.sh (expect alembic_version d5e6f7a8b9c0; it refuses while a cloud backfill runner is alive - wait, never delete the Redis keys). Do this BEFORE rebuilding any container: the new scoring code writes metrics_scoring.price_basis."
  - "Rebuild and restart the primary stack so the API and workers run the merged scoring code: ./scripts/restart.sh --build"
  - "Straight after the rebuild, recalculate the stored scores (one request, one transaction, run time on the primary unmeasured; it also inserts a metrics_scoring row for every active priced Property that has none, about 170,000 rows): curl --max-time 3600 -X POST http://localhost:8000/admin/scoring/recalculate -H 'X-API-Key: <the API key>'"
  - "Run the step 4 query in docs/features/v0.14-s1.3-one-cohort-price-basis-for-rent.md against the primary (read-only) and confirm not_scored is 0 and headline is a small remainder."
  - "Run the step 5 query in the same doc (read-only) and record the stored Belo Horizonte band counts under the before/after band table in that doc."
---

<intent-contract>

## Intent

**Problem:** `adapters/metrics/scoring.py` computes rent price/m² from the Listing headline `price`, which includes condo fee and IPTU on QuintoAndar and OLX and excludes them on ZapImóveis. A rent cohort's mean, z-score, stat score and percentile rank therefore mix two different prices (AD-3).

**Approach:** Define the cohort price basis once, in a pure `src/core/` module (constants, one SQL relation, one Python mirror), and make every scoring path read it: a rent Listing contributes its fee-exclusive `rent_monthly` when it has one and its headline `price` otherwise. Stamp the basis that produced each row's rent price/m² in a new `metrics_scoring.price_basis` column. Lock today's scoring output with a characterization test before touching `scoring.py`.

## Boundaries & Constraints

**Always:**
- The characterization test lands and passes against the unchanged `scoring.py` in its own commit, before any production change, and stays green without edits afterwards (its fixtures carry no `rent_monthly`, so they keep the headline basis).
- Per active rent Listing with `price > 0`: cohort price = `rent_monthly` when it is not NULL and > 0 (basis `rent_monthly`), else `price` (basis `headline`). Per Property × listing type: the lowest cohort price among its Listings (as today's `MIN(price)`); the stamp is the basis of the Listing that supplied it, `rent_monthly` winning an exact tie.
- `metrics_scoring.price_basis` ∈ {`rent_monthly`, `headline`}, NOT NULL, default `headline` (AD-3: "`headline` until then"). It describes the row's rent price/m². A row with no rent price/m² (sale-only) and a row scored from the legacy `properties.price` fallback are `headline`.
- Sale cohorts: every sale output value is identical to today's for the same rows.
- A cohort may hold both bases; all members stay in the same statistics, each with its own stamp. Nothing is excluded or imputed.
- The bulk path (`compute_neighborhood_stats`), the cached cohort stats (`get_neighborhood_stats_cached`) and the single-property path (`score_single_property`) all read the one definition; a test proves the SQL relation and the Python mirror agree on the same rows.
- The definition module imports nothing from `adapters`, `api` or `infra` (AD-1) and is built test-first. SQL is static text with bound parameters, assembled by concatenation (BIN-135).
- The migration passes the alembic check, is reversible, and is applied to the primary only by the operator.
- The feature doc records the before/after distribution for the Belo Horizonte rent cohort, measured read-only.

**Never:**
- Use `total_monthly_cost` as the cohort basis, or read `condo_fee*` / `iptu*` in scoring.
- Change `price`, `rent_monthly` or any `property_listings` / `properties` value; scoring only reads them.
- Touch `src/api/` (no wire exposure of `price_basis` in this story; `schemas.py` is serial-gated), the frontend, scrapers, `core/dedupe.py`, `core/listing_cost.py`, `scripts/`, `sprint-status.yaml` or the primary stack's lifecycle.
- Compute percentiles, add a minimum cohort size or change the cohort key (Story 1.6); change the sigmoid, the bands or the blend weights.
- Write to the primary database. The distribution measurement is a read-only session.

## I/O & Edge-Case Matrix

All rows: active Property, `area_m2` 100, one cohort unless stated.

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Rent Listing with unbundled rent | `price` 3800, `rent_monthly` 3000 | `price_per_m2_rent` 30, `price_basis` `rent_monthly` | No error expected |
| Rent Listing without it | `price` 3500, `rent_monthly` NULL | 35, `headline` | No error expected |
| `rent_monthly` zero or negative | `price` 3500, `rent_monthly` 0 | 35, `headline` | Treated as absent |
| Two rent Listings, both with rent | `rent_monthly` 3000 and 3200 | 30, `rent_monthly` | No error expected |
| Mixed Listings, headline lower | A `rent_monthly` 3000; B NULL, `price` 2500 | 25, `headline` | No error expected |
| Mixed Listings, rent lower or tied | A `rent_monthly` 3000; B NULL, `price` 3000 or 3500 | 30, `rent_monthly` | No error expected |
| Inactive Listing holds the rent | inactive `rent_monthly` 1000; active NULL, `price` 3500 | 35, `headline` | No error expected |
| Sale-only Property | sale `price` 500000 | `price_per_m2_sale` 5000 and every sale column as before; `price_basis` `headline` | No error expected |
| Dual rent + sale | rent `price` 3800 / `rent_monthly` 3000; sale 500000 | rent 30, sale 5000, `price_basis` `rent_monthly` | No error expected |
| Legacy Property, no Listings | `properties.price` 4000 | 40 as before, `headline` | No error expected |
| Mixed-basis cohort | P1 `rent_monthly` 3000, P2 `rent_monthly` 4000, P3 headline 5000 | mean 40, median 40; z from 30 / 40 / 50; stamps `rent_monthly`, `rent_monthly`, `headline` | No error expected |
| Fee-inclusive vs fee-exclusive peers | QA `price` 3800 / rent 3000; Zap `price` 3000 / rent 3000 | both 30, equal z and stat score (before: 38 vs 30) | No error expected |
| Single-property path | any row above through `score_single_property` | same `price_per_m2_rent` and `price_basis` as the bulk path | No error expected |
| No usable price | no Listing and `properties.price` 0 | row untouched, stamp untouched | Existing warning log |
| Existing rows after migration | rows written before this story | `price_basis` `headline` until the next recalculation | No error expected |

</intent-contract>

## Code Map

- `src/adapters/metrics/scoring.py` -- the only scoring writer. Three places hardcode `price`: `compute_neighborhood_stats` CTE `listing_min` (`:235-245`, `MIN(pl.price)` per property × type, feeds `typed` `:249-292`, pivoted `:315-338`, row loop `:390-492`, insert `:450-463`, update `:464-474`); `get_neighborhood_stats_cached` CTE `listing_min` (`:596-606`, filtered by `:lt`; Redis key `n_stats:{n_key}:{lt}`, 60 s TTL); `_min_listing_prices` (`:660-678`) used by `score_single_property` (`:681-816`, insert `:770-783`, update via `_update_metrics_score` `:159-169`). `_apply_type_fields` (`:172-203`) is the shared per-type setter. Legacy fallbacks on `properties.price` (`:266-291`, `:617-638`, `:706-712`) stay headline.
- `src/adapters/db/models.py:154-188` `MetricsScoring` (no `price_basis` yet); `:241` `PropertyListing.rent_monthly` (nullable Float; Story 1.1 guarantees NULL for missing / zero / negative).
- `alembic/versions/c4d5e6f7a8b9_listing_total_monthly_cost.py` -- current head and style reference (NOT NULL + `server_default` + named CHECK; version files never import from `src/`).
- `src/core/listing_cost.py`, `src/core/listing_type.py` -- convention for a pure `core` module; `src/core/property_projection.py:294` `LISTINGS_JSON_AGG` is the precedent for a SQL constant living in `core`.
- Callers (signatures must not change): `src/api/admin.py:187` `POST /admin/scoring/recalculate` → `compute_neighborhood_stats` + `recalculate_all_combined_scores` (the only bulk trigger; no beat task); `src/adapters/queue/tasks.py:707` → `score_single_property` after enrichment; `tasks.py:686` inserts a `MetricsScoring` without stat fields (takes the column default).
- Existing locks that must stay green unchanged: `src/tests/integration/test_scoring_spatial_cohorts.py` (rent/sale cohorts, dual means; Listings without `rent_monthly`), `test_scoring_neighborhood_stats_n_plus_one.py` (SELECT count ≤ 4 and constant), `test_scoring_sql_assembly.py` (cached stats, bulk recalc), `src/tests/unit/test_scoring_dual_scores.py`, `test_scoring_rent_sale_ppm.py`, `test_scoring_cohort_key.py`. Fixture patterns to reuse: `_make_property` / `_add_listing` in `test_scoring_spatial_cohorts.py`, `real_redis` in `test_scoring_sql_assembly.py`, `wipe_safe_db_session`.
- Migration test pattern: `src/tests/integration/test_listings_e2e.py` `TestListingCostMigration` (explicit downgrade target, `compare_metadata` filtered to one table).
- Gate: `scripts/agent/validate.py` backend tier (`alembic upgrade head` on the ephemeral stack `:463`, integration `:468`, `alembic check` informational `:475`). `alembic/` and `src/` changes select the backend tier; nothing under `scripts/` changes, so the harness suite is not triggered.
- Primary, read-only probe 2026-10-08: `alembic_version` `c4d5e6f7a8b9`; active rent Listings with `rent_monthly`: OLX 7290 / 7293 (6481 below `price`), QuintoAndar 77595 / 77892 (76204 below, 67 above), ZapImóveis 43197 / 43197 (all equal to `price`); `metrics_scoring` holds 28,210 rows. Reached with `docker exec imoveis-postgres-1 … psql` under `default_transaction_read_only=on`, using the container's own environment (no operator file read).
- Docs: `docs/features/_template.md`; naming like `docs/features/v0.14-s1.1-total-monthly-cost-on-the-persist-path.md` (its operator-steps section is the model); `docs/data-models-api.md:12,33` (table row, revision count).

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/integration/test_scoring_characterization_lock.py` -- NEW, first commit, no production change: one seeded cohort set (rent-only, sale-only, dual, two rent Listings on one Property, a legacy Property without Listings, a Listing-less sale-flagged Property) with every `metrics_scoring` stat column asserted to hand-computed values for `compute_neighborhood_stats`, plus `score_single_property` and `get_neighborhood_stats_cached` on the same rows -- AC 1 characterization lock
- [x] `src/tests/unit/test_price_basis.py` -- NEW, written before the module: the per-Listing and per-Property rows of the matrix through the Python mirror, the mixed-basis cohort through `_compute_type_scores`, vocabulary, and an AST check that the module imports no `adapters` / `api` / `infra` -- TDD for `core`
- [x] `src/core/price_basis.py` -- NEW: basis constants and vocabulary, the SQL relation yielding `property_id, listing_type, price, price_basis` per active priced Listing group, and the pure Python mirror -- the one definition later stories consume
- [x] `alembic/versions/d5e6f7a8b9c0_metrics_scoring_price_basis.py` -- NEW (revises `c4d5e6f7a8b9`): `price_basis` String NOT NULL default `'headline'` with CHECK `ck_metrics_scoring_price_basis`; reversible -- schema
- [x] `src/adapters/db/models.py` -- mirror the column and CHECK on `MetricsScoring` -- no new alembic drift
- [x] `src/adapters/metrics/scoring.py` -- replace the three hardcoded `price` reads with the shared definition; carry the rent basis through the bulk query and both write paths; stamp `price_basis` on insert and update -- the behaviour change
- [x] `src/tests/integration/test_scoring_price_basis.py` -- NEW: the Postgres-only rows of the matrix (bulk, cached stats, single-property parity, mixed-basis cohort, fee-inclusive vs fee-exclusive peers, sale unchanged, inactive Listing), SQL-vs-Python agreement, migration down/up to explicit revisions, default and CHECK, model parity for `metrics_scoring` -- real-row proof
- [x] `docs/features/v0.14-s1.3-one-cohort-price-basis-for-rent.md`, `docs/data-models-api.md` -- feature doc (all template sections, the rule, the read-only measurement query and its recorded before/after numbers for the BH rent cohort, operator steps) and the table row / revision count

**Acceptance Criteria:**
- Given the branch history, when the commit that first modifies `scoring.py` is inspected, then the characterization test file already exists in an earlier commit and is not modified by any later commit.
- Given a database at `c4d5e6f7a8b9`, when `alembic upgrade head` then `alembic downgrade c4d5e6f7a8b9` run, then both succeed, existing rows read `headline`, and `compare_metadata` reports no difference on `metrics_scoring`.
- Given a rent cohort with Listings from a fee-inclusive and a fee-exclusive platform that publish the same unbundled rent and area, when the metrics stage runs, then both Properties get the same rent price/m², z-score and stat score, and both rows are stamped `rent_monthly`.
- Given `src/`, when searched for the cohort price rule, then `scoring.py` contains no `MIN(pl.price)` and no per-Listing price selection of its own; both come from `core/price_basis.py`.
- Given the feature doc, when read, then it states, for active BH Properties with an active rent Listing, the share per basis and per platform and the price/m² quartiles and stat-band counts under the headline basis and under the new basis, with the date and the query used.
- Given the story is code-complete, when the session ends, then the spec is `awaiting-operator` with `operator_actions` covering the primary migration, the rebuild and the recalculation that makes stored scores use the new basis.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 30 findings — high 0, medium 1, low 20, false 9, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: the rent price/m² changes meaning on the wire with nothing saying so (a card shows a fee-inclusive price beside a fee-exclusive R$/m²) — true of `price_per_m2` / `price_per_m2_rent` after recalculation; a note in the feature doc now names the mismatch and that Story 2.8 states `price_basis` only in the cohort summary.
  - `[false]` `[reject]` Blind: `headline` conflates four states — AD-3 defines the stamp as `headline` until a row is rescored, and a row not yet rescored was scored on the headline, so the stamp is true of it; a sale-only row has no rent figure to describe. `updated_at` separates rescored rows.
  - `[low]` `[patch]` Blind: operator step 4 cannot verify step 3 (unfiltered query, Belo Horizonte expectation) — step 4 is now a whole-database completeness query (`not_scored`, `headline`, `rent_monthly` over active rent Properties) with its expected result.
  - `[medium]` `[patch]` Blind: step 3 is prescribed with an unmeasured blast radius — the endpoint's behaviour is pre-existing, but the doc gave no handling: it now says the run is one request and one transaction (a failure writes nothing and can be repeated), gives `--max-time 3600`, and the row-count note stays. Run time on the primary remains unmeasured (residual risk).
  - `[low]` `[patch]` Blind: a downgrade is lossy and the doc does not say so — note added: the stamps are dropped and every row reads `headline` until the recalculation is run again.
  - `[low]` `[patch]` Blind: no test pins the stamp resetting when a Property loses its rent price — added `test_losing_the_rent_listing_resets_the_stamp_on_both_paths` (dual Property, rent Listing deactivated, bulk and single-property paths). The no-area sub-case writes no row, as before, and is covered by the lock.
  - `[low]` `[patch]` Blind: acceptance criterion 4 is checked by inspection only — added `test_scoring_selects_no_listing_price_of_its_own` (static check that `scoring.py` holds no `pl.price` and no `MIN(pl.`).
  - `[low]` `[reject]` Blind: the vocabulary is written out in five places — a drift between the constants, the SQL literals and the CHECK fails loudly today: the integration matrix writes both values through the CHECK and compares the SQL relation with the mirror. Building the CHECK from the constants would make a migration import `src/`, which version files never do.
  - `[low]` `[reject]` Blind: model/migration parity does not compare the CHECK — true of `compare_metadata`; the database is built by alembic, and the constraint in the database is exercised directly by `test_check_rejects_a_value_outside_the_vocabulary`. A `pg_constraint` text comparison is more than a direct correction.
  - `[low]` `[reject]` Blind: the bulk path reads the new column by position (`row[11]`) — the surrounding loop reads all eleven existing columns by position; a misplaced column would hand `row_price_basis` a number and raise. Not worth diverging from the local idiom.
  - `[false]` `[reject]` Blind: neither the doc nor the docstring says the headline gates a Listing — both do: the rule table's first row ("Active, `price > 0`") and the module docstring's first bullet; `price` is NOT NULL.
  - `[low]` `[defer]` Blind: `rent_monthly` is taken as fee-exclusive without evidence for rows equal to `price`, and 67 QuintoAndar rows sit above it — equality is expected (ZapImóveis by definition, fee-free Listings elsewhere); the 67 rows above the headline are a real anomaly in Story 1.1's column, deferred.
  - `[low]` `[patch]` Blind: the explanation for the `average` band shrinking is asserted, not measured — reworded as the likely cause, stated as not measured, with the population difference between the quartile and band tables.
  - `[low]` `[patch]` Blind: the interim window is understated — the note now says to run step 3 straight after step 2 and mentions the 60 s cached statistics.
  - `[false]` `[reject]` Blind: the spec is not in the state its last criterion requires — mid-review state; finalization writes the status, logs and `operator_actions`.
  - `[low]` `[reject]` Blind: `TestPriceBasisMigration` has no `integration` marker and alters shared schema mid-suite — it follows `TestListingCostMigration` (unmarked, same explicit-downgrade shape, adopted in Story 1.1's review); the gate selects the directory and runs it serially.
  - `[low]` `[reject]` Edge: a NaN `rent_monthly` passes `> 0` in Postgres and not in the mirror — the only writer (`core.listing_cost`) produces rounded finite figures or NULL; a guard for a state never shown to exist.
  - `[low]` `[reject]` Edge: a NaN or infinite `price` — same, and the `pl.price > 0` gate is unchanged from before this story.
  - `[low]` `[defer]` Edge: the bulk and cached paths disagree on which Listing-less Properties use the `properties.price` fallback — verified in the code and pre-existing (both `NOT EXISTS` clauses predate this diff); deferred.
  - `[low]` `[reject]` Edge: cohort statistics cached by the old code are read by the new code — true for at most 60 s once per deploy; versioning the key adds surface for a one-minute window. Mentioned in the doc.
  - `[low]` `[reject]` Edge: the single-property path can score against statistics up to 60 s stale after a Listing's `rent_monthly` changes — the same staleness already applies to any price change; it is the TTL's contract.
  - `[false]` `[reject]` Edge (claim): the migration test upgrades to `head`, not to an explicit revision — it must: the shared test database has to be back at head for the tests that follow. The downgrade target is explicit.
  - `[false]` `[reject]` Intent: spec frontmatter has no `operator_actions` — mid-review snapshot; written at finalization.
  - `[false]` `[reject]` Intent: nothing in the diff moves a stored score — by design: the primary is operator-owned, and the migration, rebuild and recalculation are the `operator_actions`.
  - `[low]` `[patch]` Intent: the "after" distribution is a projection from a standalone query, not observed stored scores — the doc now says so and adds step 5, which records the stored Belo Horizonte band counts after the recalculation (also an operator action).
  - `[low]` `[patch]` Intent: "defined in one place" is not asserted by a test — same root cause as the Blind criterion-4 row; fixed by the static check.
  - `[false]` `[reject]` Intent: the unit test covers the score formula, not the cohort aggregation — the aggregation is Postgres window SQL and cannot run in the unit tier; `TestMixedBasisCohort` in the integration file runs it on a mixed cohort.
  - `[false]` `[reject]` Intent: headline-basis members still share a cohort with `rent_monthly` members — required by the story ("a Listing without `rent_monthly` keeps the `headline` basis and is stamped as such"); 42 of 15,269 Properties.
  - `[low]` `[patch]` Intent: changed values flow through existing API fields and Story 2.8 expects `price_basis` stated — same root cause as the first Blind row; the doc note covers it. The wire shape is unchanged, so the contract suite has nothing new to assert.
  - `[false]` `[reject]` Intent: NOT NULL + CHECK, the migration tests and the data-model doc go beyond the story text — AD-3 binds `metrics_scoring.price_basis` and the repo convention (Story 1.1) is a constrained column with a round-trip test.

## Design Notes

- **Per-Listing basis, then the lowest.** The story's criterion is worded per Listing ("a Listing without `rent_monthly` keeps the `headline` basis"). Each Listing contributes its own best-known rent figure and the Property keeps today's "cheapest offer" rule. Preferring `rent_monthly` outright would let a dearer itemized Listing hide a cheaper one that lacks the column.
- **One module, two expressions.** The bulk and cached paths are SQL, the single-property path is Python. Both expressions live side by side in `core/price_basis.py` and an integration test pins them to each other, so Story 1.6 imports the relation instead of writing `pl.price`.
- **One stamp per row.** `metrics_scoring` is one row per Property and AD-3 names one `price_basis` column. Only the rent figure can vary by basis, so the stamp describes it; sale is always the published sale price.
- **Stored scores move only on recalculation.** No beat task runs the bulk stage; `POST /admin/scoring/recalculate` does. Until the operator runs it, rows keep their old values and read `headline`, which is true of them.
- **Deploy order.** New code writes `price_basis`, so the primary is migrated before the rebuild. The old code tolerates the new column (it has a default).

## Verification

**Commands:**
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe scripts/agent/validate.py` -- expected: exit 0, `VALIDATION PASSED (tier=backend)`
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe -m pytest src/tests/unit/test_price_basis.py src/tests/unit/test_scoring_dual_scores.py src/tests/unit/test_scoring_rent_sale_ppm.py -q -o addopts=` -- expected: all pass (development loop only, not validation)

**Manual checks (if no CLI):**
- `git log --oneline -- src/tests/integration/test_scoring_characterization_lock.py src/adapters/metrics/scoring.py` shows the lock commit before the first `scoring.py` commit.

## Auto Run Result

Status: awaiting-operator

**Summary.** Rent price/m² cohorts are now scored on the fee-exclusive `rent_monthly` wherever a Listing has it, and on the headline `price` otherwise. The rule lives once in `src/core/price_basis.py` (SQL relation plus Python mirror, pinned to each other by a test) and all three scoring paths read it. Each scored row records the basis of its rent price/m² in the new `metrics_scoring.price_basis` column. Sale cohorts are unchanged. A characterization lock for the scoring stage landed in its own commit before `scoring.py` was touched and was not edited afterwards. No API, frontend or scraper change.

**Files changed.**
- `src/tests/integration/test_scoring_characterization_lock.py` (new, commit `e7ebc0c0`) — every stat column for the bulk, cached and single-property paths on one seeded cohort set
- `src/core/price_basis.py` (new) — vocabulary, `COHORT_PRICE_SQL`, `COHORT_PRICE_FOR_TYPE_SQL`, `property_cohort_prices`, `row_price_basis`
- `src/adapters/metrics/scoring.py` — the three hardcoded `price` reads replaced by the shared definition; `price_basis` stamped on insert and update
- `alembic/versions/d5e6f7a8b9c0_metrics_scoring_price_basis.py` (new), `src/adapters/db/models.py` — `price_basis` NOT NULL, default `headline`, CHECK
- `src/tests/unit/test_price_basis.py` (new), `src/tests/integration/test_scoring_price_basis.py` (new) — rule, matrix through both paths, mixed-basis cohort, SQL against mirror, migration round trip, model parity
- `docs/features/v0.14-s1.3-one-cohort-price-basis-for-rent.md` (new), `docs/data-models-api.md` — feature doc with the measured before/after distribution and operator steps; table row and revision count

**Before and after (primary, read-only, 2026-10-08, Belo Horizonte: 15,269 Properties, 16,380 active rent Listings).** Rent price/m² median 40.24 → 36.20 (Q1 28.33 → 26.25, Q3 60.53 → 53.00). 99.7% of Properties take the `rent_monthly` basis; 42 stay `headline`. 57.0% of Properties get a different rent price/m² and 22.0% change stat band. The "after" figures are computed from the Listings; stored scores change only when the operator recalculates.

**Review.** 30 findings from four layers (the verification-gap layer reported none). No intent gap, no spec defect.
- Patched: 10 rows in 8 entries — medium 1 (operator recalculation step lacked failure and timeout handling), low 7 (wire-meaning note, completeness check for the recalculation, downgrade note, hedged band explanation, interim-window note, stamp-reset test, static one-definition test, stored-distribution step).
- Deferred: 2, both low and outside this story's cause — 67 QuintoAndar Listings with `rent_monthly` above `price`; the pre-existing fallback mismatch between the bulk and cached paths.
- Rejected: 9 `false` and 9 `low`; each row and its reason is in the triage log above.

**Follow-up review: not recommended (false).** Patched counts: high 0, medium 1, low 7.

**Verification.**
- `python scripts/agent/validate.py` on the patched tree (commit `ce1e53c6` plus this spec uncommitted): `VALIDATION PASSED (tier=backend)` — lint, unit, 165 integration and 62 contract tests pass. No stamp was written because the spec was uncommitted; the orchestrator's `[verify]` re-runs the backend tier. The pre-patch tree (`cf5fa0e1`) carried a backend stamp.
- `alembic check` (informational, reports FAIL as on main): only the known PostGIS / index drift, no `metrics_scoring` entry.
- Matrix audit: every row has a passing test in `test_scoring_price_basis.py` (bulk and single-property paths) and `test_price_basis.py`.
- History: `e7ebc0c0` (lock) precedes `cf5fa0e1` (first `scoring.py` change); no later commit touches the lock file.

**Residual risks.**
- The recalculation's run time on the primary is unmeasured, and it inserts a `metrics_scoring` row (with `ai_score` 0) for every active priced Property that has none — about 170,000 rows. This is the endpoint's existing behaviour, now on the operator's path.
- Between the rebuild and the recalculation, newly enriched rows are scored on the new basis beside rows still on the headline.
- The UI shows a fee-inclusive price beside a fee-exclusive R$/m² and does not say which basis produced it.
- The primary has no `neighborhood_id` set, so cohorts are keyed by neighbourhood label alone and can span cities (Story 1.6's concern).
