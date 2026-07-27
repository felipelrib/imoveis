# Crime / safety open-data — neighbourhood safety_score from SSP rates

> Feature branch: `feat/bin-92-crime-safety-open-data` · Linear: `BIN-92` · Status: implemented

## Problem

Neighbourhood `safety_score` was only filled by curated operator judgment (BIN-87 YAML) for Belo Horizonte. House-hunters need an open-data safety proxy where legally and practically available — without inventing crime numbers from listing text or claiming absolute “safe/unsafe”.

## Approach

- Spike MG/SP sources first (table below); ship ingest only where grain supports neighbourhood differentiation.
- **Ship São Paulo** via vendor-agnostic YAML/CSV rate files (mirrors flood overlays BIN-91): operator exports SSP-SP BO microdata offline → aggregate rates → load. No live SSP scrape in CI.
- **Ship Belo Horizonte (BIN-96)** via PBH regional SEJUSP counts mapped to curated neighbourhoods; bairro LAI extracts preferred when available. Campinas / Fogo Cruzado remain parked.
- City-relative invert of `rate_per_100k` → `safety_score` in `[0,1]`; nested `quality_meta.safety` carries period, rate definition, and attribution (UI must not label absolute safe/unsafe without this — blend is BIN-94).

### Spike findings (2026-07-27)

| Source | Grain | Usable? |
|--------|-------|---------|
| [SEJUSP MG Crimes Violentos](https://dados.mg.gov.br/dataset/crimes-violentos) | Município + RISP | Not for nhood score |
| SEJUSP regional counts (PBH regionais) | Regional | **Ship BH** — see [73-bh-crime-safety-rates.md](73-bh-crime-safety-rates.md) |
| [SSP-SP Transparência BO](https://www.ssp.sp.gov.br/transparenciassp/Apresentacao.aspx) | Bairro / coords | **Ship SP** (operator → rates file) |
| PBH GCM stats | PDF aggregates | Park |
| [Fogo Cruzado API](https://api.fogocruzado.org.br/docs) | Lat/lon | Park (not BH/SP) |
| SINESP / IBGE | Município / population | Benchmark / denominator only |
| GeoSampa distritos | 96 districts | Preferred join geometry when building SP rates offline |

### Operator recipe (São Paulo)

1. Download BO microdata from SSP-SP Transparência / Dados Abertos.
2. Filter município São Paulo; aggregate counts by bairro (or point→GeoSampa distrito, then map to neighbourhood names).
3. Divide by population (IBGE / distrito) → `rate_per_100k`.
4. Write YAML/CSV (`name`, `city`, `state`, `rate_per_100k`, `period_*`).
5. `PYTHONPATH=src python scripts/dev/load_safety_overlays.py --config configs/safety_overlays.example.yaml` (after pointing `path`).

Large dumps under gitignored `data/safety/`. Tiny synthetic fixture in git for tests only.

## Changes

Files touched:

```
 src/core/safety_overlay.py                                    | NEW — parse YAML/CSV, relative score, apply, meta merge
 scripts/dev/load_safety_overlays.py                           | NEW — CLI (--rates / --config / --dry-run)
 configs/safety_overlays.example.yaml                          | NEW — SP path stub
 src/tests/fixtures/safety/sp_safety_rates_tiny.yaml           | NEW — synthetic Pinheiros/Moema rates
 src/tests/unit/test_safety_overlay.py                         | NEW — parse / score / meta / skip / idempotent
 src/tests/integration/test_safety_overlays.py                 | NEW — DB scores + meta + missing file
 .gitignore                                                    | ADD data/safety/
 docs/features/72-crime-safety-open-data.md                    | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml      | 6-7 → done
```

## New Dependencies

None.

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Dry-run fixture:
   ```bash
   PYTHONPATH=src python scripts/dev/load_safety_overlays.py \
     --rates src/tests/fixtures/safety/sp_safety_rates_tiny.yaml --dry-run
   ```
3. Apply against running PostGIS after SP neighbourhood rows exist:
   ```bash
   PYTHONPATH=src python scripts/dev/load_safety_overlays.py \
     --rates /path/to/sp_crime_rates.yaml --city "São Paulo" --state SP
   ```
4. Missing paths (example config) warn and skip without failing dry-run:
   ```bash
   PYTHONPATH=src python scripts/dev/load_safety_overlays.py \
     --config configs/safety_overlays.example.yaml --dry-run
   ```

## Notes / Follow-ups

- Depends on BIN-86 schema (`safety_score`, `quality_meta`) and existing neighbourhood rows (feature 28 polygons / name match).
- Curated YAML remains the BH safety fill; it has no SP rows today. Run open-data loader after curated if SP curated scores are added later.
- Scoring / UI blend is BIN-94 — must surface `quality_meta.safety.attribution` and never claim absolute safe/unsafe.
- Never invent crime numbers from listing AI prompts.
- BH unlock (done in BIN-96): regional SEJUSP counts → neighbourhood rates; bairro LAI extracts via `build_bh_safety_rates.py --bairro-csv`. See docs/features/73-bh-crime-safety-rates.md.
- Fogo Cruzado expansion into MG/SP still a future option for armed-violence grain.
