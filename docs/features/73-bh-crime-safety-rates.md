# BH-first crime / safety rates — SEJUSP regional → neighbourhood scores

> Feature branch: `feat/bh-crime-safety-rates` · Linear: `BIN-96` · Status: implemented

## Problem

BIN-92 shipped São Paulo open-data safety ingest and parked Belo Horizonte because SEJUSP CKAN dumps are município/RISP only. Operator priority is **BH first** — curated YAML judgment alone is not enough once objective overlays exist for other signals.

## Approach

- Confirmed CKAN schema: `registros, natureza, municipio, mes, ano, risp, rmbh` — **no bairro**.
- Ship an intermediate **PBH regional** grain: published SEJUSP H1 2026 regional violent-crime counts (Estado de Minas compilation) mapped onto curated neighbourhoods via `configs/bh_neighbourhood_regionals.yaml`.
- City-relative invert still runs in `safety_overlay` — Centro-Sul nhoods score lower than Venda Nova / Barreiro for this period.
- BH is first in `configs/safety_overlays.example.yaml`; committed seed `configs/bh_safety_rates.yaml` (rebuild with `build_bh_safety_rates.py`).
- Bairro path ready: `--bairro-csv` aggregates LAI / on-demand SEJUSP extracts when the operator obtains them (CMBH Drive extracts document that path).
- Never invent counts; attribution required; UI must not claim absolute safe/unsafe (BIN-94).

### Spike update (2026-07-27)

| Source | Grain | Usable? |
|--------|-------|---------|
| SEJUSP CKAN Crimes Violentos | Município + RISP | Not for nhood differentiation |
| SEJUSP regional counts (via EM / Observatório) | PBH 9 regionais | **Ship** (this feature) |
| SEJUSP on-demand / LAI / CMBH Drive sheets | Bairro (+ rua) | Preferred upgrade via `--bairro-csv` |
| SSP-SP BO microdata | Bairro / coords | Secondary (BIN-92) |

## Changes

Files touched:

```
 configs/bh_neighbourhood_regionals.yaml                       | NEW — nhood → regional map
 configs/bh_regional_crime_counts.yaml                         | NEW — SEJUSP H1 2026 regional counts
 configs/bh_safety_rates.yaml                                  | NEW — expanded rates seed (36 nhoods)
 configs/safety_overlays.example.yaml                          | BH first + SP secondary
 src/core/bh_safety_rates.py                                   | NEW — expand regional / aggregate bairro CSV
 scripts/dev/build_bh_safety_rates.py                          | NEW — CLI builder
 src/tests/fixtures/safety/bh_safety_rates_tiny.yaml           | NEW — tiny BH fixture
 src/tests/unit/test_bh_safety_rates.py                        | NEW — map / expand / CSV / roundtrip
 src/tests/integration/test_safety_overlays.py                 | ADD — BH apply paths
 docs/features/73-bh-crime-safety-rates.md                     | NEW — this doc
 docs/features/72-crime-safety-open-data.md                    | UPDATE — BH unpark note
```

## New Dependencies

None.

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Rebuild + dry-run BH rates:
   ```bash
   PYTHONPATH=src python scripts/dev/build_bh_safety_rates.py \
     --out configs/bh_safety_rates.yaml
   PYTHONPATH=src python scripts/dev/load_safety_overlays.py \
     --rates configs/bh_safety_rates.yaml --city "Belo Horizonte" --state MG --dry-run
   ```
3. Apply against PostGIS after BH neighbourhood rows exist:
   ```bash
   PYTHONPATH=src python scripts/dev/load_safety_overlays.py \
     --config configs/safety_overlays.example.yaml
   ```

## Notes / Follow-ups

- Regional grain means all Centro-Sul curated bairros share one count — upgrade to bairro extracts when LAI lands.
- Barreiro H1 2026 count inferred as city total − sum of listed regionals (2903 − 2643).
- Replace `bh_regional_crime_counts.yaml` when SEJUSP publishes fresher regional tables.
- Scoring / UI blend remains BIN-94.
