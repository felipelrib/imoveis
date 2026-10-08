---
title: 'Story 1.1 — Total Monthly Cost on the persist path'
type: 'feature'
created: '2026-10-08'
status: done
baseline_revision: '10242503c5e0af36eeb7143ccd8939c2123a8a92'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A QuintoAndar sale payload that carries condo fee or IPTU but no totalCost makes the legacy
      normalizer emit a phantom rent Listing priced at condo + IPTU, and that figure becomes the
      Property price.
    evidence: |-
      Pre-existing in QuintoAndarScraper._prices_and_fees: rent = partial + (condo or 0) + (iptu or 0)
      when totalCost is absent, so rentPrice 0 + condoFee 600 + iptu 150 yields rent 750 > 0.
      Reproduced in this run: normalize() of {rentPrice: 0, salePrice: 450000, condoFee: 600, iptu: 150}
      returns listings [('rent', 750.0), ('sale', 450000.0)] and price 750.0.
      Not verified: whether live QuintoAndar sale payloads have this shape (the rent search probe
      always carried totalCost). A probe of the sale search would settle it.
    location: >-
      src/adapters/scrapers/quintoandar.py:421
    severity: medium (unverified)
operator_actions:
  - "Wait for the orchestrator to merge this story into main, then from the primary checkout in Git Bash run: bash scripts/agent/migrate-primary.sh (expect alembic_version c4d5e6f7a8b9; it refuses while a cloud backfill runner is alive - wait, never delete the Redis keys). Do this BEFORE rebuilding any container: the new code INSERTs the new columns."
  - "Rebuild and restart the primary stack so the API and workers run the merged code: ./scripts/restart.sh --build"
  - "Populate the stored Listings: docker compose --env-file .env.local exec worker_scraper celery -A adapters.queue.tasks call tasks.backfill_listing_costs ; then read the result with: docker compose --env-file .env.local logs --since 30m worker_scraper | grep listing_cost_backfill (expect listing_cost_backfill_complete; a second run must report updated=0)."
  - "Run the step 4 query in docs/features/v0.14-s1.1-total-monthly-cost-on-the-persist-path.md against the primary (read-only) and record the per-platform complete / bundled / incomplete / rent_unknown / iptu_ambiguous counts in that doc."
  - "Confirm or override the two product calls made in this story: IPTU periodicity is inferred by magnitude (monthly at <= 15% of rent, annual at >= 40%, unknown between; for sale 0.10% / 0.25% of price), and a published zero is treated as unknown. To change either, edit the constants in src/core/listing_cost.py and re-run the backfill."
---

<intent-contract>

## Intent

**Problem:** A Listing's `price` means different things per platform (QuintoAndar and OLX fold condo + IPTU into it, ZapImóveis does not), OLX sums a missing fee as zero, and Zap IPTU is stored as published although it is often annual. Nothing comparable exists for the `aluguel-2027` total-cost cap (FR-31).

**Approach:** Add typed cost columns to `property_listings`, computed by one pure `src/core/` rule module and written only by the persist path (`core/dedupe.py`). Scrapers stamp the platform's raw cost figures into the listing's stored `raw_json`; the same mapping is re-run over stored rows by a `scrapers`-queue task to populate Listings already in the DB.

## Boundaries & Constraints

**Always:**
- Columns (AD-3): `rent_monthly`, `condo_fee_monthly`, `iptu_monthly`, `iptu_periodicity_source` ∈ {`monthly`,`annual`,`unknown`}, `fees_bundled`, `total_monthly_cost`, `cost_complete`, plus `updated_at` (AD-19) that moves only when a cost column or `active` changes.
- A missing, zero or negative published component is `unknown` (NULL), never 0. `total_monthly_cost` is NULL and `cost_complete` false whenever a component is unknown and not bundled. `cost_complete` ⇔ total is not NULL.
- `rent_monthly` is the platform's unbundled rent: QuintoAndar `rentPrice`, OLX `rent_base`, ZapImóveis rental `value`. Total = `rent_monthly + condo_fee_monthly + iptu_monthly` only.
- Bundled (QuintoAndar `condoIptu` with no separate fees): combined figure in `condo_fee_monthly`, `iptu_monthly` NULL, `fees_bundled` true, total = rent + combined, complete.
- IPTU periodicity: declared by the platform when it itemizes monthly (QuintoAndar); otherwise classified by magnitude against the Listing's own reference (rent for rent, sale price for sale) with an ambiguity band that yields `unknown` and no division. Annual is ÷12, rounded to cents.
- Sale Listings: condo and IPTU under the same rules; `rent_monthly`, total NULL; `cost_complete` false.
- The rule module imports nothing from `adapters`, `api` or `infra` (AD-1), and is built test-first.
- `property_listings` cost columns are written only in `core/dedupe.py`.

