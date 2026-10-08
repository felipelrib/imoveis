---
title: 'Story 1.6 — Cohort price-per-m2 percentiles computed in the pipeline'
type: 'feature'
created: '2026-10-08'
status: 'awaiting-operator'
baseline_revision: '27c11048888ac8a5ad5d9526f3332916cfae18db'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Nothing schedules the bulk scoring stage, so the stored percentile and cohort size of a
      Property's cohort peers lag until someone calls POST /admin/scoring/recalculate.
    evidence: |-
      score_single_property (run after each enrichment) writes the scored Property's own
      percentile and size only. When it takes a cohort from 9 to 10 members the newcomer gets a
      value with size 10 while the other nine keep NULL with size 9; a Listing deactivated by a
      scraper rescores nobody. compute_neighborhood_stats has one caller, src/api/admin.py:187,
      and no beat task (grep of src/ for its name). The same lag already applied to
      neighborhood_mean / z_score / stat_score before this story. Story 1.7 filters and shows
      the stored percentile, so the lag becomes visible there. The run time that made a schedule
      unreasonable (62 minutes) is fixed in this story: the stage's statement takes 7.8 s on the
      primary; the whole request is not timed yet. Not measured: how fast cohorts drift on the
      primary between runs.
    location: >-
      src/adapters/metrics/scoring.py:418
    severity: medium
  - summary: >-
      The stat cohort (neighbourhood mean, median, z-score, stat score, legacy percentile_rank)
      is still keyed by the exact neighbourhood label, so it merges cities and splits spellings,
      while the new percentile uses the city-aware folded key.
    evidence: |-
      _COHORT_KEY_SQL is COALESCE(n.name, props_json->>'neighborhood', 'Unknown'). Read-only on
      the primary, 2026-10-08: no Property has a neighborhood_id; 97 labels occur in more than
      one of the 3 cities and hold 16,477 active Properties; 537 city x label spellings fold
      into 268 neighbourhoods holding 22,845 active Properties. Those Properties get a stat
      score against a cohort that is not their neighbourhood. This story left the stat key
      alone because changing it moves stat_score and combined_score for existing rows. A card
      can therefore show a stat band and a percentile computed on two different cohorts.
    location: >-
      src/adapters/metrics/scoring.py:48
    severity: medium
  - summary: >-
      The legacy percentile_rank, percentile_rank_rent and percentile_rank_sale are still served
      by the API, the export and the modal, including the fabricated 0.5 the single-property
      path writes.
    evidence: |-
      core/property_projection.py selects and maps the three legacy columns and
      frontend/src/components/PropertyModal.tsx renders them as a percentile. On the primary
      (2026-10-08) percentile_rank_rent is exactly 0.5 on 1,007 rows and percentile_rank_sale on
      817. _compute_type_scores defaults a missing rank to 0.5 and score_single_property passes
      0.5. This story stores the trustworthy value in new columns and does not touch the wire;
      Story 1.7 (badge, filter) and Story 1.8 (panel) are where the legacy fields can be
      replaced and then dropped. test_percentile_characterization_lock.py pins the legacy
      behaviour and has to be edited by the story that removes it.
    location: >-
      src/core/property_projection.py:30
    severity: low
  - summary: >-
      The single-property path spends about one second of database time per scored Property on
      its cohort count, because the folded cohort key cannot use an index.
    evidence: |-
      Read-only on the primary, 2026-10-08, the second statement of
      _single_property_percentile_counts for a Property of the Savassi cohort (309 rent, 1,429
      sale members): 0.9 to 1.1 s; plan = sequential scan of property_listings (288,028 rows,
      aggregated) and a parallel sequential scan of properties with the fold evaluated for every
      active row (66,043 x 3 removed by the filter). It was 386 ms before the key was folded.
      The first statement takes 4 ms. It runs once per enrichment, next to a cached stat query of
      262 ms per listing type and an LLM call of seconds, so it is tolerable today. A fix needs an
      expression index on the folded label and city (a migration, and the fold becomes part of
      the schema) or a stored folded key; neither is a contained change.
    location: >-
      src/adapters/metrics/scoring.py:352
    severity: low
operator_actions:
  - "Wait for the orchestrator to merge feat/v0.14-s1.6-cohort-price-per-m2-percentiles into main, then from the primary checkout in Git Bash run: bash scripts/agent/migrate-primary.sh (it refuses while a cloud backfill runner is alive - wait or pause the runner, never delete the Redis keys). Do this BEFORE rebuilding any container: the new scoring code writes the new columns. Verify read-only: SELECT version_num FROM alembic_version; returns e6f7a8b9c0d1, and SELECT count(*) FROM metrics_scoring WHERE percentile_evaluated_at IS NOT NULL; returns 0."
  - "Rebuild and restart the primary stack so the API and workers run the merged scoring code: ./scripts/restart.sh --build. Verify: the api, worker and beat containers are up and GET http://localhost:8000/health answers."
  - "Straight after the rebuild, recalculate the stored scores (one request, one transaction; it took 62 minutes before this story; the stage's statement now runs in 7.8 s on the primary and the whole request is expected to take minutes, not measured end to end): curl --max-time 5400 -X POST http://localhost:8000/admin/scoring/recalculate -H 'X-API-Key: <the API key>'. Verify: the response carries stat_rows_updated close to 200,000. Note the run time."
  - "Run the two step 4 queries in docs/features/v0.14-s1.6-cohort-price-per-m2-percentiles.md against the primary (read-only: docker exec -i imoveis-postgres-1 sh -c 'PGOPTIONS=\"-c default_transaction_read_only=on\" psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\"' < query.sql). Expect about 109,000 rent and 123,000 sale rows with a value, about 4,500 and 3,700 suppressed, cheapest-quarter counts a little under a quarter of the rows with a value (about 26,500 rent and 30,100 sale), and 0 cohort members never evaluated apart from Properties first seen while the recalculation ran."
  - "Run the two step 5 queries in the same doc (read-only). The first must return 0; the second returns one row per listing type: wrong must be 0 in both, checked about 113,600 for rent and 126,700 for sale."
  - "Record the run time of the recalculation and the result rows of steps 4 and 5 in that doc under a new heading 'Operator steps applied on the primary (<date>)' placed after 'Operator steps (primary stack)', set the doc's Status line to done, and commit it as docs(v0.14-s1.6)."
