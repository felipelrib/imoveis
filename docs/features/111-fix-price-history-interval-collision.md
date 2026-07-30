# Fix price-history interval collision when multiple listings share property_id/listing_type/platform

> Feature branch: `fix/price-history-interval-collision` · Linear: `BIN-145` · Status: implemented

## Problem

`_record_price_change` (`src/core/dedupe.py`) finds "the" open price-history interval to close/extend via `WHERE property_id AND listing_type AND platform` — it did not scope by `property_listing_id`. `PropertyListing`'s unique constraint is `(platform, platform_listing_id, listing_type)`, not `property_id`, so nothing prevented two distinct ads (two brokers re-listing the same unit, or a relisted ad with a new `platform_listing_id`) from attaching to one property under the same `(platform, listing_type)` via the fuzzy matcher (`dedupe.py:173-187`).

Once two listings shared a property under the same platform+type, processing listing B's price could close/rewrite listing A's open interval as if it were a real price change on the same ad — firing false watchlist "price drop" alerts and corrupting the timeline shown via `GET /properties/{id}/price-history` (`src/api/properties.py`), which had the same scoping gap: it returned the merged history of every listing under a property/listing_type/platform scope, indistinguishable from one listing's own timeline.

## Approach

- Added `property_listing_id` to the open-interval identity key in `_record_price_change`'s `SELECT ... WHERE ... AND end_ts IS NULL` query, using `IS NOT DISTINCT FROM` (same null-safe pattern already used for `platform`, since `property_listing_id` is a nullable FK). The `INSERT`/`UPDATE` paths already carried `property_listing_id` correctly — only the *lookup* was under-scoped.
- Verified both real call sites (`dedupe.py` lines ~517 and ~557) already pass `property_listing_id` on every price-recording call for actual listings, so the fix activates correctly with no caller changes needed. The one call site that doesn't pass it (`_record_candidate_listings`'s dead-code fallback at `dedupe.py:95`, hit only when `candidate.listings` is empty — never true for the 3 current scrapers) is explicitly out of scope per the ticket and was left untouched.
- Added an optional `property_listing_id` query parameter to `GET /properties/{id}/price-history` (`src/api/properties.py`), symmetric with the existing `listing_type`/`platform` filters, so callers can scope to one listing's own timeline instead of the merged view across all listings sharing that property/type/platform. Documented the merged-vs-scoped distinction in the endpoint docstring.
- Testing discipline (brownfield dedupe invariant, characterization + new-behavior assert per project convention): added `test_distinct_listings_same_platform_and_type_independent` alongside the existing `test_per_platform_independence`/`test_rent_and_sale_independent_noop` tests in `test_dedupe.py`. Verified the test fails without the fix (`git stash` the `dedupe.py` change, confirmed `AssertionError` on the missing `property_listing_id IS NOT DISTINCT FROM :plid` clause) and passes with it.

## Changes

Files touched:

```
src/core/dedupe.py            | _record_price_change: added property_listing_id to open-interval SELECT WHERE clause (IS NOT DISTINCT FROM, null-safe); expanded docstring
src/api/properties.py         | get_price_history: added optional property_listing_id query filter; docstring notes the merged-vs-scoped timeline distinction (BIN-145)
src/tests/unit/test_dedupe.py | NEW test_distinct_listings_same_platform_and_type_independent — regression for two listings sharing property_id/listing_type/platform but different property_listing_id
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted:

```bash
PYTHONPATH=src .venv/bin/python -m pytest src/tests/unit/test_dedupe.py -v -k "distinct_listings or per_platform or rent_and_sale"
```

To confirm the regression test actually catches the bug:

```bash
git stash push -- src/core/dedupe.py
PYTHONPATH=src .venv/bin/python -m pytest src/tests/unit/test_dedupe.py -v -k distinct_listings   # should FAIL
git stash pop
```

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- Out of scope (explicitly, per ticket): `dedupe.py`'s hardcoded `listing_type="sale"` fallback default at the `_record_candidate_listings` dead-code path (only reached when `candidate.listings` is empty, which none of the 3 current scrapers ever produce). Left untouched.
- BIN-146 (tighten fuzzy dedup matching to prevent merging distinct units in the same building) was deliberately blocked on this ticket merging first, since both touch `src/core/dedupe.py`'s fuzzy-matching region (~lines 173-187) and adjacent code — this PR does not modify that region, so BIN-146 can proceed cleanly.