**Never:**
- Change legacy `price`, `base_price`, `condo_fee`, `iptu` values or their semantics, or the `raw_json.fees_bundled` key the projection reads.
- Derive a fee from QuintoAndar `totalCost − rentPrice` for the new columns (the live payload shows it includes other charges).
- Touch `src/api/`, `scoring.py`, the frontend, `sprint-status.yaml`, or the primary stack. No API exposure (Story 1.2), no cohort basis change (Story 1.3).
- Impute, default or estimate a component.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| QA itemized | rent 750, condoFee 120, iptu 59 | 750 / 120 / 59, `monthly`, total 929, complete | No error expected |
| QA bundled | rent 800, condoIptu 57, totalCost 857 | condo 57, iptu NULL, bundled, total 857, complete | No error expected |
| QA remainder only | rent 780, condoIptu 0, totalCost 815 | condo NULL, iptu NULL, not bundled, total NULL, incomplete | No error expected |
| OLX missing fee | rent 3500, Condomínio 650, no IPTU (or `R$ 0`) | iptu NULL `unknown`, total NULL, incomplete; legacy `price` still 4150 | No error expected |
| Zap annual IPTU | rent 4700, condo 480, iptu 4940 | `annual`, iptu 411.67, total 5591.67, complete | No error expected |
| Zap monthly IPTU | rent 3500, condo 400, iptu 273 | `monthly`, total 4173, complete | No error expected |
| Ambiguous IPTU | rent 4000, iptu 1000 (25% of rent) | `unknown`, iptu NULL, not divided, total NULL | No error expected |
| Sale Listing | sale 450000, condo 600, iptu 1857 | rent NULL, condo 600, `annual` 154.75, total NULL, incomplete | No error expected |
| Rent unknown | rent Listing, rent missing or ≤ 0 | rent NULL, periodicity `unknown` unless declared, total NULL | No error expected |
| Stored row, no stamp | pre-story row (no `raw_json.cost_source`) | same columns as a fresh scrape of the same figures | Malformed `raw_json` treated as `{}` |

</intent-contract>

## Code Map

- `src/core/listing_cost.py` -- NEW pure rules: `compute_listing_cost(...)`, `listing_cost_columns(listing)` (reads `raw_json.cost_source`, else rebuilds the same inputs from stored legacy fields), `COST_COLUMNS`. Convention exemplar: `src/core/listing_type.py`.
- `src/core/dedupe.py:479-589` `_upsert_listings` -- sole writer of listing content, raw `text()` SQL in an UPDATE (`:515`) and an INSERT (`:552`) branch; the existence SELECT at `:493` returns `id, price`. `_is_unchanged` (`:263`) skips listing writes for unchanged Properties and must stay as is.
- `src/adapters/db/models.py:211-247` `PropertyListing` -- no `updated_at` today; ORM `onupdate` never fires for raw SQL, so `updated_at` is set explicitly.
- `alembic/versions/b7c8d9e0f1a2_add_listing_base_price.py` -- style reference; head is `f3a7c81d5e42`. Version files never import from `src/`.
- `src/adapters/scrapers/quintoandar.py:447-517` -- `_listings` builds `raw_json` (`partial_price`, `fees_bundled`, `fees_note`); `_extract_fees` gives separate vs `condoIptu`; `_prices_and_fees:429` derives the `totalCost − rentPrice` remainder (legacy only).
- `src/adapters/scrapers/olx.py:493-531` -- `rent_base`, labelled `condo_fee` / `iptu` props (`R$ 0` parses to `0.0`), zero-coerced `rent_total`.
- `src/adapters/scrapers/zapimoveis.py:638-650,806-846` -- `prices.<side>.{value,condominium,iptu}`; `period` describes the rent, not the IPTU.
- `src/adapters/queue/tasks.py:1541-1571` -- thin task wrapper pattern; `src/adapters/queue/celery_app.py:223-238` `task_routes`.
- `src/tests/unit/test_listings.py:20-70` -- hand-copied SQLite DDL for `property_listings`; must gain the new columns. Existing tests here plus `src/tests/integration/test_listings_e2e.py` are the characterization lock for `_upsert_listings` and stay green unchanged.
- `src/tests/unit/test_schedule.py:227-238,273-284` -- hard-coded route lists.
- `scripts/agent/validate.py:463,475,491-504` -- `alembic upgrade head` gates; `alembic check` is informational (read its output); `src/adapters/scrapers/` triggers the cassette suite and live dry-run.
- Live probe 2026-10-08 (read-only): Zap publishes no IPTU periodicity; 60 BH listings split cleanly into 3–14% of rent (monthly) and 51–105% (annual); sale 0.01–0.06% vs 0.33–0.41% of price. QuintoAndar search rows carry `rentPrice`, `totalCost`, `condoIptu` and `totalCost − rentPrice` exceeds `condoIptu` by ~35.

