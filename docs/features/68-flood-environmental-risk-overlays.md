# Flood / environmental risk overlays — neighbourhood risk_flags from open GeoJSON

> Feature branch: `feat/flood-environmental-risk-overlays` · Linear: `BIN-91` · Status: implemented

## Problem

Flood and industrial adjacency signals are otherwise only as good as seller ad copy. Neighbourhood quality profiles (BIN-86) already expose `risk_flags` and `quality_meta`, but nothing filled them from objective geospatial layers.

## Approach

- Vendor-agnostic GeoJSON loader (mirrors feature 28): operator supplies local risk polygons — no municipal URL or SDK hardcoded.
- Intersect each `neighborhoods.geometry` with risk features → managed flags `flood_zone` / `industrial_adjacent`; max severity lands under `quality_meta.risk`.
- Missing layer paths for a city are logged and skipped (exit continues); present but invalid GeoJSON still fails that invocation.
- Tiny fixtures in git; large dumps under gitignored `data/geo/`.

### Open sources researched (operator export → GeoJSON)

| City | Flood / hydrological | Industrial / zoning notes |
|------|----------------------|---------------------------|
| **Belo Horizonte** | PBH Dados Abertos ([Área Risco Geológico](https://dados.pbh.gov.br/dataset/area-risco-geologico), [Área Prioritária SBN — Inundação](https://dados.pbh.gov.br/dataset/area-prioritaria-sbn-inundacao)); BHGeo “Área de risco de inundação”; [Cartas de Inundações](https://prefeitura.pbh.gov.br/obras-e-infraestrutura/informacoes/diretoria-de-gestao-de-aguas-urbanas/cartas-de-inundacoes) / BH Map | Municipal zoning / industrial land-use layers via Prodabel / BHGeo exports |
| **São Paulo** | GeoSampa [Risco Hidrológico](https://metadados.geosampa.prefeitura.sp.gov.br/geonetwork/srv/api/records/cefffc6d-8d1d-419b-a267-8d87a37b9e0e), [PDMAT3 áreas inundáveis](https://metadados.geosampa.prefeitura.sp.gov.br/geonetwork/srv/api/records/dfe7ddf5-4d0b-4cb0-ba0c-f5a186b1d587) (WFS/WMS/SHP) | Zoneamento / uso industrial via GeoSampa (convert locally) |
| **Campinas** | Zoneamento SHP [Área Inundável TR 100](https://zoneamento.campinas.sp.gov.br/novo_zoneamento/exporta_shp.php?id=166); Defesa Civil risk pages | Municipal zoneamento industrial layers |

Convert SHP/WFS to WGS84 GeoJSON (`ogr2ogr` / QGIS) before loading. Paths only — see `configs/risk_overlays.example.yaml`.

## Changes

Files touched:

```
 src/core/risk_overlay.py                                      | NEW — parse, intersect, apply, skip-missing
 scripts/dev/load_risk_overlays.py                             | NEW — CLI (--geojson / --config / --dry-run)
 configs/risk_overlays.example.yaml                            | NEW — city → layer path map example
 src/tests/fixtures/geo/bh_risk_flood_tiny.geojson             | NEW — overlaps FixtureA
 src/tests/fixtures/geo/bh_risk_industrial_tiny.geojson        | NEW — overlaps FixtureB
 src/tests/unit/test_risk_overlay.py                           | NEW — parse / severity / intersect / skip
 src/tests/integration/test_risk_overlays.py                   | NEW — DB flags + meta + idempotency
 .gitignore                                                    | ADD data/geo/ + *.gpkg
 docs/features/68-flood-environmental-risk-overlays.md         | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml      | 6-6 → done
```

## New Dependencies

None (uses existing `shapely`, `geoalchemy2`, `pyyaml`).

## How to Test

1. Agent gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Dry-run fixtures:
   ```bash
   PYTHONPATH=src python scripts/dev/load_risk_overlays.py \
     --geojson src/tests/fixtures/geo/bh_risk_flood_tiny.geojson \
     --risk-type flood_zone --dry-run
   ```
3. Apply against a running PostGIS after neighbourhood polygons are loaded:
   ```bash
   PYTHONPATH=src python scripts/dev/load_risk_overlays.py \
     --geojson /path/to/bh_flood.geojson --risk-type flood_zone \
     --city "Belo Horizonte" --state MG
   ```
4. Missing paths (example config) warn and skip without failing dry-run:
   ```bash
   PYTHONPATH=src python scripts/dev/load_risk_overlays.py \
     --config configs/risk_overlays.example.yaml --dry-run
   ```

## Notes / Follow-ups

- Depends on BIN-86 schema (`risk_flags`, `quality_meta`) and feature 28 neighbourhood polygons.
- Scoring / UI blend of risk flags is BIN-94.
- Optional crime/safety overlays are BIN-92 (separate managed flags if needed).
- GeoJSON contract: `properties.risk_type` ∈ {`flood_zone`, `industrial_adjacent`}; optional `severity` (`low`|`medium`|`high` or 0–1); Polygon/MultiPolygon SRID 4326.
