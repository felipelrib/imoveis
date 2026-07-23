# Favourites & Saved Searches — User preference persistence for property bookmarking and filter presets

> Feature branch: `feat/user-prefs` · Linear: `BIN-XX` · Status: implemented

## Problem

Users need to bookmark interesting properties for quick access and save complex filter combinations for reuse. These preferences must persist across sessions and be accessible from the frontend sidebar.

## Approach

- **Favourites**:
  - Simple `favourites` table with `(id, property_id, created_at)` and a unique constraint on `property_id`
  - Full CRUD via `/favourites` API using atomic `INSERT ... ON CONFLICT DO NOTHING` to prevent TOCTOU duplicates
  - List endpoint JOINs with `properties`, `metrics_scoring`, and `neighborhoods` to return enriched data (title, price, score, image)
  - Frontend toggle button (★/☆) on each property card with optimistic state management
  - Dedicated "Favourites" view mode in Properties page showing only favourited properties

- **Saved Searches**:
  - `saved_searches` table with `(id, name, filters: JSONB, created_at)`
  - Full CRUD via `/saved-searches` API
  - Strict validation of stored filters using a `SavedSearchFilters` Pydantic model (`extra="ignore"`) to ensure data schema integrity
  - Frontend sidebar panel showing named searches with click-to-apply and delete
  - Save dialog captures current filter state as a named preset
  - Applies by setting all filter state variables in the Properties component

## Changes

Files touched:

```
 src/api/favourites.py               | CRUD API with enriched list endpoint
 src/api/saved_searches.py           | CRUD API with JSONB filter storage
 src/adapters/db/models.py           | Favourite and SavedSearch ORM models
 frontend/src/api.js                 | fetchFavourites, addFavourite, removeFavourite, checkFavourite, fetchSavedSearches, saveSearch, deleteSavedSearch
 frontend/src/pages/Properties.jsx   | Favourites toggle, saved searches sidebar, view mode
```

## New Dependencies

None.

## How to Test

1. Add a favourite:
   ```bash
   curl -X POST http://localhost:8000/favourites \
     -H 'Content-Type: application/json' \
     -d '{"property_id": "UUID_HERE"}'
   ```
2. List favourites:
   ```bash
   curl http://localhost:8000/favourites
   ```
3. Save a search:
   ```bash
   curl -X POST http://localhost:8000/saved-searches \
     -H 'Content-Type: application/json' \
     -d '{"name": "Cheap in Savassi", "filters": {"maxPrice": "5000", "neighborhood": "Savassi"}}'
   ```
4. Frontend: Click ★ on a property card → appears in Favourites view. Click "Save Current Filters" → appears in sidebar.

## Notes / Follow-ups

### Fixed Tech Debt