## Tasks & Acceptance

**Execution:**
- [x] `src/tests/unit/test_listing_cost.py` -- write first: the matrix above, threshold boundaries, rounding, declared vs inferred periodicity, legacy-row reconstruction per platform, and an AST check that `core/listing_cost.py` imports no `adapters` / `api` / `infra` -- TDD for core rules (AD-1)
- [x] `src/core/listing_cost.py` -- implement the rules to make those tests pass -- one definition of the cost mapping
- [x] `alembic/versions/c4d5e6f7a8b9_listing_total_monthly_cost.py` -- add the seven cost columns (`Float` money, `Boolean NOT NULL DEFAULT false`, `String NOT NULL DEFAULT 'unknown'` with a CHECK on the three values) and `updated_at NOT NULL DEFAULT now()`; reversible downgrade -- schema
- [x] `src/adapters/db/models.py` -- mirror the columns and CHECK on `PropertyListing` -- keep `alembic check` free of new drift
- [x] `src/core/dedupe.py` -- `_upsert_listings` writes the cost columns from `listing_cost_columns` in both branches and sets `updated_at` on insert and when a cost column or `active` changes; add `repopulate_listing_costs(session, after_id, batch_size)` (one keyset batch, updates only rows whose columns differ) -- single write authority
- [x] `src/adapters/scrapers/quintoandar.py`, `olx.py`, `zapimoveis.py` -- stamp `raw_json["cost_source"]` = `{rent, condo_fee, iptu, fees_combined, iptu_periodicity}` from the raw payload; legacy keys untouched -- provenance for the mapping
- [x] `src/adapters/queue/tasks.py`, `src/adapters/queue/celery_app.py` -- `tasks.backfill_listing_costs` on `scrapers`: loop batches, commit per batch, return counts -- populate existing rows
- [x] `src/tests/fixtures/cost/labelled_listings.json`, `src/tests/unit/test_listing_cost_fixtures.py` -- labelled raw payloads for the three platforms run through the real `normalize()`: same home on two and three platforms, a published component difference, OLX zero-for-missing-fee regression, Zap annual-IPTU regression, fresh-vs-stored equivalence -- AC 4
- [x] `src/tests/unit/test_listings.py`, `src/tests/unit/test_schedule.py`, `src/tests/unit/test_backfill_listing_costs_task.py`, `src/tests/integration/test_listings_e2e.py`, scraper unit tests as needed -- DDL, persist + `updated_at` behaviour, repopulate batch, route, task happy + error path, one Postgres round trip through the migration
- [x] `docs/features/v0.14-s1.1-total-monthly-cost-on-the-persist-path.md`, `docs/data-models-api.md` -- feature doc (all template sections, rules, thresholds with the probe evidence, operator steps) and the table row

