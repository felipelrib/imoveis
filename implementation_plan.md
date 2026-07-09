# Implementation Plan: BIN-14 — Interactive Map of Properties

## Goal
Add an interactive map view to the Properties page using MapLibre GL with
score-coloured markers, clustering, popups, and a PostGIS bbox filter.

## Affected Areas
- src/api/properties.py — add bbox param + return lat/lon
- frontend/package.json — add maplibre-gl dependency
- frontend/src/api.js — add bbox param to fetchProperties
- frontend/src/pages/Properties.jsx — list/map toggle
- frontend/src/components/MapView.jsx (new) — map component
- frontend/src/index.css — map styles

No schema changes needed (location column already exists).

## Steps

### Step 1 — Backend: return lat/lon in list_properties
Add ST_X(p.location) AS lon, ST_Y(p.location) AS lat to SELECT.

### Step 2 — Backend: add bbox filter
Add optional bbox param (minLon,minLat,maxLon,maxLat string).
Use ST_Within(p.location, ST_MakeEnvelope(...)).

### Step 3 — Frontend: install maplibre-gl
npm install maplibre-gl in frontend/.

### Step 4 — Frontend: add bbox to fetchProperties
Append bbox param when provided.

### Step 5 — Frontend: create MapView component
MapLibre GL map with GeoJSON clustering, score-coloured markers, popups.

### Step 6 — Frontend: integrate toggle into Properties page
Add viewType state (grid/map), toggle buttons, fetch with bbox in map mode.

### Step 7 — Frontend: add map styles
Map container, toggle, popup styles in index.css.

### Step 8 — Validate
validate.sh all
