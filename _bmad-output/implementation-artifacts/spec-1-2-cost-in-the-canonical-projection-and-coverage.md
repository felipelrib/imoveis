---
title: 'Story 1.2 — Cost in the canonical projection and coverage'
type: 'feature'
created: '2026-10-08'
status: 'done'
baseline_revision: '0127cf0a1eb5e3350541310e5895acc834b20810'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-1-total-monthly-cost-on-the-persist-path.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Story 1.1 persisted the Total Monthly Cost columns on `property_listings`, but nothing reads them: the API projection still shows only legacy `price` / `condo_fee` / `iptu`, no view says which Listing decides a rent Property's cost, the list endpoint cannot sort or cap by total, and coverage telemetry cannot report cost completeness (FR-31, AD-12, NFR-6, SM-3).

**Approach:** Extend the one AD-12 serializer (`core/property_projection.py`) so every Listing carries its persisted cost components with explicit states and every Property carries one `deciding_listing_id` + `deciding_rule`; add a total-cost sort and cap to the shared list/export filter builder reading `total_monthly_cost` only; add a per-Platform cost-completeness block to `GET /admin/enrichment/coverage`.

## Boundaries & Constraints

**Always:**
- Every cost figure on the wire is a persisted column value copied as stored. States are labels derived from which columns are NULL / true — no arithmetic, no fallback to legacy `price` / `condo_fee` / `iptu` / `base_price`.
- Each projected Listing gains `id` (the `property_listings.id` UUID as a string) and a nested `cost` object: `rent_monthly`, `rent_state` ∈ {`known`, `unknown`, `not-applicable`}; `condo_fee_monthly`, `condo_fee_state` ∈ {`known`, `bundled`, `unknown`}; `iptu_monthly`, `iptu_state` ∈ {`known`, `bundled`, `unknown`}; `iptu_periodicity_source`; `fees_bundled`; `total_monthly_cost`; `total_state` ∈ {`complete`, `bundled`, `incomplete`, `not-applicable`}; `cost_complete`.
- Each projected Property (list, by-ids, export, detail, digest — everything going through the serializer) gains `deciding_listing_id`, `deciding_rule` ∈ {`lowest-complete-total`, `lowest-headline-price`} and `total_monthly_cost` (the deciding Listing's persisted total under `lowest-complete-total`, else null).
- Deciding rule (AD-12 + AD-19): the active rent Listing with the lowest non-null `total_monthly_cost` → `lowest-complete-total` (ties: `platform` ascending, then `id` ascending). When no active rent Listing has a total, the legacy primary Listing (unchanged `select_primary_listing`) → `lowest-headline-price`. Both null only when `primary_listing` is null.
- `sort_by=total_monthly_cost` orders by the lowest non-null `total_monthly_cost` among the Property's active rent Listings; Properties without one sort last in both directions.
- `max_total_monthly_cost=<n>` keeps Properties having an active rent Listing with `total_monthly_cost <= n`. With `include_incomplete_totals=true` it additionally keeps Properties that have an active rent Listing but none with a total. The same params exist on `/properties/export`.
- Coverage: `cost_completeness` is one row per Platform over active rent Listings of active Properties, with three mutually exclusive counts — `complete` (total present, not bundled), `bundled` (total present, `fees_bundled`), `incomplete` (no total) — their fractions, and `total`. Fractions are null when `total` is 0; a Platform with no active rent Listing has no row. Rows are ordered by platform.
- New SQL is static text with bound parameters (BIN-135: no f-string splicing of values); `core/` stays free of `adapters` / `api` imports.
- `src/api/schemas.py` and `src/tests/contract/` cover every new field and parameter.

**Never:**
- Change the meaning of existing wire fields: `price`, `primary_listing`, legacy listing `condo_fee` / `iptu` / `base_price` / `fees_bundled` (still `raw_json.fees_bundled`), `sort_by=price`, `max_price`.
- Write to `property_listings`, add a migration or an index, touch `core/listing_cost.py`, `core/dedupe.py`, `scoring.py`, scrapers, the frontend, `saved_searches.py`, `sprint-status.yaml` or the primary stack.
- Compute, impute or re-derive a cost value at read time; treat a NULL component as 0.
- Render cost in the UI (Story 1.8) or change the cohort price basis (Story 1.3).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Itemized rent Listing | rent 750, condo 120, iptu 59, `monthly`, total 929, complete | `cost`: all three `known`, `total_state` `complete`, values as stored | No error expected |
| Bundled rent Listing | rent 800, condo 57, iptu NULL, `fees_bundled`, total 857 | `condo_fee_state` and `iptu_state` `bundled`, `iptu_monthly` null, `total_state` `bundled` | No error expected |
| Incomplete rent Listing | rent 3500, condo 650, iptu NULL, not bundled, total NULL | `iptu_state` `unknown`, `total_monthly_cost` null, `total_state` `incomplete` | No error expected |
| Bundled but rent unknown | rent NULL, condo 57, `fees_bundled`, total NULL | `rent_state` `unknown`, fees `bundled`, `total_state` `incomplete` | No error expected |
| Sale Listing | condo 600, iptu 154.75, rent NULL, total NULL | `rent_state` and `total_state` `not-applicable`; fee states by their own columns | No error expected |
| Listing row without cost keys | dict lacking the new keys (older fake rows, digest fixtures) | every component `unknown`, `total_state` `incomplete` (rent) / `not-applicable` (sale); no exception | Missing keys read as NULL / false |
| Deciding: two complete totals | rent Listings A total 4200 (price 3000), B total 3900 (price 3400) | `deciding_listing_id` = B, `lowest-complete-total`, Property `total_monthly_cost` 3900; `primary_listing` still A | No error expected |
| Deciding: complete beats cheaper incomplete | A price 2500 total NULL, B price 3000 total 3900 | B decides, `lowest-complete-total` | No error expected |
| Deciding: no complete total | rent Listings all total NULL | `deciding_listing_id` = `primary_listing.id`, `lowest-headline-price`, Property total null | No error expected |
| Deciding: sale-only Property | only sale Listings | primary Listing, `lowest-headline-price`, total null | No error expected |
| Deciding: no priced Listing | `listings` empty | all three null | No error expected |
| Cap, default | `max_total_monthly_cost=4000`; P1 total 3900, P2 total 4100, P3 rent incomplete, P4 sale-only | only P1 | No error expected |
| Cap, incomplete requested | same + `include_incomplete_totals=true` | P1 and P3 | No error expected |
| Flag without a cap | `include_incomplete_totals=true` alone | no filtering effect | No error expected |
| Sort asc / desc | P1 3900, P2 4100, P3 incomplete | asc: P1, P2, P3; desc: P2, P1, P3 | No error expected |
| Inactive Listing holds the low total | inactive rent Listing total 1000, active one 4100 | sort, cap and deciding all use 4100 | No error expected |
| Invalid sort key | `sort_by=total` | 422 from the existing pattern validation | FastAPI validation error |
| Coverage, empty | no active rent Listings | `cost_completeness: []` | No error expected |
| Coverage counts | platform X: 2 complete, 1 bundled, 1 incomplete, plus an inactive Listing, a sale Listing and a Listing of an inactive Property | X: total 4, 2 / 1 / 1, fractions 0.5 / 0.25 / 0.25 | No error expected |

</intent-contract>

## Code Map

- `src/core/property_projection.py` -- the AD-12 serializer. `select_primary_listing` (`:44`, unchanged), `map_property_list_item` (`:149`) and `map_property_detail` (`:221`) both set `listings` / `primary_listing`; `LISTINGS_JSON_AGG` (`:294`) builds the per-Listing JSON (filters `pl.active = true`, no ORDER BY — selection must be order-independent) and is shared by list, by-ids, export, detail and `core/top_deals_digest.py:22`.
- `src/api/schemas.py:6` `PropertyListingModel`; `:21` `PropertyModel` and `:142` `PropertyDetailModel` (both `extra="ignore"`: a field missing from the model is silently dropped from the response); `:389-465` coverage models.
- `src/api/properties.py` -- `PropertyListFilters` (`:140`) and its export twin `PropertyExportFilters` (`:163`, adapted by `_export_filters_as_list_filters`); `_build_list_filters` (`:303`) builds WHERE / params / ORDER from allow-listed fragments; `_sort_price_expr` (`:125`) is the correlated-subquery pattern to mirror; `max_price` EXISTS filter at `:317-336`; order assembled at `:397-404` as `"<expr> <DIR>"`.
- `src/api/property_export.py:17,76,90` -- CSV column tuples derived from the projection dict; `listings` is already a JSON cell.
- `src/core/enrichment_coverage.py` -- pure math: `coverage_fraction` (`:95`, null on zero denominator, clamped), `CoverageReport` (`:86`), `build_coverage_report` (`:178`).
- `src/adapters/db/enrichment_coverage_queries.py` -- SQL constants, `CoverageInputs` (`:210`), `fetch_coverage_inputs` (`:296`). Denominator convention: active Properties.
- `src/api/admin.py:1081-1127` -- coverage route: `fetch_coverage_inputs` → `build_coverage_report` → `EnrichmentCoverageResponse.model_validate(asdict(report))`.
- `src/adapters/db/models.py:211-263` `PropertyListing` -- cost columns from Story 1.1; `fees_bundled` and `cost_complete` are NOT NULL booleans, `iptu_periodicity_source` NOT NULL; `property_id` is indexed.
- Tests to extend: `src/tests/unit/test_property_projection.py` (`_listing`, `TestMapPropertyProjection._row`), `test_properties_response_schema.py`, `test_property_export.py`, `test_enrichment_coverage.py` (`_report`), `test_admin_coverage_api.py` (`_inputs`), `src/tests/contract/test_api_contract.py` (`_PROJECTION_KEYS` `:335`, `TestAdminEnrichmentCoverageContract` `:748`), `src/tests/integration/test_enrichment_coverage_sql.py` (seed helpers, `wipe_safe_db_session`). Seeding pattern for list-endpoint integration tests: `src/tests/integration/test_sort_price_listing_type.py`.
- Characterization lock (must stay green unchanged): the existing tests in `test_property_projection.py`, `test_sort_price_listing_type.py`, `test_max_price_sale_filter.py`, `test_top_deals_digest.py`, `test_property_export.py` and the contract suite.
- Docs: `docs/api.md:13-51` (properties) and `:171-212` (coverage); feature doc from `docs/features/_template.md`, named like `docs/features/v0.14-s1.1-total-monthly-cost-on-the-persist-path.md`.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_property_projection.py` -- write first: every Listing-state and deciding-rule row of the matrix, order independence of the deciding choice, both mappers carrying the three Property fields, validation of the mapped dict against `PropertyModel` / `PropertyDetailModel` -- TDD for `core`
- [x] `src/core/property_projection.py` -- add the cost columns and `id` to `LISTINGS_JSON_AGG`; a listing-cost view builder, a deciding-listing selector, and wire both into the two mappers -- one serializer for every view
- [x] `src/api/schemas.py` -- `ListingCostModel` (states as `Literal`), `PropertyListingModel.id` / `.cost`, the three Property fields on `PropertyModel` and `PropertyDetailModel`, `CostCompletenessModel` and `EnrichmentCoverageResponse.cost_completeness` -- wire contract
- [x] `src/api/properties.py` -- `sort_by` pattern gains `total_monthly_cost`; `max_total_monthly_cost` (≥ 0) and `include_incomplete_totals` on both filter models; filter and NULLS LAST ordering in `_build_list_filters` -- sort/filter reads `total_monthly_cost` only
- [x] `src/api/property_export.py` -- CSV columns `deciding_listing_id`, `deciding_rule`, `total_monthly_cost` -- export serializes the same projection
- [x] `src/core/enrichment_coverage.py`, `src/adapters/db/enrichment_coverage_queries.py`, `src/api/admin.py` -- per-Platform counts query, pure builder with fractions, `cost_completeness` on the report and response -- NFR-6 / SM-3
- [x] `src/tests/unit/test_enrichment_coverage.py`, `test_admin_coverage_api.py`, `test_property_export.py`, `test_properties_response_schema.py` -- builder math (zero total, ordering, fractions), route passes the block through, CSV columns, filter-builder SQL for the new params -- unit coverage
- [x] `src/tests/integration/test_total_monthly_cost_sort_filter.py` (new), `src/tests/integration/test_enrichment_coverage_sql.py` -- seeded Postgres rows for the cap, flag, sort and inactive-Listing rows and for the coverage counts row -- the SQL is only meaningful against real rows
- [x] `src/tests/contract/test_api_contract.py` -- projection keys, per-Listing `cost` shape and state vocabulary, deciding-rule vocabulary and its consistency with `listings`, the new query params on list and export, `cost_completeness` shape -- AC 3
- [x] `docs/features/v0.14-s1.2-cost-in-the-canonical-projection-and-coverage.md`, `docs/api.md` -- feature doc (all template sections) and the API reference for the new fields, params and coverage block

**Acceptance Criteria:**
- Given a Property with active rent Listings, when it is returned by `GET /properties`, `/properties/by-ids`, `/properties/export` or `/properties/{id}`, then it carries exactly one `deciding_listing_id` that names one of its `listings`, with a `deciding_rule` from the two-value vocabulary, and each Listing carries `cost` with a state for every component.
- Given the serializer, when a Property is projected, then no cost figure in the output differs from the stored column value of the Listing it belongs to.
- Given `GET /properties?sort_by=total_monthly_cost` or `max_total_monthly_cost`, when the SQL is built, then the only cost column it references is `total_monthly_cost`.
- Given `GET /admin/enrichment/coverage`, when called twice over an unchanged corpus, then `cost_completeness` is identical and for every row `complete + bundled + incomplete == total`.
- Given the existing projection, sort-by-price, max-price, export and digest tests, when the suite runs, then they pass without modification of their existing assertions.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 28 findings — high 0, medium 2, low 11, false 15, maybe-false 0
- findings:
  - `[medium]` `[patch]` Blind: `sort_by=total_monthly_cost` has no secondary sort key, so the large no-total group ties and LIMIT/OFFSET pages can repeat or skip rows — the order now ends `NULLS LAST, p.id`; unit assertions updated.
  - `[false]` `[reject]` Blind: `deciding_rule` can be set with a null `deciding_listing_id` — only for a row without `id`; `LISTINGS_JSON_AGG` always emits `pl.id` (primary key), so no database row reaches that branch. Hand-built rows without the key must not raise (matrix row "Listing row without cost keys").
  - `[false]` `[reject]` Blind: a deciding Listing can exist without a primary Listing when `price` is unparseable — `property_listings.price` is NOT NULL Float, so a totalled rent Listing is always priced.
  - `[low]` `[patch]` Blind: the contract helper never ties `cost_complete` to the total — `_assert_listing_cost` now asserts `cost_complete == (total_monthly_cost is not None)`.
  - `[low]` `[patch]` Blind: the contract helper does not check a `bundled` fee state against the flag — same helper, now asserts `(state == "bundled") == fees_bundled` for both fees.
  - `[false]` `[reject]` Blind: an unexpected stored `iptu_periodicity_source` fails the whole response — the column carries `ck_property_listings_iptu_periodicity_source` (three values, NOT NULL), so no other value can be stored.
  - `[low]` `[reject]` Blind: the cap/sort contract tests assert nothing on an empty corpus — true of every contract test in the file by design (corpus-agnostic shape checks); the seeded behaviour runs in `test_total_monthly_cost_sort_filter.py`, which the gate executed (the integration suite passed with none skipped). Seeding inside the contract suite is more than a direct correction.
  - `[false]` `[reject]` Blind: the new integration file writes to an unguarded database — `src/tests/integration/conftest.py` has the autouse `_refuse_primary_database_url` (`assert_wipe_safe_database_url`) for every test in the directory; the file follows the `test_sort_price_listing_type.py` pattern.
  - `[low]` `[patch]` Blind: no real-row test of the CSV export — the export integration test now also requests `format=csv` and checks the last three cells of the P1 row.
  - `[low]` `[reject]` Blind: the digest is claimed but untested for the new keys — the digest renders no `listings` field (confirmed by the verification-gap layer); its existing tests run through the changed serializer and pass, and `test_rows_without_cost_keys_still_project` covers digest-shaped rows.
  - `[low]` `[patch]` Blind: `enrichment_coverage` docstring still says "four aggregates" — corrected to five.
  - `[low]` `[reject]` Blind: platform order is applied in SQL and again in Python; a null platform folds to `""` — the builder's order is the one on the wire and is deterministic; `platform` is NOT NULL and platform keys are lowercase ASCII registry names, so the two orders cannot differ in practice.
  - `[low]` `[patch]` Blind: `_stored_total` had an unreachable flat-key fallback and an untested `float()` guard — both deleted; the selector reads `cost.total_monthly_cost` only.
  - `[false]` `[reject]` Blind: spec is `in-review` with unticked tasks and empty logs — mid-review state; finalization writes them.
  - `[false]` `[reject]` Blind: the deploy-order hazard is only prose — it is the first entry of Story 1.1's `operator_actions` ("migrate BEFORE rebuilding any container"), which already orders the API image after the migration.
  - `[false]` `[reject]` Blind: frontend and saved searches do not know the new params and no follow-up is minted — the story's criterion names "the property listing endpoint"; UI consumption is Story 1.8 and saved-search matching is Stories 1.9/1.10. Recorded in the feature doc.
  - `[medium]` `[patch]` Edge: page boundaries on equal or NULL sort keys — same defect as the first Blind row; fixed by the `p.id` tie-break.
  - `[false]` `[reject]` Edge: `max_total_monthly_cost=inf` passes `ge=0` — a cap of +infinity keeping every Property that has a total is the correct result of the comparison, not a degenerate one; NaN is already rejected by `ge=0`.
  - `[low]` `[reject]` Edge: a sale Listing with a stored total would show a value beside `not-applicable` — the single writer (`core.listing_cost.compute_listing_cost`) cannot produce a total without a rent, and masking it would break "copied as stored"; a guard for an undemonstrated state.
  - `[low]` `[reject]` Edge: the cost query failing on an unmigrated database takes the whole coverage endpoint down — an unmigrated database fails every Property read as well; swallowing the error would report an empty block as if measured.
  - `[low]` `[patch]` Gap: the `listing_type = 'rent'` clause of the sort and cap SQL was only string-asserted — the seeded P4 sale Listing now carries a total of 500; cap, both sorts and the deciding test keep their expectations and would fail without the clause.
  - `[false]` `[reject]` Intent: "complete" means two things (bundled totals pass the cap and decide) — FR-31 defines incomplete as "a total with any `unknown` component", AD-3 keeps the total when the fee is bundled, and Story 1.1 persists `cost_complete = true` for it; `total_state` only labels the sub-kind.
  - `[false]` `[reject]` Intent: the deciding Listing and Property total are derived at read time — the criterion places them "when the property projection is serialized" and the story names no new persisted column; AD-12 puts listing selection in the shared serializer and allows read-time aggregation; the persisted `deciding_listing_id` belongs to `property_fit_status` (Story 2.5). Every figure is a stored column value.
  - `[false]` `[reject]` Intent: deciding fields on sale-only Properties, a fallback not constrained to rent, Optional schema fields — AD-12 prescribes "the legacy primary-listing rule otherwise"; there is never more than one, and null only when the Property has no priced Listing.
  - `[false]` `[reject]` Intent: coverage is a sibling block, not a `signals` row, over active Properties, with no UI — `signals` is keyed by `EnrichmentTaskClass` with a Property denominator (contract-locked), so a per-Platform Listing row cannot live there; Story 2.10 states the "same active Properties denominator" for this module; unlike 2.10 this story has no rendering criterion.
  - `[false]` `[reject]` Intent: saved searches, frontend and agent client are not exercised — same refutation as the Blind consumer row: the criterion is scoped to the property listing endpoint.
  - `[low]` `[reject]` Intent: contract loops are vacuous on an empty corpus; behaviour rests on the integration tests — same as the Blind row; the gate runs them unskipped.
  - `[false]` `[reject]` Intent: task checkboxes unticked, `oversized` warning — mid-review state; the warning is informational.

## Design Notes

- **Nested `cost`, not flat keys.** The Listing already exposes a legacy `fees_bundled` read from `raw_json` (true for the QuintoAndar remainder case too) that the current modal renders; the column of the same name means "published combined figure". Nesting keeps both without redefining the legacy key.
- **Selection in the serializer is sanctioned.** AD-12 puts primary-listing selection in the shared serializer; the deciding Listing is the same kind of choice over persisted rows. The SQL sort/cap use the same predicate (active, rent, total not null), so list order and `deciding_listing_id` cannot disagree.
- **`total IS NOT NULL` instead of `cost_complete`.** Story 1.1 guarantees `cost_complete` ⇔ total not NULL; reading one column satisfies "reads `total_monthly_cost` only" literally.
- **Incomplete means a rent Listing without a total.** With `include_incomplete_totals` a sale-only Property stays excluded: a monthly-cost cap has no meaning for it (AD-3: totals exist for rent Listings only).
- **No index.** The correlated subquery rides the existing `property_listings.property_id` index, like `sort_by=price`; an index is unmeasured and would need an operator migration.
- **Deploy dependency.** The projection SELECTs Story 1.1's columns, so the primary must be migrated (1.1's `operator_actions`) before an API image built from this story runs. No new operator step.

## Verification

**Commands:**
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe scripts/agent/validate.py` -- expected: exit 0, `VALIDATION PASSED (tier=backend)`
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe -m pytest src/tests/unit/test_property_projection.py src/tests/unit/test_enrichment_coverage.py src/tests/unit/test_property_export.py -q -o addopts=` -- expected: all pass (development loop only, not validation)

## Auto Run Result

Status: done

**Summary.** The AD-12 serializer now exposes each Listing's stored Total Monthly Cost components under a nested `cost` object with explicit states, and each Property carries one `deciding_listing_id`, its `deciding_rule` and the deciding Listing's stored `total_monthly_cost`. `GET /properties` and `/properties/export` accept `sort_by=total_monthly_cost`, `max_total_monthly_cost` and `include_incomplete_totals`, reading `total_monthly_cost` only. `GET /admin/enrichment/coverage` gains a per-Platform `cost_completeness` block. No migration, no write path, no frontend change.

**Files changed.**
- `src/core/property_projection.py` — cost columns and `id` in `LISTINGS_JSON_AGG`; `listing_cost_view`, `project_listing`, `select_deciding_listing`, wired into both mappers
- `src/api/schemas.py` — `ListingCostModel`, listing `id` / `cost`, deciding fields on both Property models, `CostCompletenessModel`
- `src/api/properties.py` — total-cost sort (NULLS LAST, `p.id` tie-break), cap and incomplete flag on list and export filters
- `src/api/property_export.py` — three deciding columns appended to the CSV
- `src/core/enrichment_coverage.py`, `src/adapters/db/enrichment_coverage_queries.py`, `src/api/admin.py` — per-Platform counts query, pure builder, response block
- `src/tests/unit/test_property_projection.py`, `test_properties_response_schema.py`, `test_property_export.py`, `test_enrichment_coverage.py`, `test_admin_coverage_api.py` — extended
- `src/tests/integration/test_total_monthly_cost_sort_filter.py` (new), `test_enrichment_coverage_sql.py` — seeded Postgres rows
- `src/tests/contract/test_api_contract.py` — new fields, params and coverage block
- `docs/features/v0.14-s1.2-cost-in-the-canonical-projection-and-coverage.md` (new), `docs/api.md`

**Review.** 28 findings from four layers. No intent gap, no spec defect.
- Patched: 6 entries — medium 1 (deterministic tie-break on the total sort; two rows), low 5 (contract helper consistency assertions; sale Listing with a total seeded so the rent clause is executed; CSV export over seeded rows; dead fallback and guard removed from `_stored_total`; stale docstring count).
- Deferred: 0.
- Rejected: 15 `false` and 5 `low`; each row and its reason is in the triage log above.

**Follow-up review: not recommended (false).** Patched counts: high 0, medium 1, low 5.

**Verification.**
- `python scripts/agent/validate.py` on the final tree: `VALIDATION PASSED (tier=backend)` — lint, unit, integration and contract all pass. No stamp was written because the tree was uncommitted at the time; the orchestrator's `[verify]` re-runs the backend tier.
- `alembic check` (informational step, reported FAIL as on main): only the known PostGIS / index drift, no `property_listings` entry.
- Matrix audit: every row has a passing test — listing states and deciding rows in `test_property_projection.py`; cap, flag, sort, inactive Listing and coverage counts against seeded Postgres rows; invalid sort key in unit, integration and contract.

**Residual risks.**
- The projection SELECTs Story 1.1's columns. An API image built from this story fails every Property read on a database without 1.1's migration; 1.1's operator steps already order the migration before any rebuild.
- Until 1.1's cost backfill has run on the primary, every Property reads `lowest-headline-price` and the cap returns nothing.
- Contract tests are shape checks over whatever corpus exists; sort and cap behaviour is proven by the seeded integration tests.
- Saved searches cannot store the cap and the UI does not render cost yet (Stories 1.8–1.10).