**Acceptance Criteria:**
- Given the migration is applied to a database at `f3a7c81d5e42`, when `alembic upgrade head` then `alembic downgrade -1` run, then both succeed and `alembic check` reports no difference on `property_listings`.
- Given a Property rescraped with identical cost figures, when it is persisted again, then its Listing's `updated_at` is unchanged; when a component changes, then `updated_at` advances.
- Given the same home published on two platforms with identical components, when both are normalized, then their totals are equal and each equals rent + condo + monthly IPTU with rent counted once; given one differing component, then the totals differ by exactly that amount.
- Given Listings persisted before this story, when `tasks.backfill_listing_costs` runs, then every row carries the columns a fresh scrape of the same figures would produce, a second run updates zero rows, and legacy `price` / `base_price` / `condo_fee` / `iptu` are byte-identical.
- Given the story is code-complete, when the session ends, then the spec is `awaiting-operator` with `operator_actions` covering the primary migration, the worker rebuild and the backfill run.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 39 findings — high 0, medium 8, low 20, false 10, maybe-false 1
- findings:
  - `[medium]` `[reject]` Blind: a low annual IPTU (under 15% of rent) is classified monthly and marked complete; Zap-derived thresholds also applied to OLX and sale — real limit of the magnitude rule, but the rule is the intent contract's (fix would edit the spec). Recorded as a residual risk in the feature doc and as an operator decision in `operator_actions`.
  - `[false]` `[reject]` Blind: `iptu_periodicity_source` does not say declared vs inferred — the stamp does: `raw_json.cost_source.iptu_periodicity` is the declared value and `null` when inferred; the column vocabulary is fixed by AD-3.
  - `[low]` `[reject]` Blind: declared periodicity bypasses magnitude and the QuintoAndar declaration is unevidenced — the detail cassette itemizes 750 + 120 + 59 = `totalCost` 929, i.e. QuintoAndar IPTU is a monthly figure; a platform declaration is the stronger source, and a guard would add a branch for a state never observed.
  - `[medium]` `[patch]` Blind: the backfill can overwrite a concurrent scrape's fresh columns (batch read, then UPDATE by id) — `repopulate_listing_costs` now appends `FOR UPDATE` to the batch SELECT on PostgreSQL, held until the per-batch commit.
  - `[low]` `[reject]` Blind: dead retry config, no per-row isolation, no resume cursor or traceback in the backfill task — the decorator mirrors the file's thin-task idiom and harms nothing; a rerun is idempotent and scans fast, so a resume cursor is not worth a parameter. (The `OverflowError` sub-claim is patched under the edge-case row.)
  - `[low]` `[patch]` Blind: the migration round-trip test skips itself once a later migration owns the head — now downgrades to the explicit revision `f3a7c81d5e42` and upgrades to head, no head check.
  - `[low]` `[patch]` Blind: AC 1 "`alembic check` reports no difference" not machine-verified — added `test_model_matches_the_migrated_schema` (`compare_metadata` filtered to `property_listings`).
  - `[low]` `[reject]` Blind: invariants only in Python, no CHECK tying `cost_complete` to the total, no indexes — one writer computes both from one function; indexes belong to the stories that sort/filter (1.2) and sweep (Epic 2), unmeasured today.
  - `[medium]` `[patch]` Blind: `updated_at` does not move when `availability.py` deactivates a Listing — the deactivation UPDATE now sets `updated_at`; pinned in `test_availability.py`.
  - `[false]` `[reject]` Blind: spec still `in-review` with unticked tasks and no `operator_actions` — that was the mid-review state; finalization writes them.
  - `[low]` `[patch]` Blind: operator steps incomplete (bare `docker compose exec`, no way to read the task result, no rollback or heartbeat note, spot-check cannot answer SM-3) — feature doc operator section rewritten.
  - `[false]` `[reject]` Blind: legacy-untouched asserted weakly by the fixture test — the pre-existing scraper suites (`test_olx.py`, `test_zapimoveis.py`, `test_scoring_and_fees.py`, `test_scraper_cassettes.py`, `test_quintoandar.py`) pin `price` / `base_price` / `condo_fee` / `iptu` / `fees_bundled` and pass unmodified in this diff.
  - `[low]` `[patch]` Blind: fixture holes (no OLX sale, no QuintoAndar sale) — added `olx-sale` and `quintoandar-sale` labelled cases.
  - `[low]` `[reject]` Blind: `condoFee` + `condoIptu` without `iptu` comes out incomplete although rent + `condoIptu` is published — outcome is conservative, never wrong; honouring it adds a branch and breaks fresh == stored (legacy rows did not keep `condoIptu`).
  - `[low]` `[reject]` Blind: column lists and periodicity literals duplicated — seven AD-3 columns fixed by the architecture; `test_result_carries_exactly_the_cost_columns` plus the persist tests fail on a missed column; a generic refactor is not a direct correction.
  - `[low]` `[patch]` Blind: permanently-incomplete populations unmeasured (OLX rows without `base_price`, QuintoAndar rows without `partial_price`, homes with no condo fee) — documented in Notes and counted by the new step 4 query (`rent_unknown`).
  - `[low]` `[patch]` Blind: a constants-restating test and a stale `validate.sh backend` in a touched doc line — removed `test_thresholds_are_the_documented_constants` (the boundary tests pin the thresholds behaviourally); doc line now names `scripts/agent/validate.py --tier backend`. The column-contract test stays: Story 1.2 consumes those names.
  - `[false]` `[reject]` Edge: a Zap fee-only rescrape is a noop — `_is_unchanged` compares `props_json`, which carries `condo_fee` / `iptu` on Zap, so the write happens; proven by the new `TestRealNormalizeRescrape`.
  - `[medium]` `[patch]` Edge: backfill vs concurrent scrape — same defect as the Blind row; fixed by the row lock.
  - `[low]` `[reject]` Edge: a finite figure of ~1e27 breaks `quantize` — no platform publishes such a value; a magnitude cap is a guard for an undemonstrated state.
  - `[low]` `[patch]` Edge: `float()` on an int too large for a float raised `OverflowError` outside the `try` — `_number` now parses inside one `try` (`ArithmeticError`), returning `None`; `10**400` added to the unparseable cases.
  - `[low]` `[reject]` Edge: no upper bound on the annual band — a garbage figure in is a garbage total out; a ceiling would be a third threshold with no measured basis.
  - `[low]` `[reject]` Edge: `batch_size` arriving as a string from `celery call` — the documented command passes none; operator misuse fails loudly before any write.
  - `[low]` `[patch]` Edge (claim, AC 4): legacy OLX rows without `base_price` stay `rent_monthly NULL` after the backfill — true and honest (nothing is rebuilt from the summed headline); documented and measured, same patch as the Blind row.
  - `[false]` `[reject]` Edge (claim, AC 2): `updated_at` does not advance on a Zap fee-only change — refuted as above; now pinned.
  - `[medium]` `[patch]` Gap: a fee-only change reaches the cost columns only through `props_json` mirroring, unpinned — added `TestRealNormalizeRescrape.test_fee_only_change_updates_cost_and_updated_at` (real Zap `normalize()` twice through `match_or_create_property`, only `condominium` differs: noop when equal, `updated`, new total and `updated_at` when not).
  - `[medium]` `[patch]` Gap: model/migration parity checked only by a non-gating step — same patch as the Blind row (`compare_metadata`).
  - `[low]` `[patch]` Gap (other): migration test goes permanently skipped — same patch as the Blind row.
  - `[low]` `[patch]` Gap (other): no QuintoAndar / OLX sale through the real `normalize()` — same patch as the Blind row.
  - `[false]` `[reject]` Intent: handoff lives in doc prose, not in spec frontmatter — mid-review state; `operator_actions` and `awaiting-operator` are written at finalization.
  - `[false]` `[reject]` Intent: nothing observes the primary corpus — by rule; the primary is operator-owned, which is why the story ends `awaiting-operator`.
  - `[low]` `[patch]` Intent: no QuintoAndar or OLX payload goes through `normalize()` into a stored row — added `TestLabelledFixturesPersist`: every labelled case is normalized, written by `_upsert_listings` and compared with its label.
  - `[maybe-false]` `[reject]` Intent: the Celery task is never run against a database — the task is thin glue (mock-tested loop/commit/rollback) over `repopulate_listing_costs`, which runs on SQLite and Postgres with multi-batch keysets; a live `celery call` needs the worker stack and is operator step 3. If it were wrong it would be `low` (a wiring error the first run exposes).
  - `[false]` `[reject]` Intent: unchanged rows are not populated by the scrape path — by design and stated; the backfill covers them.
  - `[medium]` `[patch]` Intent: `updated_at` on deactivation — same patch as the Blind row.
  - `[low]` `[patch]` Intent: `alembic check` is a manual read — same patch as the Blind row.
  - `[medium]` `[reject]` Intent: periodicity is inferred, not recorded from a source; OLX rests on Zap-derived thresholds — same root as the first Blind row; the intent contract's rule, surfaced to the operator.
  - `[false]` `[reject]` Intent: no cassette changes and no run evidence in the diff — the scrapers gate ran on the final tree: 145 cassette/unit tests and the live dry-run passed.
  - `[false]` `[reject]` Intent: `epic-1-context.md` rewritten wholesale — required by the workflow: the cached context was the v0.13 epic and older than the planning artifacts.

