# Export filtered properties (API) — CSV/JSON shortlist export

> Feature branch: `feat/bin-50-export-filtered-properties-api` · Linear: `BIN-50` · Status: implemented

## Problem

House-hunters need to share or archive a filtered property shortlist outside the app. Without an API-owned export, clients would invent ad-hoc flatteners that diverge from compare/grid (violating AD-12) or hit the DB directly (violating AD-8).

## Approach

- Add `GET /properties/export?format=csv|json` with the same filter surface as `GET /properties` (no pagination).
- Reuse `_build_list_filters`, `_LIST_SELECT_COLUMNS`, and `map_property_list_item` so export is the AD-12 projection (same primary listing, price/m², scores, neighbourhood fields).
- Cap at 5000 rows; JSON reports `truncated` when more match. CSV uses a stable column set with `primary_listing_*` prefixes and JSON-encoded list fields.
- Auth via `verify_api_key_if_configured`: require `X-API-Key` only when `auth.api_key` is set (Epic 2 edge rules).

## Changes

Files touched:

```
 src/api/auth.py                         | ADD verify_api_key_if_configured
 src/api/property_export.py              | NEW — CSV/JSON serializers over AD-12 dicts
 src/api/properties.py                   | ADD GET /properties/export + PropertyExportFilters
 src/api/schemas.py                      | ADD PropertyExportResponse
 src/tests/unit/test_auth.py             | ADD optional-key unit tests
 src/tests/unit/test_property_export.py  | NEW — serializer unit tests
 src/tests/contract/test_api_contract.py | ADD export contract tests
 docs/features/35-export-filtered-properties-api.md | NEW — this doc
 _bmad-output/implementation-artifacts/sprint-status.yaml | Story 4.1 + epic-4 progress
```

## New Dependencies

None.

## How to Test

1. Unit + contract (via agent gate):
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual (API up, optional `API_KEY`):
   - `GET /properties/export?format=json&max_price=5000` → `{ properties, total, truncated }` with AD-12 keys.
   - `GET /properties/export?format=csv` → downloadable CSV with header + `primary_listing_price`.
   - `GET /properties/export?format=xml` → 422.

## Notes / Follow-ups

- BIN-51 (Story 4.2) should wire Properties UI Export actions through `api.js` to this endpoint.
- Digest (BIN-52) must also consume AD-12 fields, not invent a second shape.
- Cap is hard-coded at 5000; promote to AppConfig if operators need a higher dump limit.
