# Canonical property projection — AD-12 decisioning DTO for compare/export

> Feature branch: `feat/bin-41-canonical-property-projection` · Linear: `BIN-41` · Status: implemented

## Problem

Compare (and later export/digest) need one stable property shape — primary listing, price/m², scores, neighbourhood id/label, enrichment — but the API exposed denormalized `p.price` without a primary listing, omitted `neighborhood_id`, and left “best price” selection in React (`groupListings` / min price). That violates AD-12 and would force competing flatteners in Stories 1.2–1.3 / Epic 4.

## Approach

- Centralize selection and serialization in `api/property_projection.py` (shared by list, detail, batch).
- Primary listing rule: lowest non-null price; ties prefer `rent` over `sale`, then `platform` ascending. Top-level `price` follows the primary listing when present.
- Add `neighborhood_id` + `primary_listing` to list and detail DTOs; keep full `listings[]`.
- Add `GET /properties/by-ids?ids=` (1–4 UUIDs) returning the list projection in request order for compare.
- Minimal frontend: `fetchPropertiesByIds` in `api.js` only (grid still uses local grouping until BIN-42/43).

## Changes

Files touched:

```
 src/api/property_projection.py              | NEW — primary listing + list/detail mappers
 src/api/schemas.py                          | ADD neighborhood_id, primary_listing, PropertyBatchResponse
 src/api/properties.py                       | USE projection; SQL neighborhood_id; GET /by-ids
 frontend/src/api.js                         | ADD fetchPropertiesByIds
 src/tests/unit/test_property_projection.py  | NEW — unit coverage for AD-12 rules
 src/tests/contract/test_api_contract.py     | ADD projection + batch contract tests
 docs/features/26-canonical-property-projection.md | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | Story 1.1 + epic-1 progress
```

## New Dependencies

None.

## How to Test

1. Unit + contract (via agent gate):
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual (API up): `GET /properties?page=1&page_size=1` — each item has `primary_listing`, `neighborhood_id`, scores, `price_per_m2`.
3. Manual batch: `GET /properties/by-ids?ids=<id1>,<id2>` — `{ "properties": [...] }` in request order; `ids=` or 5 ids → 400.

## Notes / Follow-ups

- BIN-42 / BIN-43 should consume `/by-ids` and prefer `primary_listing` instead of React `groupListings` for decisioning price.
- Grid/modal still flatten locally for display tables; migrate when compare lands.
- Export/digest (Epic 4 / BIN-50+) must reuse this projection (AD-12), not invent a second shape.
