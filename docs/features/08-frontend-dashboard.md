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

### Fixed Tech Debt
