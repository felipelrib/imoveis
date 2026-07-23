# Owner-scoped favourites, searches & watchlist — Principal.id owns personalization rows

> Feature branch: `feat/bin-45-owner-scoped-favourites` · Linear: `BIN-45` · Status: implemented

## Problem

Favourites and saved searches had nullable UUID `owner` columns that were never written or filtered; watchlist used JWT `user_id` (missing from Alembic) while the SPA only sends `X-API-Key`. Nullable owner columns were not meaningful for digests or multi-principal isolation (AD-11 / FR-19).

## Approach

- Align `owner` to `String` matching `AuthConfig.principal_id` / `Principal.id` (default `"default"`).
- Require `verify_api_key` on `/favourites`, `/saved-searches`, and `/watchlist`; all CRUD filters/writes by `owner = principal.id`.
- Migrate watchlist off JWT/`user_id` onto `owner`; unique constraints become `(owner, property_id)`.
- Attribute existing single-tenant null/legacy rows to `"default"` in the migration.
- SPA favourites and saved-searches helpers use `apiFetch` so the credential gate attaches `X-API-Key`.
- Alert workers still evaluate all watchlist rows by `property_id` (system-wide); ownership is API-scoped only.

## Changes

Files touched:

```
 alembic/versions/a1b2c3d4e5f6_owner_scoped_personalization.py | NEW — owner String, watchlist owner, uniques, backfill
 src/adapters/db/models.py                                   | Favourite/SavedSearch/Watchlist owner String + uniques
 src/api/favourites.py                                       | verify_api_key + owner scope
 src/api/saved_searches.py                                   | verify_api_key + owner scope
 src/api/watchlist.py                                        | API key + owner; drop JWT/user_id
 frontend/src/api.js                                         | favourites/saved-searches via apiFetch
 src/tests/unit/test_owner_scoped_personalization.py         | NEW — 401 + isolation
 src/tests/integration/test_owner_scoped_personalization.py  | NEW — Postgres roundtrip
 docs/features/10-favourites-and-saved-searches.md           | Auth note
 docs/features/17-watchlist-price-drop-alerts.md             | Owner note
 docs/features/30-appconfig-api-credential.md                | Story 2.3 done
 _bmad-output/.../sprint-status.yaml                         | 2-3 done
```

## New Dependencies

None.

## How to Test

1. With `API_KEY` set and migrations applied:
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/favourites
   # 401
   curl -s -H "X-API-Key: $API_KEY" http://localhost:8000/favourites
   # 200
   ```
2. Add a favourite / watchlist entry with the key; confirm `owner` equals `auth.principal_id` in Postgres.
3. Automated:
   ```bash
   bash scripts/agent/validate.sh backend
   ```

## Notes / Follow-ups

- **Attribution**: migration sets `owner = 'default'` for null favourites/saved_searches; watchlist uses `COALESCE(user_id, 'default')` when a drifted `user_id` column exists, else `'default'`.
- Digest subscriptions (Epic 4) can subscribe using the same `Principal.id` / `owner` key.
- Multi-profile login (open FR-19 question) remains out of scope.
