# Interactive Map of Properties

> Feature branch: `feat/interactive-map` · Status: implemented
> Linear: [BIN-14](https://linear.app/felipelrib/issue/BIN-14/interactive-map-of-properties)
> Milestone: v0.3 — User Experience

## Problem

Location is the #1 real-estate dimension. Properties have lat/lon stored as a
PostGIS POINT column, but the UI only shows them as a number in the modal. A
map makes spatial deal-hunting intuitive and helps users see neighbourhood
clusters at a glance.

## Approach

- **Map library**: MapLibre GL JS (free, open-source, no API key required).
  Uses OpenStreetMap raster tiles with a vector-style API for markers.
- **Clustering**: MapLibre's built-in GeoJSON clustering (`cluster: true`)
  handles large result sets without external dependencies.
- **Score-coloured markers**: Circle-layer markers coloured by
  `combined_score` — green (≥0.7), yellow (≥0.4), red (<0.4), grey (no score).
- **Backend bbox filter**: New `bbox=minLon,minLat,maxLon,maxLat` parameter
  on `GET /properties` using PostGIS `ST_Within` + `ST_MakeEnvelope` for
  server-side viewport filtering.
- **Integration**: List/Map toggle in the Properties page toolbar. Map view
  uses the same filter state and fetches properties with the bbox parameter.
  Grid view is unchanged.

## Changes

```
src/api/properties.py                 — added lat/lon to SELECT, bbox filter
frontend/src/api.js                   — added bbox param to fetchProperties
frontend/src/components/MapView.jsx   — new MapLibre GL map component
frontend/src/pages/Properties.jsx     — list/map toggle, handleBboxChange
frontend/src/index.css                — map popup/control styles
frontend/package.json                 — added maplibre-gl dependency
frontend/package-lock.json            — lockfile update
```

## New dependencies

- `maplibre-gl` — MapLibre GL JS mapping library (no API key needed)

## How to test

1. `bash scripts/start.sh` (or `docker compose up`)
2. Navigate to Properties page
3. Click the **🗺 Map** toggle button in the toolbar
4. Verify the map loads centered on Belo Horizonte
5. Verify markers appear at correct coordinates (if properties exist)
6. Click a marker → popup shows title, price, score, and "View Details" button
7. Click "View Details" → PropertyModal opens
8. Pan/zoom the map → markers update for the new viewport
9. Click the **☷ List** toggle → grid view returns
10. `bash scripts/validate.sh all`

## Notes / follow-ups

- Map tiles come from OpenStreetMap (requires internet on first load)
- The `alembic check` warning about PostGIS system tables is pre-existing
  and unrelated to this feature
