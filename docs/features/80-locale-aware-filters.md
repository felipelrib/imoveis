# Locale-aware filters — PT labels + EN canonical wire

> Feature branch: `feat/bin-100-locale-aware-filters` · Linear: `BIN-100` · Status: implemented

## Problem

Operators filtering in Portuguese need localized option labels (Apartamento / Aluguel / Mobiliado / Aceita pets) while the API, DB, and saved-search JSON stay English canonical enums. Listing-type PT synonyms existed only at ingest; saved searches posted camelCase keys that the API ignored (`extra="ignore"`), so reopen lost filter state.

## Approach

- **Canonical store / localized present:** UI labels come from the string catalog (`t()`); select/checkbox **values** and query params stay EN (`rent`, `apartment`, …). Neighbourhood and city remain proper-noun `ILIKE` matches — never translated.
- Extend the property-type synonym pattern with `core/listing_type.py` for `listing_type` / `price_type` (`aluguel`→`rent`, `venda`→`sale`, `ambos`→`both`). Pydantic `BeforeValidator` normalizes before EN pattern checks on list/export filters.
- Saved searches persist **snake_case EN** JSON via `SavedSearchFilters.to_wire()`; accept camelCase + legacy `furnished`/`pets`/`neighbourhood` on write. SPA `toSavedSearchWire` / `fromSavedSearchWire` round-trip both shapes so labels re-localize on reopen.
- Pets filter keeps matching QuintoAndar amenity key `PODE_TER_ANIMAIS_DE_ESTIMACAO` internally — never exposed in UI.
- Platforms stay brand names (OLX / QuintoAndar).

### Synonym tables (API free-text / query aliases)

| Param | PT / alt aliases | Canonical |
|---|---|---|
| `property_type` | apartamento, casa, kitnet, … | apartment / house / condo_house / studio |
| `listing_type` | aluguel, alugar, venda, vender, comprar, ambos | rent / sale / both |
| `price_type` | aluguel, venda, comprar, … | rent / sale |

## Changes

Files touched:

```
 src/core/listing_type.py                              | NEW — PT→EN listing/price normalize
 src/api/properties.py                                 | BeforeValidator on listing_type/price_type
 src/api/saved_searches.py                             | camelCase aliases + EN snake wire dump
 src/tests/unit/test_listing_type.py                   | NEW — synonym + filter model tests
 src/tests/unit/test_saved_search_filters.py           | NEW — wire round-trip tests
 frontend/src/savedSearchFilters.js                    | NEW — to/from saved-search wire
 frontend/src/pages/Properties.jsx                     | wire helpers + filter testids
 frontend/tests/e2e/locale-filters.spec.js             | NEW — PT labels + EN params + save/reopen
 docs/features/80-locale-aware-filters.md              | NEW — this doc
 _bmad-output/.../sprint-status.yaml                   | 8-4 → done
```

## New Dependencies

None.

## How to Test

1. Full gate:
   ```bash
   bash scripts/agent/validate.sh all
   ```
2. Manual: switch Language to Português → Properties filter options show Apartamento / Somente aluguel / Mobiliado; DevTools Network still shows `listing_type=rent&property_type=apartment`. Save filters, clear, reopen — labels stay PT, wire stays EN. Neighbourhood names are unchanged proper nouns.

## Notes / Follow-ups

- BIN-101: localize AI tags / verdicts / score payload copy.
- BIN-103: multi-locale extensibility checklist — see `docs/i18n/add-a-locale.md` / `docs/features/83-product-i18n.md`.
- Pets SQL still QuintoAndar-amenity-only; OLX `accepts_pets` column is out of scope for this ticket.
