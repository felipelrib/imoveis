# Frontend Dashboard — React/Vite SPA with real-time monitoring, property browser, and map view

> Feature branch: `feat/frontend` · Linear: `BIN-XX` · Status: implemented

## Problem

Operators need a visual interface to monitor system health, trigger scrapes, control workers, browse properties with advanced filters, manage favourites/watchlist, save search presets, and explore properties on a map.

## Approach

- **React 18 SPA with Vite**: Client-side routing via `react-router-dom` with 3 primary pages:
  1. **Dashboard** — Service status, pipeline charts (Recharts), stats, quick actions
  2. **Scraper Control** — Platform selector, scrape trigger, worker pause/resume, schedule editor, activity log
  3. **Properties** — Filterable grid/map view with property cards, modal detail, favourites, watchlist, saved searches

- **Sidebar navigation**: App shell with persistent sidebar showing navigation links and live service health dots (DB, Redis, Ollama, AI Workers).

- **Real-time polling**: `useSystemStatus` hook polls `/system/status` every 6s. Dashboard polls `/system/pipeline` every 8s. Scraper Control polls pipeline every 3s and schedule every 15s.

- **Property grid features**:
  - 12+ filter parameters (sort, listing type, property type, price, bedrooms, parking, score, furnished, pets, neighbourhood)
  - Multi-select neighbourhood filter populated from API
  - Grid / Map view toggle
  - Saved searches sidebar with save/delete/apply
  - Favourites view mode
  - Watchlist toggle per card
  - Property modal with full details, price history, AI analysis

- **Map view**: Uses MapLibre GL JS with OpenStreetMap tiles. Properties displayed as markers with score-colored badges. Supports bbox-based spatial querying.

- **Toast notifications**: `ToastProvider` component for success/error/info feedback.

- **Persistent logs**: Scraper Control activity log persists to localStorage (capped at 200 entries).

## Changes

Files touched:

```
 frontend/src/App.jsx                     | App shell, sidebar, routing
 frontend/src/api.js                      | API client with 20+ functions
 frontend/src/pages/Dashboard.jsx         | Service status, pipeline charts, stats
 frontend/src/pages/ScraperControl.jsx    | Scrape trigger, worker control, schedule
 frontend/src/pages/Properties.jsx        | Property grid, filters, favourites, watchlist
 frontend/src/components/PropertyModal.jsx| Property detail modal
 frontend/src/components/MapView.jsx      | MapLibre GL map with markers
 frontend/src/components/ToastProvider.jsx| Toast notification system
 frontend/src/hooks/useSystemStatus.js    | Polling hook for system status
 frontend/src/index.css                   | Complete design system (dark theme)
```

## New Dependencies

- `react`, `react-dom`, `react-router-dom` — Core React stack
- `recharts` — Dashboard charts
- `maplibre-gl` — Map rendering
- `lucide-react` — Icon library (present in deps but may not be actively used)
- `@playwright/test` — E2E testing

## How to Test

1. Start the frontend:
   ```bash
   cd frontend && npm run dev
   ```
2. Ensure the backend is running on port 8000. Vite proxy is configured in `vite.config.js`.
3. Open `http://localhost:5173`

## Notes / Follow-ups

### Bugs Found

- **BUG (Critical): Properties page displays wrong data due to API column index mismatch** — As documented in `07-rest-api.md`, the backend `list_properties` endpoint returns columns in wrong indices, causing the frontend to display `address` where `stat_score` should be, etc. All scoring data on property cards is incorrect.

- **BUG (Moderate): `apiOk` computed but never used** (App.jsx L17): `const apiOk = !loading && status?.database?.status === 'ok'` is declared but never referenced. Presumably should gate UI rendering.

- **BUG (Minor): `load()` uses stale closures** (Properties.jsx L115-160): The `load` function captures `sortBy`, `listingType`, etc. from closure but is called from `useEffect` which has these as dependencies. However, `page` is also captured, and the `load(1)` call in the filter-change effect should reset pagination correctly but the function re-reads `page` from closure, not the argument.

- **BUG (Minor): Map view passes `data?.properties` instead of `mapProperties`** (Properties.jsx L463): The `MapView` component receives `properties={data?.properties || []}` but `mapProperties` state from `handleBboxChange` is never passed. Map always shows the current grid page's properties rather than spatial results.

### Tech Debt

- **No lazy loading/code splitting** — All pages load eagerly.
- **No error boundaries** — An unhandled error in any component crashes the entire app.
- **`VITE_API_KEY` exposed in client bundle** — Admin API key is visible in browser DevTools. Fine for local dev but should not be used in production.
- **No accessibility (a11y)** — Missing ARIA labels, keyboard navigation, and screen reader support.
- **Inline styles proliferate** — Most component styling uses inline `style={{}}` objects rather than CSS classes.
