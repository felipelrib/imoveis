# City filter, multi-select neighborhoods, and geo purge — keep BH/SP/Campinas only

> Feature branch: `feat/city-filter-and-purge` · Linear: `BIN-70` · Status: implemented

## Problem

OLX and other scrapes landed properties outside the operator geo (Nova Lima, Uberlândia, other states). Missing city was previously allowed on ingest, so incomplete payloads stayed in the DB. The Properties neighborhood filter was a native always-open multi-select with no search and no city grouping.

## Approach

- Expand `geo_allowlist` to Belo Horizonte, São Paulo, Campinas (+ MG/SP) and **reject missing city** on ingest.
- Harden address city extraction for QuintoAndar-style `, City` tails without UF.
- One-shot bulk purge script using the same allowlist rules (dry-run / `--apply`).
- API: `city_name` filter, `GET /properties/cities`, enrich neighborhoods with `city`.
- Custom searchable multi-select (no antd): click-to-open, tags, search, neighborhoods grouped by city.

## Changes

Files touched:

```
 configs/app_config.yaml                                      | Expand geo_allowlist cities/states
 src/infra/config.py                                          | Default GeoAllowlistConfig keep-list
 src/core/geo_allowlist.py                                    | Reject city_missing; parse ", City" address tail
 src/api/properties.py                                        | city_name filter, /cities, neighborhoods+city
 src/api/schemas.py                                           | CityModel; NeighborhoodModel.city
 scripts/dev/purge_out_of_geo_properties.py                   | NEW — dry-run / --apply purge
 frontend/src/components/SearchableMultiSelect.jsx            | NEW — antd-style multi-select
 frontend/src/pages/Properties.jsx                            | City + neighborhood SearchableMultiSelect
 frontend/src/api.js                                          | cityName param, fetchCities
 frontend/src/index.css                                       | .sms styles
 frontend/tests/e2e/properties-city-neighborhood-filters.spec.js | NEW — Playwright coverage
 frontend/tests/e2e/helpers/apiMocks.js                       | Mock cities + richer neighborhoods
 src/tests/unit/test_geo_allowlist.py                         | Missing city rejected; SP/Campinas; address tails
 src/tests/unit/test_property_city_filters.py                 | NEW — filter builder unit tests
 src/tests/contract/test_api_contract.py                      | Cities + neighborhoods.city contract
 docs/features/49-city-filter-and-geo-purge.md                | NEW — this doc
```

## New Dependencies

None.

## How to Test

1. Unit / contract / e2e:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Purge (local DB):
   ```bash
   export DATABASE_URL=postgresql://imoveis:imoveis_local_dev@localhost:${POSTGRES_PORT}/realestate
   PYTHONPATH=src python scripts/dev/purge_out_of_geo_properties.py
   PYTHONPATH=src python scripts/dev/purge_out_of_geo_properties.py --apply
   ```
3. UI: open Properties → Advanced Filters → Cities / Neighborhoods open only on click; neighborhoods show city group headers; selections appear as removable tags and update the list query.

## Notes / Follow-ups

- Scrapers still primarily target BH URLs; SP/Campinas are allowed for retention/filter but are not actively scraped unless platform `extra` is expanded.
- Workers may re-ingest out-of-geo rows until rebuilt with the new allowlist image — rebuild `api` / `worker_scraper` after deploy.
- Related: BIN-68 (initial geo allowlist), BIN-70 (this feature).
