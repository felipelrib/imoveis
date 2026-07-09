# Saved Searches & Favourites

## Problem

The Properties page has rich filters but no persistence — users re-enter the same
query each visit and can't keep a shortlist of properties they like.

## Solution

Two complementary features added to the Properties page:

1. **Saved Searches** — Save the current filter set with a name, reload and reapply it
   later. A sidebar panel on the left shows all saved searches with one-click apply.
2. **Favourites** — Star properties to add them to a shortlist. Toggle ★ on each card
   or in the modal. A dedicated "Favourites" view shows only starred properties.

## Database

Two new tables (nullable `owner` column for future auth):

- **saved_searches** — stores filter JSON as a JSONB column
- **favourites** — links to `properties` via FK with unique constraint

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/saved-searches` | List all saved searches |
| `POST` | `/saved-searches` | Create a new saved search |
| `DELETE` | `/saved-searches/{id}` | Delete a saved search |
| `GET` | `/favourites` | List all favourites with property details |
| `POST` | `/favourites` | Add a property to favourites |
| `DELETE` | `/favourites/{property_id}` | Remove from favourites |
| `GET` | `/favourites/check/{property_id}` | Check if property is favourited |

## Frontend

- **Properties.jsx** — sidebar panel with saved searches and favourites link
- **PropertyModal.jsx** — ★ favourite toggle in the modal header
- **PropertyCard** (inline in Properties.jsx) — ★ favourite button alongside 🔔 watchlist
- **index.css** — sidebar styles, favourite button, responsive layout

## Files Changed

| File | Change |
|------|--------|
| `src/adapters/db/models.py` | Added `SavedSearch` and `Favourite` models |
| `alembic/versions/c7d8e9f0a1b2_*.py` | Migration for both tables |
| `src/api/saved_searches.py` | CRUD for saved searches |
| `src/api/favourites.py` | CRUD for favourites |
| `src/api/main.py` | Registered new routers |
| `frontend/src/api.js` | Added API functions |
| `frontend/src/pages/Properties.jsx` | Sidebar + favourites view mode |
| `frontend/src/components/PropertyModal.jsx` | Favourite toggle |
| `frontend/src/index.css` | Sidebar + favourite styles |

## Acceptance Criteria

- [x] Save a filter set, reload page, reapply it — same results
- [x] Favourite/unfavourite persists across page reload
- [x] Favourites view lists only starred properties
- [x] Saved searches sidebar shows all with quick-apply
- [x] Tables have nullable `owner` column for future auth
- [x] `validate.sh` passes
