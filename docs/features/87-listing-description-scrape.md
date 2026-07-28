# Listing description scrape/persist — restore corpus bodies (BIN-105)

> Feature branch: `feat/bin-105-listing-description-scrape` · Linear: `BIN-105` · Status: implemented

## Problem

BIN-97 audit found **0%** of active properties had a non-empty `description`. Search
cards omit body text (OLX Flight ads have no `body`; QuintoAndar search cards omit
`description`), and ingest never fetched detail pages for content — only availability
recheck did. Sentiment and embeddings were title-starved.

## Approach

- Pure HTML extractors for QuintoAndar (`houseInfo.remarks` → generated long text →
  legacy `description`) and OLX (`ad.body` from `__NEXT_DATA__` or Flight).
- During `scrape_listings`, when normalized description is empty: reuse DB text if
  present; otherwise `fetch_description(detail_url)` via the platform scraper.
- Exact-match dedupe never blanks a non-empty description with an empty search payload.
- One-shot backfill script for the existing empty corpus (dry-run / `--apply`).

## Changes

Files touched:

```
 src/adapters/scrapers/listing_description.py              | NEW — extractors + URL helper
 src/adapters/scrapers/quintoandar.py                      | fetch_description; remarks in normalize
 src/adapters/scrapers/olx.py                              | fetch_description; strip body
 src/adapters/queue/tasks.py                               | conditional detail enrich before persist
 src/core/dedupe.py                                        | blank-description preserve on update
 scripts/dev/backfill_listing_descriptions.py              | NEW — dry-run / --apply backfill
 src/tests/fixtures/scrapers/quintoandar_detail.html       | houseInfo.remarks + generatedDescription
 src/tests/fixtures/scrapers/olx_detail.html               | NEW — NEXT_DATA ad.body
 src/tests/fixtures/scrapers/olx_detail_flight.html        | NEW — Flight body
 src/tests/unit/test_listing_description.py                | NEW
 src/tests/unit/test_description_enrich.py                 | NEW
 src/tests/unit/test_backfill_listing_descriptions.py      | NEW
 src/tests/unit/test_dedupe_noop.py / test_dedupe_orchestration.py | blank-desc regressions
 src/tests/unit/test_scraper_cassettes.py                  | description asserts
 docs/features/78-pt-corpus-ai-locale-audit.md             | point BUG at BIN-105
 docs/features/87-listing-description-scrape.md            | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Unit / cassette:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Scraper live gate:
   ```bash
   bash scripts/agent/validate-scrapers.sh --require-live
   ```
3. Backfill dry-run against local DB:
   ```bash
   PYTHONPATH=src .venv/bin/python scripts/dev/backfill_listing_descriptions.py --limit 20
   PYTHONPATH=src .venv/bin/python scripts/dev/backfill_listing_descriptions.py --apply --limit 20
   ```

## Notes / Follow-ups

- OLX detail fetch remains subject to Cloudflare 403 without a proxy pool (BIN-47/48).
- QuintoAndar search `shortRentDescription` is intentionally **not** treated as the
  persisted description — detail `remarks` / generated long text is preferred.
- After a large backfill, embeddings catch up via `embed_property` enqueue; optional
  full `POST /admin/embeddings/backfill` if many rows were updated offline.
- Related: BIN-97 audit · BIN-102 semantic search · BIN-104 epic · feature 78.
