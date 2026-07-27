# Property deep links — Shareable URLs for property, favourites, and compare

> Feature branch: `feat/bin-82-property-deep-links` · Linear: `BIN-82` · Status: implemented

## Problem

Property detail (modal), favourites view, and side-by-side compare lived only in React state. Users could not copy a URL to reopen a property, the favourites list, or a specific comparison set. Internal UUIDs are awkward to share; there was no sequential public id.

## Approach

- Add `properties.public_id BIGSERIAL`-style unique column (sequence + backfill by `first_seen`) while keeping UUID as the primary key for FKs.
- Drive UI from the router: `/properties/:publicId` opens the modal, `/favourites` shows favourites, `/compare/14,22` opens compare (comma-separated public ids).
- Keep `Properties` mounted via a layout route so compare selection survives “Back to grid”.
- Detail / by-ids / price-history accept either `public_id` (digits) or UUID.
- Fix favourites list load on view enter and map `property_id` + `public_id` onto cards.

## Changes

Files touched:

```
 alembic/versions/d1e2f3a4b5c6_add_property_public_id.py | NEW — public_id column + backfill
 src/adapters/db/models.py                              | Property.public_id
 src/api/property_projection.py                         | expose public_id in list/detail
 src/api/schemas.py                                     | PropertyModel / Detail public_id
 src/api/properties.py                                  | resolve public_id or UUID
 src/api/favourites.py                                  | return public_id on favourites list
 src/api/property_export.py                             | CSV includes public_id
 frontend/src/routes/propertyPaths.js                   | NEW — path helpers (numeric public ids)
 frontend/src/App.jsx                                   | layout routes + nav highlight
 frontend/src/pages/Properties.jsx                      | URL sync via public_id
 frontend/src/hooks/useCompareSelection.js              | replace() + string normalize
 frontend/src/components/CompareView.jsx                | Clear & exit only onClearSelection
 frontend/tests/e2e/deep-links.spec.js                  | NEW — Playwright deep-link coverage
 frontend/tests/e2e/helpers/apiMocks.js                 | public_id on fixtures
 docs/features/62-property-deep-links.md                | this doc
```

## New Dependencies

None.

## How to Test

1. Manual (after migrate):
   - Open a property → URL `/properties/<public_id>`; paste in a new tab opens the modal.
   - Click ★ Favourites → `/favourites`; reload keeps favourites view.
   - Select 2+ → Compare → `/compare/14,22`; reload restores compare.
2. Automated:
   ```bash
   cd frontend && npx playwright test tests/e2e/deep-links.spec.js
   bash scripts/agent/validate.sh all
   ```

## Notes / Follow-ups

- UUID remains the internal PK / FK; `public_id` is shareable only.
- Compare path uses comma-separated public ids; fewer than 2 redirects to `/properties`.
- Related: BIN-43 compare view, BIN-13 favourites.