## Design Notes

- **Why magnitude classifies periodicity.** The story requires annual IPTU to be converted and ambiguous IPTU left `unknown`, but no platform labels it (probed live). Thresholds are named constants in the core module: rent — monthly at ≤ 15% of rent, annual at ≥ 40%; sale — monthly at ≤ 0.10% of price, annual at ≥ 0.25%. The gap between the observed clusters is the ambiguity band. An operator override would be a one-line constant change.
- **Zero is unknown.** Platforms and advertisers emit 0 for "not filled"; a house with genuinely no condo fee is indistinguishable, so it stays incomplete and later reads as pending verification rather than as a false total.
- **Stamp plus fallback.** New scrapes carry `raw_json.cost_source`, so the mapping never reads headline columns. Rows stored before this story have only legacy fields; the fallback rebuilds the identical inputs (QuintoAndar `raw_json.partial_price` and the `fees_note` that marks a derived remainder; OLX `base_price`; Zap `price`), and a test pins fresh == stored.
- **Deploy order matters.** New code INSERTs the new columns, so the primary must be migrated before workers are rebuilt.

## Verification

**Commands:**
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe scripts/agent/validate.py` -- expected: exit 0, `VALIDATION PASSED (tier=backend)` with the scrapers gate (cassettes + live dry-run) run
- `C:/Workfolder/imoveis/.venv/Scripts/python.exe -m pytest src/tests/unit/test_listing_cost.py src/tests/unit/test_listing_cost_fixtures.py src/tests/unit/test_listings.py -q -o addopts=` -- expected: all pass (development loop only, not validation)

**Manual checks (if no CLI):**
- Read the `contract: alembic check` output in the gate log: no `property_listings` entry among the reported differences.

## Auto Run Result

Status: awaiting-operator

**Summary.** `property_listings` gains the Total Monthly Cost columns (`rent_monthly`, `condo_fee_monthly`, `iptu_monthly`, `iptu_periodicity_source`, `fees_bundled`, `total_monthly_cost`, `cost_complete`) and `updated_at`. One pure module, `src/core/listing_cost.py`, holds the rules; `core/dedupe.py` is the only writer. The three scrapers stamp the platform's raw figures in `raw_json.cost_source`; `tasks.backfill_listing_costs` (queue `scrapers`) re-runs the same mapping over stored rows. Legacy `price` / `base_price` / `condo_fee` / `iptu` are unchanged. Everything an agent can do is committed; applying it to the primary is owed by the operator (see `operator_actions`).

**Files changed.**
- `src/core/listing_cost.py` — new: cost rules, thresholds, stamp builder, stored-row fallback
- `src/core/dedupe.py` — `_upsert_listings` writes cost columns and `updated_at`; new `repopulate_listing_costs` (keyset batch, row-locked on Postgres)
- `alembic/versions/c4d5e6f7a8b9_listing_total_monthly_cost.py` — new migration (reversible)
- `src/adapters/db/models.py` — columns and CHECK on `PropertyListing`
- `src/adapters/scrapers/quintoandar.py`, `olx.py`, `zapimoveis.py` — stamp `raw_json.cost_source`
- `src/adapters/scrapers/availability.py` — deactivation moves `updated_at`
- `src/adapters/queue/tasks.py`, `celery_app.py` — `tasks.backfill_listing_costs` and its route
- `src/tests/unit/test_listing_cost.py`, `test_listing_cost_fixtures.py`, `test_backfill_listing_costs_task.py`, `src/tests/fixtures/cost/labelled_listings.json` — new tests and 14 labelled payloads
- `src/tests/unit/test_listings.py`, `test_schedule.py`, `test_availability.py`, `src/tests/integration/test_listings_e2e.py` — extended
- `docs/features/v0.14-s1.1-total-monthly-cost-on-the-persist-path.md`, `docs/data-models-api.md` — feature doc and table row
- `_bmad-output/implementation-artifacts/epic-1-context.md` — recompiled for the v0.14 epic (the cached one was the v0.13 epic)

**Review.** 39 findings from four layers. No intent gap, no spec defect.
- Patched (9 entries; grouped rows share an entry): medium 3 — backfill/scrape race (row lock), `updated_at` on deactivation, fee-only rescrape pinned on the real path; low 6 — model/migration parity test, migration round trip on explicit revisions, `OverflowError` in `_number`, sale fixtures plus persist-every-label test, operator steps and incomplete-population notes, tautological test and stale doc line.
- Deferred (1): QuintoAndar phantom rent Listing for sale payloads with fees and no `totalCost` (pre-existing, unverified on live data).
- Rejected: every rejected row and its reason is in the triage log above (10 `false`, 1 `maybe-false`, the rest `low`/`medium` whose fix would edit the intent contract or add guards for undemonstrated states).

**Follow-up review: recommended (true).** Three `medium` entries were patched after the review layers ran, so two behaviour changes are unreviewed: the `FOR UPDATE` batch lock in `repopulate_listing_costs` (lock scope against concurrent scrape upserts on a ~200k-row table has only been exercised single-session on the test Postgres), and the `updated_at` write in `deactivate_listing_and_maybe_property`.

**Verification.**
- `python scripts/agent/validate.py` on the final tree: `VALIDATION PASSED (tier=backend)` — lint OK; unit 2192 passed, 1 skipped; integration 127 passed; contract 51 passed; scrapers cassette/unit 145 passed; live dry-run OK (QuintoAndar and ZapImóveis). The first run after patching failed on isort only (import order in the integration test, auto-fixed); the rerun passed. No stamp: the run was on an uncommitted tree; the orchestrator's `[verify]` re-runs the backend tier.
- `alembic check` (informational): only the known PostGIS/index drift, no `property_listings` entry; now also asserted by `test_model_matches_the_migrated_schema`.
- Matrix audit: all ten rows have a passing test (`TestMatrix`, `TestLegacyReconstruction`, labelled fixtures).
- Read-only live probe (2026-10-08) of ZapImóveis and QuintoAndar search payloads grounded the rules.

**Residual risks.**
- IPTU periodicity is inferred by magnitude because no platform labels it. A small annual IPTU reads as monthly and overstates the total. Thresholds come from 60 ZapImóveis listings and are applied to OLX and sale too.
- A published zero is unknown, so a home with genuinely no condo fee never gets a complete total.
- Stored rows without an unbundled rent (old OLX rows without `base_price`) stay incomplete until the Property changes; the size of that population is unknown until the operator runs the step 4 query.
- Until the operator migrates, rebuilds and runs the backfill, the primary has no cost data. Rebuilding before migrating would break every scrape persist.
- Stories 1.2 and 1.3 depend on these columns existing on the primary; `awaiting-operator` is not machine-enforced as a gate.

## Operator Confirmation

Confirmed 2026-10-08: the external actions this story owed were carried out.

- Wait for the orchestrator to merge this story into main, then from the primary checkout in Git Bash run: bash scripts/agent/migrate-primary.sh (expect alembic_version c4d5e6f7a8b9; it refuses while a cloud backfill runner is alive - wait, never delete the Redis keys). Do this BEFORE rebuilding any container: the new code INSERTs the new columns.
- Rebuild and restart the primary stack so the API and workers run the merged code: ./scripts/restart.sh --build
- Populate the stored Listings: docker compose --env-file .env.local exec worker_scraper celery -A adapters.queue.tasks call tasks.backfill_listing_costs ; then read the result with: docker compose --env-file .env.local logs --since 30m worker_scraper | grep listing_cost_backfill (expect listing_cost_backfill_complete; a second run must report updated=0).
- Run the step 4 query in docs/features/v0.14-s1.1-total-monthly-cost-on-the-persist-path.md against the primary (read-only) and record the per-platform complete / bundled / incomplete / rent_unknown / iptu_ambiguous counts in that doc.
- Confirm or override the two product calls made in this story: IPTU periodicity is inferred by magnitude (monthly at <= 15% of rent, annual at >= 40%, unknown between; for sale 0.10% / 0.25% of price), and a published zero is treated as unknown. To change either, edit the constants in src/core/listing_cost.py and re-run the backfill.

_Appended by the bmad-loop orchestrator (`bmad-loop confirm`, #335): a human confirmed these external actions out of band, and the story was advanced from `awaiting-operator` to `done`._
