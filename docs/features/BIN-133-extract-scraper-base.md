# Extract Shared Scraper Base Logic — deduplicate OLX/QuintoAndar price and neighborhood parsing

> Feature branch: `feat/extract-scraper-base` · Linear: `BIN-133` · Status: implemented

## Problem

`_parse_price_pair` was byte-for-byte identical in `olx.py` and `quintoandar.py`; `_parse_cities`/`_parse_neighborhoods`/`_neighborhoods_for_path`/`_neighborhoods_for_city` followed the same structure with only superficial per-platform differences, none of it lifted into `BaseScraper` or a shared module. This had already drifted once: OLX's `_parse_neighborhoods` returned `list[dict]`, QuintoAndar's returned `list[str]`, for what is conceptually the same operation — meaning a bug fix to price-pair parsing or neighborhood-slug handling had to be manually applied twice, with no guarantee both copies stayed in sync.

## Approach

- Extract `_parse_price_pair` and the neighborhood/city parsing helpers into a new `src/adapters/scrapers/common.py`, shared by both scraper classes.
- Resolve the `list[dict]` vs `list[str]` neighborhood-return inconsistency to one shape.
- No behavior change: existing scraper cassette tests (`test_scraper_cassettes.py`, `test_quintoandar.py`) serve as the characterization lock, proving the extraction didn't alter parsing behavior.

## Changes

Files touched:

```
src/adapters/scrapers/common.py      | NEW — shared price-pair/neighborhood/city parsing helpers
src/adapters/scrapers/olx.py         | now delegates to common.py instead of duplicating parsing logic
src/adapters/scrapers/quintoandar.py | now delegates to common.py instead of duplicating parsing logic
src/tests/unit/test_quintoandar.py   | updated for the unified neighborhood-return shape
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
bash scripts/agent/validate-scrapers.sh --require-live
```

Existing cassette-based unit tests (`test_scraper_cassettes.py`) lock parsing behavior; no new live probes were needed since this is a pure refactor.

## Notes / Follow-ups

- This was tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone), finding #6 from the 2026-07-29 audit.
- Epic parent: BIN-128.
- Any future third scraper platform should build directly on `scrapers/common.py` rather than re-copying OLX/QuintoAndar's parsing logic a third time.
