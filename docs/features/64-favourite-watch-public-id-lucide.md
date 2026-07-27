# Favourites/watchlist public_id resolve + lucide Star/Bell icons

> Feature branch: `fix/favourite-watch-uuid-and-icons` · Linear: n/a (regression from BIN-82) · Status: implemented

## Problem

After shareable deep links (BIN-82), the property modal opens on `/properties/<public_id>`. Favourites and watchlist mutations still queried `properties.id = '<digits>'`, which Postgres rejects for UUID columns (`InvalidTextRepresentation` → HTTP 500). Card/modal action icons also used mismatched emoji (star vs chart/bell) at inconsistent sizes.

## Approach

- Shared `api.property_refs.resolve_property_uuid` accepts sequential `public_id` or UUID (same rules as `/properties/{id}`).
- Favourites and watchlist add/check/delete resolve refs before SQL; responses always return the UUID `property_id`.
- Modal mutations prefer `property.id` from the loaded detail payload.
- Use already-declared **lucide-react** `Star` / `Bell` with outline vs filled (`fill="currentColor"`) at a fixed 18px size.

## Changes

Files touched:

```
 src/api/property_refs.py                               | NEW — parse/resolve public_id|UUID
 src/api/properties.py                                  | USE shared parse_property_ref
 src/api/favourites.py                                  | FIX resolve public_id before write/check
 src/api/watchlist.py                                   | FIX resolve public_id before write/check
 src/tests/unit/test_property_refs.py                   | NEW — parse unit tests
 src/tests/unit/test_owner_scoped_personalization.py    | ADD public_id favourite/watchlist cases
 frontend/src/pages/Properties.jsx                      | USE lucide Star/Bell on cards
 frontend/src/components/PropertyModal.jsx              | USE lucide + mutationId from detail
 frontend/src/index.css                                 | Equal-size icon button chrome
 frontend/tests/e2e/compare-select.spec.js              | UPDATE icon regression
 docs/features/64-favourite-watch-public-id-lucide.md   | NEW — this doc
```

## New Dependencies

None (lucide-react was already in `frontend/package.json`).

## How to Test

1. Open a property via deep link `/properties/<public_id>` → star and bell should toggle without 500.
2. Same from card actions (UUID path) still works.
3. Icons: outline when off, filled amber when on; same visual size.
4. Automated:
   ```bash
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- Price-drop **notifications** are configured under `alerts:` in `configs/app_config.yaml` (`channels: log|redis|email`, SMTP / digest settings). Watching a property only registers the watchlist row; alerts fire when scrapers/dedupe detect a drop past `min_drop_pct` (modal “Alert at %”). Frontend can poll Redis via the alerts channel when `redis` is enabled.
- Rebuild the Docker `api` image after this change before trusting local UI against compose.
