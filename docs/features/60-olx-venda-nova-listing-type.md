# OLX Venda Nova listing_type — stop mistaking neighbourhood for sale

> Feature branch: `feat/olx-venda-nova-listing-type` · Linear: `BIN-81` · Status: implemented

## Problem

OLX ad [1520650089](https://mg.olx.com.br/belo-horizonte-e-regiao/imoveis/casa-de-03-quartos-no-candelaria-venda-nova-belo-horizonte-1520650089) (R$1.300, title/address **Venda Nova**) was stored as `listing_type=sale`. Category-less detail URLs defaulted to sale, and `fix_olx_listings._infer_listing_type` treated bare substring `venda` as a sale cue — matching the neighbourhood name.

Scan of live DB (OLX): only **3** `sale` rows with price &lt; R$30k; **1** of them was the Venda Nova false positive. The other two were dual “venda ou locação” ads whose stored price is the rent figure.

## Approach

- Shared helpers in `core/olx_listing_type.py`: mask `Venda Nova` / `venda-nova`, title phrases, price bands; dual titles defer to price.
- Wire into `OLXScraper._detect_listing_type` and `scripts/dev/fix_olx_listings.py`.
- Add `--types-only` to the fix script; applied backfill: **3** rows `sale→rent` (including 1520650089).

## Changes

Files touched:

```
 src/core/olx_listing_type.py                    | NEW — Venda Nova–safe title/price inference
 src/adapters/scrapers/olx.py                    | Use helpers when stamp/path missing
 scripts/dev/fix_olx_listings.py               | Shared inference + --types-only
 src/tests/unit/test_olx_listing_type.py         | NEW — helper regressions
 src/tests/unit/test_olx.py                      | Detect listing type cases for BIN-81
 docs/features/60-olx-venda-nova-listing-type.md | NEW — this note
```

## New Dependencies

None.

## How to Test

1. Unit: `pytest src/tests/unit/test_olx_listing_type.py src/tests/unit/test_olx.py::TestDetectListingType`
2. Backfill (already applied on primary DB):
   ```bash
   PYTHONPATH=src python scripts/dev/fix_olx_listings.py --types-only --apply
   ```
3. UI: Max price 5000 + Sale should no longer show the Candelária / Venda Nova R$1.300 card.

## Notes / Follow-ups

- Dual listings that store a single rent price as `sale` are reclassified to rent; when **both** prices exist they now become two `property_listings` rows — see [88-olx-dual-rent-sale-listings](88-olx-dual-rent-sale-listings.md) (BIN-108).
- Rebuild `worker_scraper` after merge so new scrapes pick up detect changes.
