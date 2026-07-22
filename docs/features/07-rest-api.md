# REST API — FastAPI application serving property queries, admin controls, and user features

> Feature branch: `feat/rest-api` · Linear: `BIN-XX` · Status: implemented

## Problem

The React frontend and external clients need a comprehensive REST API to query properties, manage user preferences (favourites, watchlist, saved searches), trigger scrapes, and control system behaviour (worker pause, GPU scaling, score recalculation, schedule management).

## Approach

- **FastAPI with router decomposition**: Endpoints are organized into 7 router modules:
  - `api/properties.py` — Property listing, detail, neighborhoods, price history
  - `api/admin.py` — Worker management, GPU scaling, scoring, schedule (API-key protected)
  - `api/system.py` — Health checks, pipeline telemetry, Ollama management
  - `api/watchlist.py` — Watchlist CRUD
  - `api/favourites.py` — Favourites CRUD
  - `api/saved_searches.py` — Saved search CRUD
  - `api/auth.py` — API key verification via `X-API-Key` header

- **Rich property queries**: `GET /properties` supports 12+ filter parameters (platform, price, bedrooms, parking, neighbourhood, listing type, property type, furnished, pets, score, bbox) with sort and pagination.

- **Geospatial queries**: `bbox` parameter enables map-based property discovery using `ST_Within` + `ST_MakeEnvelope`.

- **Admin API protection**: All `/admin/*` endpoints require `X-API-Key` header validated against `API_KEY` env var.

- **System health aggregation**: `/system/status` probes DB, Redis, and Ollama in one call for the dashboard service status panel.

## Changes

Files touched:

```
 src/api/main.py          | FastAPI app, CORS, /scrape, /platforms, /health
 src/api/properties.py    | GET /properties, GET /properties/:id, GET /neighborhoods, GET /price-history
 src/api/admin.py         | POST /admin/workers/pause|resume, POST /admin/gpu/scale, POST /admin/scoring/*, GET|POST /admin/schedule
 src/api/system.py        | GET /system/status, GET /system/pipeline, POST /system/ollama/ensure
 src/api/watchlist.py     | CRUD /watchlist
 src/api/favourites.py    | CRUD /favourites
 src/api/saved_searches.py| CRUD /saved-searches
 src/api/auth.py          | API key verification dependency
```

## New Dependencies

None beyond FastAPI core.

## How to Test

1. Start the API:
   ```bash
   uvicorn api.main:app --reload --port 8000
   ```
2. Browse API docs at `http://localhost:8000/docs`
3. Test property query:
   ```bash
   curl 'http://localhost:8000/properties?page=1&page_size=5&sort_by=combined_score&sort_dir=desc'
   ```

## Notes / Follow-ups

### Bugs Found

- **[FIXED] BUG (Critical): Column index mismatch in `list_properties`** (properties.py L176-224): The SQL SELECT has 27 columns but the Python indexing is wrong:
  - `row[11]` mapped to `address` but column 11 is `first_seen`
  - `row[12]` mapped to `image_urls` but column 12 is `stat_score`
  - `row[13]` mapped to `created_at` but column 13 is `ai_score`
  - All subsequent row indices are off by 3, causing **all scoring fields to display wrong values** on the property cards. `stat_score`, `ai_score`, `combined_score` will show `address`, `image_urls`, `first_seen` values respectively.

- **[FIXED] BUG (Moderate): f-string SQL injection surface** (properties.py L68, L75): Lines like `f"(p.props_json->>'available_for_{listing_type}')::boolean"` and `f"...'{is_furnished}'"` directly interpolate user input into SQL. While FastAPI validates `listing_type` via regex `^(rent|sale|both)$`, `is_furnished` is a boolean and doesn't go through f-string. However, the pattern is dangerous and should use parameterized queries for all values.

- **[FIXED] BUG (Moderate): Session leak on exceptions** (properties.py L36-235): `list_properties` creates `session = SessionLocal()` and relies on `finally: session.close()`, but if an exception occurs before the `try` block (e.g., in parameter processing), the session is never closed. Should use `with SessionLocal() as session:` or a dependency injection pattern.

- **[FIXED] BUG (Minor): `saved_searches.filters` stored as Python dict, not JSON** (saved_searches.py L99): The raw SQL `INSERT` passes `req.filters` (a Python dict) as `:filters`. Whether this works depends on the PostgreSQL driver and column type (`JSONB`). It should explicitly serialize with `json.dumps()`.

- **[FIXED] BUG (Minor): `/scrape` only imports `quintoandar`** (main.py L85): The comment says "Import scrapers so they self-register" but only imports `quintoandar`, not `olx`. OLX scraper will never be available.

### Tech Debt

- **No OpenAPI response models** — Most endpoints return untyped dicts, losing API documentation benefits.
- **Sync database sessions in async FastAPI** — All endpoints use `SessionLocal()` synchronously, blocking the event loop. Should use async sessions or run in thread pool.
- **No rate limiting on public endpoints** — Anyone can query `/properties` at high rates.
- **CORS allows `*` methods/headers** — Over-permissive for production.
- **`/system/ollama/ensure` uses `subprocess.Popen`** — Security risk: if an attacker can somehow influence the command, this is a shell injection vector.
