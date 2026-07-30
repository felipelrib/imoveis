# Listing availability recheck — soft-deactivate unavailable source URLs

> Feature branch: `feat/listing-availability-recheck` · Linear: `BIN-80` · Status: implemented

## Problem

Scraped QuintoAndar and OLX listings stay on the Properties page after the source
takes them down. Users open dead links; deal browsing is polluted. We still want
the rows (and price history) for offline stats — just not in the live feed.

## Approach

- Soft-deactivate only: `property_listings.active = false`; never delete rows.
- Listing-level: rent can die while sale stays live on the same property.
- Property `active = false` only when zero active listings remain.
- Celery beat `tasks.recheck_listing_availability` on the `scrapers` queue.
- Detection: QuintoAndar `__NEXT_DATA__` listing `status` (e.g. `despublicado`);
  OLX HTTP 410 / “Anúncio não encontrado” / homepage redirect. Cloudflare 403 →
  `unknown` (no deactivate).
- API listing JSON and max-price `EXISTS` filter require `pl.active = true`.

## Changes

Files touched:

```
 configs/app_config.yaml                      | availability_recheck knobs
 src/infra/config.py                          | AvailabilityRecheckConfig
 src/adapters/scrapers/availability.py        | NEW — classifiers + deactivate helper
 src/adapters/queue/tasks.py                  | recheck_listing_availability task
 src/adapters/queue/celery_app.py             | beat entry + scrapers route
 src/api/property_projection.py               | listings agg filters active
 src/api/properties.py                        | max_price EXISTS filters active
 src/api/admin.py                             | POST /admin/availability/recheck
 src/tests/fixtures/scrapers/*.html           | QA/OLX unavailable fixtures
 src/tests/unit/test_availability.py          | NEW — detector + deactivate tests
 src/tests/unit/test_schedule.py              | beat + route assertions
 src/tests/unit/test_config.py                | real YAML leaves
 src/tests/unit/test_property_projection.py   | active listing SQL lock
 docs/features/BIN-80-listing-availability-recheck.md | this doc
```

## New Dependencies

None.

## How to Test

1. Unit detectors:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Manual enqueue (API key required):
   ```bash
   curl -X POST -H "X-API-Key: $API_KEY" \
     http://localhost:8000/admin/availability/recheck?batch_size=20
   ```
3. Confirm Properties cards omit deactivated listing links; dual-listed houses keep
   the live listing type only.

## Notes / Follow-ups

- Maps PRD debt “Dead listing URL pruning”.
- Scraper Control UI button for recheck: shipped in BIN-123 / feature 93.
- Rebuild `beat` + `worker_scraper` after merge so the new route/schedule load.
- Example QA unavailable: house `894638432` rent `despublicado` while sale stayed
  `publicado` at probe time.
- Example OLX unavailable: `https://www.olx.com.br/vi/1000000000` → HTTP 410,
  title “Anúncio não encontrado | OLX”.
