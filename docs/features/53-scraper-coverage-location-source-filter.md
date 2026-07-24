# Scraper coverage, OLX location accuracy, and platform filter

> Feature branch: `feat/scraper-limits-location-source-filter` · Linear: `BIN-74` · Status: implemented

## Problem

OLX scrapes stopped near ~200 listings because windows that hit `max_pages` with a partial last page (~40 of 50 ads) were not marked saturated, so price/neighborhood fan-out never ran. QuintoAndar still truncated when an atomic price+neighborhood window stayed at the SSR ceiling (≥12). Property cards showed wrong pin text (city “São Paulo” as neighborhood, slug “sion”) and had no source filter despite an API-ready `?platform=` param.

## Approach

- Soften OLX saturation: at `page_size_hint >= 10`, treat last page as full enough at 70% of hint so partial last pages fan out; keep strict equality for tiny test hints.
- QuintoAndar: after price bisect and neighborhood fan-out, fan out by house type (`apartamento` / `casa`) before accepting truncation.
- Harden `olx_location` when neighborhood is an allowlisted city name; prefer BH for MG scrapes when a catalog bairro is recovered from the title; run existing `fix_olx_listings.py --apply`.
- Project `city` on list/detail rows; humanize slug labels; cards show `Neighborhood, City`.
- Wire platform select in Properties UI to the existing API client param.

## Changes

Files touched:

```
 src/adapters/scrapers/olx.py                              | Soft saturation threshold for partial last pages
 src/adapters/scrapers/quintoandar.py                      | House-type fan-out on atomic nb saturation
 src/core/olx_location.py                                  | neighborhood_is_city detection + MG→BH heuristic
 src/api/property_projection.py                            | city projection, humanize, format_location_label
 src/api/schemas.py / properties.py                        | city on PropertyModel + detail SELECT
 frontend/src/pages/Properties.jsx                         | platform filter + location card label
 frontend/tests/e2e/properties-platform-filter.spec.js     | NEW — platform=olx + location label e2e
 src/tests/unit/test_olx.py                                | Partial last-page saturation regression
 src/tests/unit/test_quintoandar.py                        | House-type fan-out + URL tests
 src/tests/unit/test_olx_location.py                       | São Paulo-as-nb + Sion title regression
 src/tests/unit/test_property_projection.py                | city / humanize / location label
 docs/features/53-scraper-coverage-location-source-filter.md | NEW — this note
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
bash scripts/agent/validate-scrapers.sh --require-live
```

Manual:

1. Rebuild scraper worker after merge: `docker compose --env-file .env.local build worker_scraper && docker compose --env-file .env.local up -d worker_scraper`.
2. Trigger OLX scrape; logs should show `olx_splitting_price_window` / `olx_fanout_neighborhoods` past the old ~200 cliff.
3. Trigger QuintoAndar; look for `quintoandar_fanout_house_types` on dense atomic bands.
4. Properties → Source = OLX → network shows `platform=olx`; cards show `📍 Sion, Belo Horizonte` style labels.
5. Backfill legacy OLX rows (local):
   ```bash
   export DATABASE_URL=postgresql://imoveis:imoveis_local_dev@localhost:${POSTGRES_PORT}/realestate
   PYTHONPATH=src python scripts/dev/fix_olx_listings.py --skip-ai --no-merge          # dry-run
   PYTHONPATH=src python scripts/dev/fix_olx_listings.py --apply --skip-ai --no-merge
   ```

## Notes / Follow-ups

- Atomic QuintoAndar windows that remain ≥12 after house-type fan-out still truncate at SSR; no deeper pagination without a non-SSR client.
- Platform filter matches canonical `properties.platform`, not “has any listing on X”.
- Rebuild `worker_scraper` so Compose does not run a stale image after scraper changes.
- Prefer `--no-merge` on `fix_olx_listings.py --apply` until merge FK ordering is hardened (template OLX titles false-positive heavily).
- Related: BIN-62 funneling, BIN-72 OLX location, BIN-70 city filters.