---

<intent-contract>

## Intent

**Problem:** The only stored percentile is the legacy `percentile_rank*`: a SQL `PERCENT_RANK` with no minimum cohort size, a cohort for Properties without a neighbourhood (`Unknown`), a cohort key that merges same-named neighbourhoods of different cities (97 labels, 16,477 active Properties on the primary), and a fabricated `0.5` on the single-property path. "Among the N% cheapest of its neighbourhood" (FR-30) cannot be read from it.

**Approach:** The scoring stage (the AD-10 writer of `metrics_scoring`) computes, per Property and listing type, the share of its city × neighbourhood × listing-type cohort priced at or below it, on the Story 1.3 price basis, and stores it in new nullable columns with the cohort size and an evaluation timestamp. The math is one pure `core` function; SQL only counts. The legacy `percentile_rank*` columns, the API and the UI stay as they are; a characterization lock of that legacy output lands first.

## Boundaries & Constraints

**Always:**
- A characterization test of today's percentile output (bulk stage, single-property path, AD-12 list projection) lands in its own commit before any production change and is never edited afterwards; `test_scoring_characterization_lock.py` (Story 1.3) also stays green unedited.
- Percentile = (cohort members with price/m² ≤ this Property's) ÷ cohort size, in (0, 1]; lower is cheaper; tied Properties share one value (the inclusive count). `0.25` reads "among the 25% cheapest".
- Cohort member: an active Property with `area_m2 > 0`, an assigned neighbourhood, and a row in `core.price_basis.COHORT_PRICE_SQL` for that listing type. Its price/m² is that relation's price ÷ area. No other price is read; Listing-less Properties (legacy `properties.price`) are not members.
- Cohort key: listing type × city × neighbourhood, where neighbourhood is the spatial FK's name when assigned, else the `props_json` label, and city is the FK's city, else `props_json.city`; both compared trimmed and case-insensitively. A Property with no FK and a blank or missing label is unassigned.
- Null, never defaulted: cohort smaller than `scoring.percentile_min_cohort_size` (percentile null, cohort size stored); not a member (percentile and size null). A dual Property gets one percentile per listing type.
- `scoring.percentile_min_cohort_size` lives in `configs/app_config.yaml` through `AppConfig`, default 10, minimum 2 (a cohort of one never has a percentile).
- Both writers of the stage (`compute_neighborhood_stats`, `score_single_property`) produce the same values for the same rows and stamp `percentile_evaluated_at` whenever they evaluate a row, value or null. Only `adapters/metrics/scoring.py` writes the new columns.
- The bulk stage stays set-based: counts come from window functions in the one existing statement; no per-row query.
- The pure module imports nothing from `adapters`, `api`, `infra` (AD-1), is built test-first, and SQL is static text with bound parameters assembled by concatenation (BIN-135).
- The migration is additive, reversible, passes the alembic check for `metrics_scoring`, and is applied to the primary only by the operator.

**Never:**
- Change the value or meaning of any existing `metrics_scoring` column (`percentile_rank*`, stat, z, mean, median, combined, `price_basis`) or the stat cohort key.
- Touch `src/api/` (the wire is Story 1.7; `schemas.py` is a serial surface), `core/property_projection.py`, the frontend, scrapers, `scripts/`, `sprint-status.yaml`, `.bmad-loop/` or the primary stack.
- Read `pl.price`, `total_monthly_cost` or `properties.price` for a percentile; impute a percentile; write `0.5` or `0` for "unknown".
- Fix DW-39 or the stage's run time here (recorded, not changed).

## I/O & Edge-Case Matrix

Minimum cohort size 3 unless stated; all members active with `area_m2` 100, one city and neighbourhood.

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Distinct prices | rent price/m² 30, 40, 50, 70 | 0.25, 0.5, 0.75, 1.0; size 4 | No error expected |
| Ties | 30, 40, 40, 50 | 0.25, 0.75, 0.75, 1.0 | No error expected |
| All tied | 40, 40, 40 | 1.0 each | No error expected |
| Exactly at minimum | 3 members, minimum 3 | values stored | No error expected |
| One below minimum | 2 members, minimum 3 | percentile null, size 2, evaluated | No error expected |
| Single-listing cohort | 1 member, any minimum | null, size 1 | Minimum below 2 is rejected (`ValueError`, config validation) |
| Dual Property | rent cohort of 3, sale cohort of 2 | rent value, sale null with size 2 | No error expected |
| Missing area | `area_m2` NULL or 0 | percentile and size null; an existing row is cleared | Existing warning log on the single path |
| Unassigned neighbourhood | no FK, label missing or blank | percentile and size null; stat columns as today (`Unknown` cohort) | No error expected |
| Same label, two cities | `Centro` in two cities | two cohorts | No error expected |
| Label case / padding | `Savassi`, ` savassi ` | one cohort | No error expected |
| Rent basis | Listing `price` 3800, `rent_monthly` 3000 | ranked at 30 R$/m² | No error expected |
| Listing-less legacy Property | `properties.price` only | percentile and size null; not counted in any cohort | No error expected |
| Inactive Property or Listing | inactive | not a member; a stored percentile is cleared by the full bulk run | No error expected |
| Single-property path | any row above | same percentile and size as the bulk run on the same rows | No error expected |
| Row never evaluated | row inserted by the enrichment task before scoring | all five columns null | No error expected |
| Inconsistent counts | at-or-below 0 or above the size | — | `ValueError` from the pure function |

</intent-contract>

## Code Map

- `src/adapters/metrics/scoring.py` -- the only writer. `compute_neighborhood_stats` (`:218-516`): one statement, CTEs `listing_min` (= `COHORT_PRICE_SQL`) → `typed` (Listing branch `:255-272`, legacy `properties.price` branch `:273-301`, both restricted by the optional label key `where_clause`) → `stats` (windows; legacy `PERCENT_RANK` `:319-323`) → `pivoted` (`:326-351`); rows read by position (`:404-416`), written through `_apply_type_fields` (`:182-215`). `score_single_property` (`:688-826`): early return without a write when no usable price/area (`:723-726`); passes `pct_rank=0.5` (`:753`, `:762`). `_COHORT_KEY_SQL` (`:39`) is the stat cohort key (label or `Unknown`) and must not change. `_compute_type_scores` (`:144-166`) defaults the legacy percentile to 0.5 — legacy, leave.
- `src/core/price_basis.py` -- `COHORT_PRICE_SQL` relation `(property_id, listing_type, price, price_basis)`; a filter on `property_id` from an outer join is pushed into it (index scan, 0.14 ms on the primary).
- `src/adapters/db/models.py:154-197` -- `MetricsScoring`, `__table_args__` with `ck_metrics_scoring_price_basis`.
- `alembic/versions/d5e6f7a8b9c0_metrics_scoring_price_basis.py` -- current head and style reference; version files never import `src/`.
- `src/infra/config.py:475` `ScoringConfig` (frozen pydantic); `configs/app_config.yaml:267` `scoring:` block.
- Callers, signatures unchanged: `src/api/admin.py:187` (`POST /admin/scoring/recalculate`, the only bulk trigger, never passes a key); `src/adapters/queue/tasks.py:707` (after enrichment; `:686` inserts a bare `MetricsScoring` first).
- `src/core/property_projection.py` -- `LIST_SELECT_COLUMNS` (`:476`), `map_property_list_item` (`:300`), `_dual_score_fields` (`:30`): the AD-12 projection that exposes `percentile_rank*`; read-only here, locked by the new characterization test.
- Tests to keep green unedited: `src/tests/integration/test_scoring_characterization_lock.py`, `test_scoring_price_basis.py` (its migration test downgrades through this story's revision), `test_scoring_spatial_cohorts.py`, `test_scoring_neighborhood_stats_n_plus_one.py` (SELECT count of the bulk stage ≤ 4 and constant), `test_scoring_sql_assembly.py`, `src/tests/unit/test_scoring_*.py`, `test_price_basis.py`. Fixture patterns: `_make_property` / `_add_listing` / `real_redis` / `TestPriceBasisMigration` in `test_scoring_price_basis.py`.
- Primary, read-only, 2026-10-08 (`alembic_version` `d5e6f7a8b9c0`): 200,081 active Properties, 0 with `neighborhood_id`, 0 `neighborhoods` rows, 3 without a label, 315 without area, 0 active priced Properties without a Listing; 3 cities; 2,944 labels (2,754 after trim + lower-case); 97 labels in more than one city (16,477 Properties). Cohort members below a size, city-aware key: rent 113,541 members — <5: 2,407, <10: 5,456, <20: 10,505, <30: 14,989; sale 126,638 — 2,115 / 4,427 / 7,978 / 10,446. Timings: the percentile counts for all 240,188 members 3.3 s; single-property lookup 0.14 ms + 386 ms; today's cached cohort stats query 262 ms per type. Legacy `percentile_rank_rent` = 0.5 on 1,007 rows, `_sale` on 817.
- Docs: `docs/features/_template.md`; `docs/features/v0.14-s1.3-one-cohort-price-basis-for-rent.md` (operator-steps model); `docs/data-models-api.md:12,33`.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/integration/test_percentile_characterization_lock.py` -- NEW, first commit, no production change: legacy `percentile_rank`, `_rent`, `_sale` for ties, a single-member cohort, the `Unknown` cohort, one label in two cities and a dual Property through the bulk stage; the single-property path's `0.5`; the AD-12 list projection's percentile fields and its exact key set -- characterization lock
- [x] `src/tests/unit/test_cohort_percentile.py` -- NEW, before the module: the matrix rows that are pure math (distinct, ties, all tied, at minimum, below, single, invalid counts, invalid minimum), a whole-cohort reference helper, import purity -- TDD for `core`
- [x] `src/core/cohort_percentile.py` -- NEW: `cohort_percentile(at_or_below, cohort_size, min_cohort_size)`, the whole-cohort reference `cohort_percentiles(values, min_cohort_size)`, and the SQL expressions for the cohort city and neighbourhood -- the one definition
- [x] `src/infra/config.py`, `configs/app_config.yaml` -- `scoring.percentile_min_cohort_size` (default 10, ≥ 2) -- config-owned threshold (AD-2)
- [x] `alembic/versions/e6f7a8b9c0d1_metrics_scoring_cohort_percentiles.py`, `src/adapters/db/models.py` -- NEW revision on `d5e6f7a8b9c0`: `price_per_m2_percentile_rent`, `price_per_m2_percentile_sale` (Float), `percentile_cohort_size_rent`, `percentile_cohort_size_sale` (Integer), `percentile_evaluated_at` (DateTime), all nullable, with range CHECKs; model mirrors them -- schema
- [x] `src/adapters/metrics/scoring.py` -- bulk: cohort size and at-or-below counts joined into the existing statement, values through the pure function, cleared for rows whose Property is no longer a member on a full run; single path: the same counts for one Property, and an existing row cleared when the Property has no usable price or area -- the behaviour
- [x] `src/tests/integration/test_cohort_percentiles.py` -- NEW: every Postgres row of the matrix through the bulk stage, bulk against single-path parity, SQL counts against the Python reference, clearing, CHECKs, migration down/up to explicit revisions, model parity, a static check that only `scoring.py` assigns the new columns -- real-row proof
- [x] `docs/features/v0.14-s1.6-cohort-price-per-m2-percentiles.md`, `docs/data-models-api.md` -- feature doc (all template sections: definition, thresholds chosen, measurements, operator steps with the verification SQL, what Story 1.7 and 1.9 read) and the table row / revision count

**Acceptance Criteria:**
- Given the branch history, when the first commit that touches production code is inspected, then `test_percentile_characterization_lock.py` exists in an earlier commit, and neither it nor `test_scoring_characterization_lock.py` is modified by a later commit.
- Given a database at `d5e6f7a8b9c0`, when `alembic upgrade head` then `alembic downgrade d5e6f7a8b9c0` run, then both succeed, existing rows read null in the five columns, and `compare_metadata` reports no difference on `metrics_scoring`.
- Given `configs/app_config.yaml`, when `scoring.percentile_min_cohort_size` is changed and the stage runs, then suppression follows the new value with no code change; a value below 2 fails config validation.
- Given `src/`, when searched, then the percentile path contains no `pl.price` and no `properties.price` read, and no module other than `adapters/metrics/scoring.py` assigns the five columns.
- Given the bulk stage on a seeded corpus, when the SQL statements it emits are counted, then the count does not depend on the number of Properties.
- Given the story is code-complete, when the session ends, then the spec is `awaiting-operator` with `operator_actions` covering the primary migration, the rebuild, the recalculation and the read-only SQL that confirms the stored percentiles.

## Spec Change Log

- 2026-10-08, follow-up pass: the dispatch of this pass lifts one line of the intent contract, "Never ... fix the stage's run time here", for the cohort median only: compute it once per cohort if the stored values stay byte-identical under both characterization locks. Done in commit `57ef0bb5`; DW-39 and everything else on the Never list stand. The contract block itself is not edited.

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 29 findings — high 0, medium 6, low 19, false 4, maybe-false 0
- findings:
  - `[medium]` `[patch]` Blind: the single-property path reads its own price/m² in one statement and counts the cohort in a second; a Listing change committed between them can give `at_or_below` 0 and raise `ValueError` inside the enrichment task — real under READ COMMITTED. The second statement now counts the other members (`p.id <> :pid`) and the Property is added in Python, so the pair is always within `1..size`.
  - `[low]` `[patch]` Blind: a full run writes the snapshot it read at its start, so a row scored by the single path during the run is overwritten with older counts and an earlier stamp — true, and the stat columns already behaved this way; the stamp is the honest time of the data. Stated in the feature doc Notes.
  - `[low]` `[patch]` Blind: every full run now updates every scored row and the cost is unmeasured — true. The doc now says what moves (a second dead row version per row; the same request already rewrites every row in `recalculate_all_combined_scores`; the writes happen after the long `SELECT`) and operator step 3 records the run time.
  - `[medium]` `[defer]` Blind: cohort peers are left inconsistent by the single path and nothing but the manual endpoint corrects them — verified (one caller, no beat task); the same lag predates this story for every cohort statistic. Deferred with the run-time blocker. The remark about `sprint-status.yaml` and follow-up keys does not apply: the orchestrator owns both.
  - `[low]` `[patch]` Blind: the Story 1.9 contract does not say what a missing `metrics_scoring` row means — one sentence added to the reader table in the feature doc.
  - `[low]` `[reject]` Blind: `TestMigration` and the static class lack `@pytest.mark.integration` and the static checks belong in `unit/` — the gate selects the directory and runs it serially (`validate.py:468`); `TestMigration` follows `TestPriceBasisMigration` and `TestListingCostMigration`, which are unmarked for the same reason. Moving the static class is a relocation with no behaviour gained in the tier this code needs.
  - `[low]` `[patch]` Blind: the single-writer test also flags reads, so Story 1.7 would trip it by selecting the columns in the projection — verified in `_references`. String constants are now flagged only when the SQL text contains `UPDATE` or `INSERT`; a test pins both directions.
  - `[low]` `[patch]` Blind: the lock's "never edited" wording conflicts with Story 1.7 changing the projection key set — the lock file itself is not edited (acceptance criterion 1); the feature doc now tells Story 1.7 to change the pinned key set in the commit that changes the projection.
  - `[low]` `[patch]` Blind: a keyed run pays the full percentile cost and its test cannot tell a whole cohort from the keyed rows — the cost is moot (no production caller passes a key); the test gap is the verification-gap finding below and is fixed there.
  - `[low]` `[patch]` Blind: the operator verification cannot separate a defect from expected drift — step 5 now leaves out cohorts touched after the full run (rows carrying another stamp) and reports them in their own column, so `wrong` must be exactly 0. The query was run read-only on the primary against shadowed columns to check that it executes.
  - `[low]` `[patch]` Blind: the key ignores `state` and the number of Properties without a city was not measured — measured: 0 active Properties lack a city (doc updated). State stays out of the key: same-named cities in two states with same-named neighbourhoods is not a state shown to exist (3 cities on the primary); noted in the doc.
  - `[medium]` `[patch]` Blind: accent and whitespace variants split one neighbourhood into several cohorts, untested — measured read-only on the primary: 537 spellings of 268 neighbourhoods, 22,845 active Properties. The key is now compared folded (NFC, lower case, Portuguese accents removed, whitespace collapsed) in `core/cohort_percentile.py`; an integration test covers four spellings, a unit test the expression. Re-measured cost of the bulk counts: 6.5 s (3.3 s before).
  - `[low]` `[reject]` Blind: the floor of 2 lives in `ScoringConfig` (`ge=2`) and in `MIN_COHORT_SIZE_FLOOR` — `infra/config.py` imports nothing from `core` today; `test_floor_matches_the_pure_module` fails if they drift. The remark about an index for the Story 1.7 filter is now a line in the doc.
  - `[medium]` `[patch]` Edge: `at_or_below` 0 after a concurrent price change between the two statements — same defect as the first row; fixed there.
  - `[low]` `[patch]` Edge: a newer single-path result is overwritten by the bulk run's older snapshot — same as the second row; documented.
  - `[low]` `[reject]` Edge: two `neighborhoods` rows with the same name and city in different states share a cohort — the table is empty on the primary and the case needs two same-named cities; a guard for a state not shown to exist.
  - `[low]` `[patch]` Edge: after `scoring.percentile_min_cohort_size` changes, stored rows keep the old threshold until a recalculation — true by design; the doc now says so and how a reader can honour the new value meanwhile (`percentile_cohort_size_<type>`).
  - `[low]` `[reject]` Edge (claim): the statement-count test leaves the ORM flush statements out — it counts what this story added (reads, the counting CTE, the clearing statement); the per-row ORM writes are the stage's existing write path and are batched by the driver, so their statement count is not a stable thing to pin.
  - `[low]` `[patch]` Gap: the keyed-run test seeds only rows inside the key, so restricting the counts to the key would pass — the test now adds a member under another spelling, blanks the keyed rows first and asserts size 4 and shares over 4.
  - `[low]` `[patch]` Gap: the clearing statement's stamp is asserted with `>=`, which holds when it does not stamp — changed to `>`.
  - `[low]` `[defer]` Intent: the trustworthy value exists only at rest; the API, export and modal still serve the legacy value — by the intent (Story 1.7 puts the value on the wire and `schemas.py` is not to be edited here); the legacy fields and their fabricated `0.5` are deferred to the stories that replace them.
  - `[medium]` `[defer]` Intent: "when the stage runs" holds for the whole cohort only on the manual bulk run; the automatic path updates one Property — same root as the fourth row; deferred with it.
  - `[false]` `[reject]` Intent: no test goes through the Celery task or the admin endpoint for the new columns — both call the two functions under test with unchanged signatures (`tasks.py:707`, `admin.py:187`); the write happens inside those functions.
  - `[low]` `[reject]` Intent: tie handling is not a config value — a tie rule is a definition, not a threshold: one accepted value in `AppConfig` would be a knob with nothing to turn, and a second value would need a second SQL form. It is stated in the doc and reported as a decision.
  - `[medium]` `[defer]` Intent: two cohort definitions coexist in one stage (city-aware for the percentile, label-only for the stat columns) — true; changing the stat key moves existing stat scores and is excluded by the intent ("do not weaken the existing lock"). Deferred with the measurement.
  - `[false]` `[reject]` Intent: a Property with no area and no row gets no row, and an unscored row keeps a NULL stamp — a missing row reads NULL through the projection's LEFT JOIN, which is the "skipped with a null" the story asks for; an existing row is cleared and stamped (tested on both paths).
  - `[low]` `[patch]` Intent: the single path adds two statements per Property and the every-row update is unmeasured — same as the third row; documented with the measured 0.14 ms + 386 ms.
  - `[false]` `[reject]` Intent: AD-10 — the auditor found the single-writer rule consistent with it; no divergence reported.
  - `[false]` `[reject]` Intent: "the main production change looked uncommitted" — the auditor read the primary checkout's log; on this branch `ab496950` (lock) precedes `006928cc` and `4a10c2a7` (first `scoring.py` change), and no later commit touches either lock file.

### 2026-10-08 — Review pass (follow-up)
- verdicts: 28 findings — high 0, medium 5, low 19, false 4, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: the feature doc says the per-row median is "not changed here" while the diff replaces it — true: the `perf` commit of this pass landed after the doc. Doc updated (Approach, Measurements, Changes, Notes).
  - `[low]` `[patch]` Blind: operator step 3 is sized for the 62-minute run — step 3 and `operator_actions` now state the measured 7.8 s for the statement and that the whole request is expected to take minutes, unmeasured end to end.
  - `[medium]` `[patch]` Blind: no test in the diff pins the median rewrite — same defect as the verification-gap row below; fixed there.
  - `[medium]` `[defer]` Blind: once neighbourhood geometries exist, a Property moved to its FK cohort by the single path leaves its label peers stale — carried: same root as the first pass's "cohort peers are left inconsistent by the single path" (deferred entry "Nothing schedules the bulk scoring stage"). The primary has 0 `neighborhoods` rows.
  - `[false]` `[reject]` Blind: `percentile_evaluated_at` (application UTC) and `now()` columns are on two clocks — `SHOW timezone` on the primary returns `UTC` and `now()::timestamp` equals `now() AT TIME ZONE 'utc'`; both stamps are naive UTC. Recorded in the doc Measurements.
  - `[false]` `[reject]` Blind: rows the full run never reaches keep a NULL stamp — carried: first pass, "an unscored row keeps a NULL stamp"; by design and stated for Story 1.9 in the doc Notes.
  - `[low]` `[reject]` Blind: the single-writer static check misses `query.update({Model.col: ...})`, `setattr` and `**{...}` forms — true; it is a tripwire for the ordinary forms, and catching dynamic writes means more parsing rules for a write nobody is shown to make.
  - `[medium]` `[defer]` Blind: the single path adds two whole-table statements per enrichment and its cost was not re-measured after folding — measured read-only on the primary: 4 ms + 0.9 to 1.1 s (386 ms before folding). Tolerable next to an LLM call; an index needs a migration. Deferred with the plan as evidence; doc Measurements and Notes updated.
  - `[low]` `[reject]` Blind: a no-break space, hyphen or apostrophe variant still splits a cohort — measured: `\s` does not match U+00A0 on the primary; 6 active Properties carry a non-ASCII space in the label and 10 a typographic apostrophe, of 200,151. Widening the fold changes the key, its unit test and the operator query for 16 Properties whose result today is a suppressed singleton, not a wrong value. Stated in the doc.
  - `[low]` `[patch]` Blind: step 4 expects the cheapest-quarter counts "close to a quarter" although the inclusive share puts fewer than a quarter at or below 0.25 — true in direction, small in size: 24.3% rent and 24.5% sale on the primary's data. The doc now gives those numbers and the reason.
  - `[low]` `[patch]` Blind: the lock's "never edited" wording against the doc telling Story 1.7 to edit the pinned key set — carried: first pass, same row; the doc already tells Story 1.7 what to do.
  - `[low]` `[patch]` Blind: `test_missing_area_clears_an_existing_row` compares two `datetime.now()` stamps with `>` and can tie on a coarse clock — the test now ages the first stamp to 2000-01-01 before the second run, so the assertion still fails when the clearing statement does not stamp.
  - `[low]` `[reject]` Blind: `TestMigration` and the static class carry no marker and the migration test changes the schema mid-suite — carried: first pass, same row (the gate selects the directory and runs it serially).
  - `[low]` `[reject]` Edge: a label with a no-break or zero-width space is its own cohort — same as the Blind row above; measured and stated.
  - `[low]` `[reject]` Edge: a Property assigned to a `neighborhoods` row with a blank name has no fallback to its label — the table is empty on the primary and nothing is shown to create a blank-named row; a guard for a state not shown to exist.
  - `[medium]` `[patch]` Edge: operator step 5 does not count a member of a cohort at or above the minimum whose stored percentile is NULL (`abs(NULL - x) > 1e-9` is NULL) — true. The filter now has `stored IS NULL OR ...`; run against a stand-in table with one such row injected it reports `wrong` 1.
  - `[low]` `[patch]` Edge (claim): the doc's "not changed here; recorded as a deferred finding" is false after commit `57ef0bb5` — same as the first Blind row; fixed there.
  - `[medium]` `[patch]` Gap: the median of the unkeyed bulk run is not pinned per stat cohort; a `medians` CTE grouped by listing type alone passes every test — reproduced: with that wrong grouping the backend tier fails on nothing but the new test. Added `TestMedianOncePerCohort` (unkeyed run, four stat cohorts, both types, a dual row, the `Unknown` cohort, an even-sized cohort).
  - `[low]` `[patch]` Gap (other): the doc contradicts the code on the median — same as the first Blind row.
  - `[low]` `[reject]` Intent: the cohort key folds accents and inner whitespace, wider than the contract's "trimmed and case-insensitively" — true; the first pass patched it on a measurement (537 spellings of 268 neighbourhoods) and the dispatch of this pass names the folded key as the design under review. The fix would be an edit of this spec. The auditor's side remark (the Python reference test uses `.strip().lower()` and passes only for want of accents in its corpus) is covered by the new both-paths test on accent variants.
  - `[false]` `[reject]` Intent: stamping is narrower than "every row a full run passes over" — carried: first pass, same row.
  - `[low]` `[patch]` Intent: the feature doc describes the pre-addendum median — same as the first Blind row.
  - `[false]` `[reject]` Intent: commit order and the own `perf` commit cannot be checked from the flattened diff — checked in git: `git log main..HEAD` touches `test_percentile_characterization_lock.py` only in `ab496950` (the first commit) and `test_scoring_characterization_lock.py` in none; the median change is alone in `57ef0bb5`.
  - `[low]` `[patch]` Intent: "byte-identical" median is evidenced only to the locks' tolerance — measured read-only on the primary: the old subquery, evaluated once for each of the 5,080 stat cohorts, equals the joined median under `float8send` for all of them, and the join keeps all 240,281 rows; the new test asserts exact equality.
  - `[low]` `[patch]` Intent: `updated_at` now moves on every full run — carried: first pass ("every full run now updates every scored row"), stated in the doc.
  - `[low]` `[patch]` Intent: the tests exercise neither the triggers, the primary, the gate's `alembic check`, nor bulk-against-single agreement on FK-assigned or accent-variant rows — the last part was a real gap: new test `test_spelling_variants_and_a_spatial_assignment_agree_on_both_paths`. The rest is carried (triggers: first pass `false`; the primary is the operator steps; the gate runs `alembic check` itself).
  - `[low]` `[patch]` Lead: operator step 5 recomputes rent only, so a defect in the sale columns passes the operator check — the query now unpivots both types and returns one row per type.
  - `[low]` `[patch]` Lead: step 5 says `wrong` must be exactly 0, but a Property cleared by the single path or relabelled by a scrape after the run leaves its old peers one too large and the query cannot see why — the doc now names both causes and how they look.

## Design Notes

- **New columns, legacy untouched.** `percentile_rank*` is on the wire, in the export and in the modal with a different definition (`PERCENT_RANK`, cheapest = 0, defaults). Redefining it in place would change the API silently and force an edit of the Story 1.3 lock. Story 1.7 puts the new value on the wire and can retire the legacy fields there.
- **Inclusive share, not `PERCENT_RANK`.** The badge says `entre os N% mais baratos`. With the inclusive share the sentence is literally true for every member (cheapest of 20 → 5%); `PERCENT_RANK` gives 0% for the cheapest and depends on n − 1.
- **SQL counts, Python divides.** Both writers get `(at_or_below, cohort_size)` from SQL and call one pure function, so the minimum-size rule and the tie rule exist once and are unit-tested without Postgres.
- **City in the key.** The primary has no spatial assignment; labels such as `Centro` exist in all three cities. The stat cohort key keeps its label-only form (changing it moves stat scores; out of scope, recorded).
- **Minimum 10.** At 10 one member moves the value by at most 10 points and the 25% badge needs the two cheapest. It suppresses 4.8% of rent members and 3.5% of sale members on the primary; 20 would suppress 9.3% / 6.3%.
- **Cost.** Bulk: one extra CTE with two window counts over about 240,000 rows (3.3 s measured alone) inside a stage that took 62 minutes; no extra statement per row; one clearing `UPDATE` per full run. Single path: two extra statements per scored Property (about 0.4 s on the primary).

- **Shape of the SQL (guidance, not a contract).** Bulk: a CTE over `listing_min` joined to `properties` (+ `neighborhoods`), not restricted by the optional label key (a restricted run must still rank against whole cohorts), yielding per member `COUNT(*) OVER (PARTITION BY city, neighbourhood, listing_type)` and `COUNT(*) OVER (PARTITION BY city, neighbourhood, listing_type ORDER BY price_per_m2)` (the default frame includes peers, so ties share the inclusive count); left-joined by `(property_id, listing_type)` and pivoted beside the existing columns. Single path: statement 1 reads the Property's own city, neighbourhood and price/m² per type from the same expressions (`JOIN (COHORT_PRICE_SQL) lm ... WHERE p.id = :pid`); statement 2 counts the cohort with those values bound. Clearing on a full run: one `UPDATE` nulling the percentile and size columns (and stamping `percentile_evaluated_at`) for rows that hold a value or size and whose Property is not a member any more.

## Workspace and commits

- Work only in the git worktree `C:\Workfolder\imoveis\.run\wt\1-6` (branch `feat/v0.14-s1.6-cohort-price-per-m2-percentiles`). Every read, edit and git command happens there, with absolute paths or `git -C`. `C:\Workfolder\imoveis` itself is the primary checkout: never edit it, never run git in it. Only its interpreter is used: `C:\Workfolder\imoveis\.venv\Scripts\python.exe` (the worktree has no `.venv`).
- Read `AGENTS.md` and `CLAUDE.md` in the worktree first; they bind this work.
- Commit order (conventional commits, each ending with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`): (1) `test(v0.14-s1.6): ...` with only `test_percentile_characterization_lock.py`; (2) the pure module, its unit tests and the config key; (3) migration, model, `scoring.py`, integration tests; (4) docs. Do not commit this spec file and do not edit its `<intent-contract>` block; leave `sprint-status.yaml` and `.bmad-loop/` alone. Never merge, push or run `ship.py`.
- Integration tests need the ephemeral test stack that only the gate creates: run `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py --tier backend` from the worktree (allow 10 minutes) to run them. Never run `docker compose` against the project `imoveis`, never run `migrate-primary.sh`, never read `.env.local`. Write multi-line scripts and SQL with the Write tool, not shell heredocs.
- The lock commit must pass against the unchanged production code: run the gate once on commit (1) before writing production code.

## Verification

**Commands:**
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe scripts/agent/validate.py` -- expected: exit 0, `VALIDATION PASSED (tier=backend)`
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe -m pytest src/tests/unit/test_cohort_percentile.py -q -o addopts=` -- expected: all pass (development loop only, not validation)

**Manual checks (if no CLI):**
- `git log --oneline -- src/tests/integration/test_percentile_characterization_lock.py src/adapters/metrics/scoring.py` shows the lock commit before the first `scoring.py` commit.

## Auto Run Result

Status: awaiting-operator

**Summary.** The scoring stage now stores, per Property and listing type, the share of its city × neighbourhood × listing-type cohort priced at or below it (in (0, 1], lower is cheaper), computed on the Story 1.3 price basis, together with the cohort size and the time of the evaluation. A cohort below `scoring.percentile_min_cohort_size` (default 10) has no percentile; a Property without area, without a neighbourhood or without a Listing price has none either. Nothing is defaulted. The rule is one pure function in `src/core/cohort_percentile.py`; SQL only counts, and both writers (bulk and single-property) call the same function. The legacy `percentile_rank*` columns, the API and the UI are unchanged; a characterization lock of that legacy output landed first, in its own commit.

**Files changed.**
- `src/tests/integration/test_percentile_characterization_lock.py` (new, commit `ab496950`) — legacy `percentile_rank*` through the bulk stage, the single-property path and the AD-12 list projection (values and exact key set)
- `src/core/cohort_percentile.py` (new) — the percentile rule, the whole-cohort reference, the folded cohort key SQL
- `src/infra/config.py`, `configs/app_config.yaml` — `scoring.percentile_min_cohort_size` (10, minimum 2)
- `alembic/versions/e6f7a8b9c0d1_metrics_scoring_cohort_percentiles.py` (new), `src/adapters/db/models.py` — five nullable columns and four range CHECKs on `metrics_scoring`
- `src/adapters/metrics/scoring.py` — counts in the bulk statement, clearing on a full run, two count statements on the single path
- `src/tests/unit/test_cohort_percentile.py` (new), `src/tests/integration/test_cohort_percentiles.py` (new) — the rule, the matrix on Postgres, bulk against single path, SQL against the Python reference, migration, single writer
- `docs/features/v0.14-s1.6-cohort-price-per-m2-percentiles.md` (new), `docs/data-models-api.md` — feature doc with measurements and operator steps; table row and revision count

**Decisions taken where the story was open.**
- Minimum cohort size: 10 (config). Suppresses 4.0% of rent and 2.9% of sale cohort members on the primary.
- Percentile definition and ties: inclusive share (members at or below ÷ size); tied Properties share the value. Not a config value.
- Cohort key: listing type × city × neighbourhood, labels compared without case, accents or extra whitespace. The stat cohorts keep their label-only key.
- New columns instead of redefining `percentile_rank*`; nothing new on the wire (Story 1.7).
- Listing-less Properties (legacy `properties.price`) are in no percentile cohort.
- A cohort of one never has a percentile (config rejects a minimum below 2).
- `percentile_evaluated_at` and the cohort size are stored so Story 1.9 can tell "evaluated, suppressed" from "not evaluated".

**Review.** 29 findings from four layers: high 0, medium 6, low 19, false 4.
- Patched: 16 rows in 12 entries — medium 2 (single-path race that could fail the enrichment task; spelling variants splitting cohorts), low 10 (single-writer test flagged reads, keyed-run test, clearing stamp assertion, operator verification query, and six documentation points).
- Deferred: 4 entries — three from the review (4 rows): no scheduled bulk run so cohort peers lag (medium), the stat cohort key (medium), the legacy `percentile_rank*` still served (low); and one found while measuring, outside the review rows: the per-row median that makes the bulk stage take 62 minutes (medium).
- Rejected: 4 `false` and 5 `low`; each row and its reason is in the triage log.

**Follow-up review (first pass): recommended (true).** Patched counts: high 0, medium 2, low 10. The unverified risk: the folded cohort key (`_fold_sql`) and the changed single-path counting were written after the review layers ran. They are covered by tests and the gate, and no reviewer has read them.

**Verification.**
- `python scripts/agent/validate.py` on commit `28b01524` (auto tier: backend): exit 0, `VALIDATION PASSED (tier=backend)` — lint, 2337 unit, 227 integration, 62 contract tests. The gate is run again on the final commit that adds this spec.
- `alembic check` (informational, reports FAIL as on main): the known PostGIS and index drift only, nothing on `metrics_scoring`; `TestMigration` round-trips `e6f7a8b9c0d1` ↔ `d5e6f7a8b9c0` and compares the model with the migrated table.
- Matrix audit: every row has a passing test in `test_cohort_percentiles.py` (bulk and single path) or `test_cohort_percentile.py`.
- History: `ab496950` (lock) precedes every production commit; no later commit touches either lock file.

**Residual risks.**
- Not verified on the primary: the migration, the run time of the recalculation with the new columns, and the stored values. These are the operator actions.
- The single-path cohort count was timed before the key was folded (386 ms); the folded key adds string work to that scan and was not timed on that path.
- Between full runs the percentile of a Property's cohort peers lags (deferred entry).
- A change of the minimum cohort size takes effect on stored rows only after a recalculation.

### Follow-up review pass — 2026-10-08

Status: awaiting-operator

**Summary.** A fresh review of the whole diff (four layers plus a direct reading of the folded key, the single-path counts, the migration and the operator queries) found no defect in the production code of the story. It found the operator verification weaker than it read, one untested property of the new median SQL, and a feature doc that predated the median change. The deferred run-time finding was fixed in this pass at the dispatcher's request: the cohort median of the bulk statement is computed once per cohort and joined back.

**Files changed in this pass.**
- `src/adapters/metrics/scoring.py` (commit `57ef0bb5`, `perf`) — `medians` CTE joined into `stats` instead of a subquery per row; no other change
- `src/tests/integration/test_cohort_percentiles.py` (commit `d2eac956`) — per-cohort median on an unkeyed run; both writers on accent, case and whitespace variants plus a spatially assigned Property; clearing-stamp assertion independent of clock resolution
- `docs/features/v0.14-s1.6-cohort-price-per-m2-percentiles.md` (commit `8177f3e0`) — median change and measurements; step 3 run time; step 4 expected numbers; step 5 for both listing types with the NULL case; notes on the single-path cost and on what the fold does not cover

**The median.** Read-only on the primary, 2026-10-08: the whole statement (median, stat windows, percentile counts; 199,836 result rows) runs in 7.8 s. The old subquery evaluated once per stat cohort (5,080 rows, 147 s, about 29 ms a row against 240,281 rows in the stage) returns the same median as the joined form for every cohort, byte for byte (`float8send`). Both characterization locks pass unedited. Not measured: the whole request of operator step 3 (statement, about 200,000 ORM row updates, the combined-score `UPDATE`).

**Review.** 28 findings: high 0, medium 5, low 19, false 4.
- Patched: 8 entries (14 rows; two more `patch` rows are carried from the first pass and were not patched again) — medium 2 (the unkeyed median was unpinned; operator step 5 missed a NULL percentile in a cohort at or above the minimum), low 6 (stale doc on the median and run time; cheapest-quarter expectation; stamp assertion; both-paths test on spelling variants; step 5 for sale; the drift note on step 5).
- Deferred: 1 new entry — the single-path cohort count costs 0.9 to 1.1 s per scored Property with the folded key (low, measured). One prior entry carried (peers lag between full runs). The run-time entry is removed from `deferred:` because it is fixed.
- Rejected: 4 `false` (two clocks: the database runs in UTC; NULL stamp on unscored rows, carried; stamping breadth, carried; commit order, checked in git) and 6 `low` (no-break space and apostrophe variants, two rows: 16 Properties, stated in the doc; blank-named `neighborhoods` row; dynamic write forms in the single-writer check; unmarked migration test, carried; the folded key against the contract's wording). Each reason is in the triage log.

**Follow-up review: not recommended (false).** Follow-up pass; patched counts: high 0, medium 2, low 6. No patched entry was `high`, and both medium patches are a test and a verification query, each checked against the defect it targets (the wrong grouping fails only the new test; the query reports the injected row).

**Verification.**
- `python scripts/agent/validate.py` (auto tier: backend) on the working tree holding all code and test changes of this pass: exit 0 — lint, 2337 unit, 229 integration, 62 contract tests. The gate is run again on the final commit.
- Mutation check: with `medians` grouped and joined by listing type only, the backend tier exits 1 and the single failure is `TestMedianOncePerCohort`.
- The four operator queries of steps 4 and 5, extracted verbatim from the feature doc, ran read-only on the primary against a stand-in for `metrics_scoring` built from the live rows with the stage's own SQL: step 4 `rent_with_value` 109,093, `rent_suppressed` 4,518, `sale_with_value` 122,943, `sale_suppressed` 3,721, members never evaluated 0; step 5 first query 0; second query `checked` 113,611 rent / 126,664 sale, `wrong` 0 / 0. With a NULL percentile injected it reports `wrong` 1; with wrong sizes, 40,442.
- The predicate of the clearing `UPDATE`, as a `SELECT` on the primary: hash anti join, 1.9 s.
- The migration was read, not run on the primary: five `ADD COLUMN` without default (catalog only) and four `CHECK` constraints, each validated by one scan of about 200,000 rows under the table lock; downgrade drops the constraints, then the columns.

**Residual risks.**
- The run time of the whole recalculation request is estimated, not measured (operator step 3 records it).
- The stand-in used for the operator queries holds what the SQL computes; the real rows go through the Python division and the ORM. The integration tests cover that path on small data.
- 16 active Properties whose label carries a non-ASCII space or a typographic apostrophe are ranked in a cohort of their own spelling.
- Peers lag between full runs (deferred entry), now cheaper to close because the stage is fast.
