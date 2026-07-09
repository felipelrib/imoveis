# Implementation Plan — Saved Searches & Favourites (BIN-13)

## Goal

Add filter persistence and property shortlisting to the Properties page. Users can save their current filter set and reapply it later, and favourite individual properties for quick access.

## Affected Areas

### Backend
- `src/adapters/db/models.py` — add `SavedSearch` and `Favourite` models
- `alembic/versions/` — new migration for both tables
- `src/api/saved_searches.py` — **new file**: CRUD for saved searches
- `src/api/favourites.py` — **new file**: CRUD for favourites
- `src/api/main.py` — register new routers

### Frontend
- `frontend/src/api.js` — add fetchSavedSearches, saveSearch, deleteSavedSearch, fetchFavourites, addFavourite, removeFavourite, checkFavourite
- `frontend/src/pages/Properties.jsx` — add Saved Searches sidebar, ★ favourite toggle on PropertyCard, favourites view mode
- `frontend/src/index.css` — styles for sidebar and favourite button
- `frontend/src/components/PropertyModal.jsx` — add ★ favourite toggle in modal header

## Database Schema

### saved_searches
```sql
CREATE TABLE saved_searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL,
    filters JSONB NOT NULL,
    owner UUID,
    created_at TIMESTAMP DEFAULT now()
);
```

### favourites
```sql
CREATE TABLE favourites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    owner UUID,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(property_id)
);
```

## Step-by-Step Implementation

### Step 1: Add database models (commit: `feat: add SavedSearch and Favourite models`)

Add to `src/adapters/db/models.py`:

```python
class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))
    name = Column(String, nullable=False)
    filters = Column(JSON, nullable=False)
    owner = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default=sa.text("now()"))

class Favourite(Base):
    __tablename__ = "favourites"
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    owner = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default=sa.text("now()"))
    __table_args__ = (sa.UniqueConstraint("property_id", name="uq_favourite_property"),)
```

### Step 2: Create Alembic migration (commit: `feat: add migration for saved_searches and favourites tables`)

Create `alembic/versions/<hash>_add_saved_searches_favourites.py`:
- `upgrade()`: CREATE TABLE saved_searches, CREATE TABLE favourites
- `downgrade()`: DROP TABLE favourites, DROP TABLE saved_searches

### Step 3: Create backend API for saved searches (commit: `feat: add saved searches API endpoints`)

Create `src/api/saved_searches.py` following the watchlist pattern:
- `GET /saved-searches` — list all (ordered by created_at DESC)
- `POST /saved-searches` — create with `{name, filters: {...}}`
- `DELETE /saved-searches/{id}` — delete by ID
- `GET /saved-searches/{id}` — get single (to retrieve filters)

### Step 4: Create backend API for favourites (commit: `feat: add favourites API endpoints`)

Create `src/api/favourites.py` following the watchlist pattern:
- `GET /favourites` — list all (JOIN properties to return property data)
- `POST /favourites` — add `{property_id}`
- `DELETE /favourites/{property_id}` — remove by property_id
- `GET /favourites/check/{property_id}` — check if property is favourited

### Step 5: Register new routers in main.py (commit: `feat: register saved_searches and favourites routers`)

### Step 6: Add frontend API functions (commit: `feat: add saved search and favourites API functions`)

### Step 7: Implement Saved Searches sidebar + Favourites toggle (commit: `feat: add saved searches sidebar and favourites toggle to Properties page`)

### Step 8: Add favourite toggle to PropertyModal (commit: `feat: add favourite toggle to PropertyModal`)

### Step 9: Add styles (commit: `feat: add styles for saved searches sidebar`)

## Validation Plan

1. `bash scripts/agent/validate.sh backend` — lint, unit, integration, contract tests
2. `bash scripts/agent/validate.sh frontend` — frontend build

## Risks and Conflict Surface

- **Low risk**: Entirely additive — no existing code significantly modified
- **Migration**: New tables only, no changes to existing schema
- **Frontend layout**: Sidebar addition requires careful CSS (use flexbox)
- **Single-user**: No auth — `owner` column nullable for future use
