# interactive-map — MapLibre GL spatial property browser with score-coloured markers and viewport filtering

> Feature branch: `feat/interactive-map` · Linear: `BIN-14` · Status: implemented

## Problem

Location is the #1 real-estate dimension. Properties store coordinates as a PostGIS `POINT`
column, but the UI only displayed them as numbers inside the detail modal. A map view makes
spatial deal-hunting intuitive and reveals neighbourhood clusters at a glance.

## Approach

- **Map library**: MapLibre GL JS — free, open-source, no API key required. Backed by
  OpenStreetMap raster tiles with a vector-style layer API for custom markers.
- **GeoJSON clustering**: MapLibre's built-in `cluster: true` on the GeoJSON source
  groups nearby markers at low zoom levels, scaling circle size with cluster count
  (`step` expression). No extra libraries needed.
- **Score-coloured markers**: A `case` expression in the `circle-color` paint property
  colours each point by `combined_score`:
  - Green (`#10b981`) ≥ 0.7
  - Yellow (`#f59e0b`) ≥ 0.4
  - Red (`#ef4444`) < 0.4
  - Grey (`#6b7280`) — no score yet
- **Popup on click**: `maplibregl.Popup` renders property title, price, bedrooms, area, score,
  and a "View Details" button. The button's click handler calls `onSelectProperty` to open
  the existing `PropertyModal`.
- **Backend bbox filter**: `GET /properties?bbox=minLon,minLat,maxLon,maxLat` uses PostGIS
  `ST_Within(location, ST_MakeEnvelope(..., 4326))` for server-side viewport clipping.
  Only properties in the current map view are fetched.
- **Integration**: List/Map toggle button in the Properties page toolbar. Map view shares
  the full filter state with the grid. The `onBboxChange` callback fires on `moveend`
  and re-fetches with the new viewport bounding box.

## Changes

Files touched:

```
 src/api/properties.py                | Added lat/lon extraction, bbox filter (ST_Within + ST_MakeEnvelope)
 frontend/src/api.js                  | Added bbox param to fetchProperties()
 frontend/src/components/MapView.jsx  | NEW — MapLibre GL map component with clustering, popups, score colours
 frontend/src/pages/Properties.jsx    | List/Map toggle, handleBboxChange callback
 frontend/src/index.css               | Map popup styles, map container sizing
 frontend/package.json                | Added maplibre-gl dependency
 frontend/package-lock.json          | Lockfile update
```

## New Dependencies

- `maplibre-gl` (npm) — MapLibre GL JS mapping library (no API key needed).

## How to Test

1. Start the stack: `bash scripts/start.sh`
2. Navigate to **Properties** page.
3. Click the **🗺 Map** toggle in the toolbar.
4. Verify the map loads centred on Belo Horizonte (−43.94, −19.92).
5. Verify markers appear at correct coordinates (if properties with lat/lon exist).
6. Click an unclustered marker → popup shows title, price, score, and "View Details" button.
7. Click "View Details" → `PropertyModal` opens correctly.
8. Pan/zoom the map → markers refresh for the new viewport.
9. Click the **☷ List** toggle → grid view restores.

## Notes / Follow-ups

- **BUG (XSS in map popup)**: `popup.setHTML(popupHtml)` where `popupHtml` interpolates
  `props.title` from the GeoJSON feature — which originates from the database. If a
  property title contains `<script>` or event attributes, it executes in the popup context.
  Use `setDOMContent()` with a manually constructed DOM tree, or sanitize with DOMPurify
  before calling `setHTML()`.
- **BUG (`map-view-btn` selector picks first button only)**: The "View Details" click handler
  uses `map.getContainer().querySelector('.map-view-btn')`, which always selects the first
  matching element. If two popups are open simultaneously (unlikely but possible), it could
  call `onSelectProperty` with the wrong `id`. Use `e.target` inside the event listener
  instead.
- **BUG (Cluster click callback API deprecated)**: `getClusterExpansionZoom(clusterId, callback)`
  is the legacy callback form; newer MapLibre versions prefer the Promise-based
  `getClusterExpansionZoom(clusterId)`. The callback will silently fail on future versions.
- **`updateMarkers` as `useCallback` dependency array**: `onSelectProperty` is listed as a
  dependency but not `onBboxChange`. If `onBboxChange` changes identity between renders the
  map's `moveend` handler captures a stale closure. Include `onBboxChange` in the
  `useCallback` deps.
- Map tiles require internet access on first load. Consider bundling a local tile server
  (e.g. `maptiler/tileserver-gl`) for fully offline operation.
