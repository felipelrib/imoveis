# SP/Campinas scrape coverage — multi-city windows for QuintoAndar and OLX

> Feature branch: `feat/bin-113-sp-campinas-scrape` · Linear: `BIN-113` · Status: implemented

## Problem

Geo allowlist already keeps Belo Horizonte, São Paulo, and Campinas for retention and UI filters, but both scrapers only seeded BH search windows. SP/Campinas inventory never entered the pipeline unless an operator hand-edited platform `extra` and the scrapers still assumed a single city.

## Approach

- Add optional `extra.cities` on QuintoAndar and OLX; fall back to legacy top-level `city_slug` / `region` + `neighborhoods` when absent.
- Enable SP and Campinas as **city-wide** windows (`neighborhoods: []`); BH keeps its existing neighborhood fan-out. Price bisect still applies before truncate.
- Carry city identity on QuintoAndar windows (and stamp `_qa_city_slug` on yields) so normalize city/state fallbacks are not hard-coded to BH/MG.
- Key OLX neighborhood fan-out by category path so BH neighborhoods never attach under SP/Campinas paths.

## Changes

Files touched:

```
 configs/app_config.yaml                         | Migrate QA/OLX to extra.cities (BH+SP+Campinas)
 src/adapters/scrapers/quintoandar.py            | Multi-city windows + slug-based city/state fallback
 src/adapters/scrapers/olx.py                    | Multi-city paths + per-path neighborhood fan-out
 src/adapters/queue/tasks.py                     | OLX reconcile catalog reads neighborhoods from cities
 src/tests/unit/test_quintoandar.py              | Multi-city windows, nb skip, normalize SP/Campinas
 src/tests/unit/test_olx.py                      | Multi-city paths + per-path fan-out isolation
 src/tests/unit/test_neighbourhood_quality_yaml.py | Fan-out slug coverage reads cities[].neighborhoods
 docs/features/91-sp-campinas-scrape-coverage.md | NEW — this doc
 docs/features/49-city-filter-and-geo-purge.md   | Resolve scrape-coverage follow-up
```

## New Dependencies

None.

## How to Test

1. Unit gate:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Confirm config loads three QA city slugs and six OLX rent paths (3 cities × 2 categories) when `scrape_type=rent`:
   ```bash
   PYTHONPATH=src python -c "
   from infra.config import get_config
   from adapters.scrapers.quintoandar import QuintoAndarScraper
   from adapters.scrapers.olx import OLXScraper
   cfg = get_config()
   qa = QuintoAndarScraper('quintoandar', cfg.scraping.platforms['quintoandar'].model_dump())
   olx = OLXScraper('olx', cfg.scraping.platforms['olx'].model_dump())
   print([c['city_slug'] for c in qa._cities])
   print(len(olx._initial_windows({'scrape_type': 'rent'})))
   "
   ```
3. After deploy: rebuild `worker_scraper` (and `beat` if schedule image embeds config) so the new YAML is live.

### Operator enablement

| Goal | Change in `configs/app_config.yaml` |
|------|-------------------------------------|
| Stop scraping a city | Remove that entry under `extra.cities` |
| Deepen SP/Campinas coverage | Add `{ slug: ... }` (QA) or `{ slug, zone }` (OLX) under that city's `neighborhoods` |
| Revert to BH-only | Keep only the BH city entry (or drop `cities` and use legacy `city_slug` / `region`) |

Geo allowlist and purge scripts are unchanged — out-of-geo rows are still rejected on persist / purgeable offline.

## Notes / Follow-ups

- SP/Campinas have no starter neighborhood catalogs yet; city-wide + price bisect may hit SSR/page ceilings more often until operators add slugs.
- Related: BIN-70 / feature 49 (geo allowlist), BIN-113 (this ticket).
