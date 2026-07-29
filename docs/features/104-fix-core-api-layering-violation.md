# Fix core→api Layering Violation in top_deals_digest.py — move shared row-mapping into core

> Feature branch: `fix/core-api-layering-violation` · Linear: `BIN-134` · Status: implemented

## Problem

`src/core/top_deals_digest.py` imported `LIST_SELECT_COLUMNS` and `map_property_list_item` from `api.property_projection`. That inverts the documented architecture (`src/core/` = business logic; `src/api/` = presentation layer sitting above core/adapters per `CLAUDE.md`'s repository map). `api/property_projection.py` itself already imported from `core.ai_locale` and `core.neighbourhood_quality`, so core↔api had become a two-way dependency — one hop from an actual circular import.

Failure scenario: any refactor of API response shaping (`LIST_SELECT_COLUMNS`, `map_property_list_item`) would directly change core business-logic behavior (top-deals digest selection), and `core.top_deals_digest` could no longer be unit-tested/imported in isolation without pulling in FastAPI-adjacent modules — violating the project's own risk-tiered "pure domain should be TDD'd in isolation" testing philosophy.

## Approach

- Audited `api/property_projection.py`: it has zero FastAPI-specific dependencies (no `fastapi`/`pydantic` route wiring, just row-mapping/serialization helpers operating on plain dicts and DB row mappings). It only depends on `core.ai_locale` and `core.neighbourhood_quality`, both already inside `core`.
- Moved the whole module to `src/core/property_projection.py` (`git mv`, preserving history) rather than splitting a "shared" subset — the entire file is core-appropriate business logic (primary-listing selection, decisioning price, neighbourhood field projection, AD-12 serializers, shared SQL fragments), not presentation glue.
- Updated both consumers to import from `core.property_projection`: `src/core/top_deals_digest.py` (the layering violation) and `src/api/properties.py` (which already depended on the same module, now via the correct direction).
- No behavior change: this is a pure code-motion refactor. Existing unit tests (`test_property_projection.py`, `test_properties_response_schema.py`, `test_top_deals_digest.py`, `test_schedule.py`) all pass unchanged after the move — they serve as the characterization lock proving `map_property_list_item`/`map_property_detail`/`select_top_deals` output didn't change.
- Added `src/tests/unit/test_core_api_layering.py`: an AST-based test that walks every `.py` file under `src/core` and asserts none of them `import api` / `from api import ...` / `from api.x import ...`, so this violation can't silently reappear in this or any other core module.

## Changes

Files touched:

```
src/api/property_projection.py -> src/core/property_projection.py | MOVED — pure row-mapping/serialization has no FastAPI dependency, belongs in core
src/core/top_deals_digest.py                                      | import LIST_SELECT_COLUMNS / map_property_list_item from core.property_projection instead of api.property_projection
src/api/properties.py                                             | import from core.property_projection instead of api.property_projection
src/tests/unit/test_property_projection.py                        | updated imports (module import + one inline test import) to core.property_projection
src/tests/unit/test_properties_response_schema.py                 | updated import to core.property_projection
src/tests/unit/test_core_api_layering.py                          | NEW — AST-based lock asserting src/core never imports from src/api
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
```

Targeted characterization + new lock:

```bash
PYTHONPATH=.:src python -m pytest src/tests/unit/test_core_api_layering.py src/tests/unit/test_property_projection.py src/tests/unit/test_properties_response_schema.py src/tests/unit/test_top_deals_digest.py src/tests/unit/test_schedule.py -v
```

`test_core_api_layering.py::test_core_module_does_not_import_api` is parametrized over every module under `src/core`; it will fail immediately (naming the offending file and the imported name) if a future change reintroduces a `core -> api` import anywhere in the package, not just in `top_deals_digest.py`.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone).
- Epic parent: BIN-128.
- BIN-134 explicitly blocks BIN-135 (f-string SQL fragments in the same `top_deals_digest.py` file) — this refactor was landed first so BIN-135 doesn't have to rebase its SQL change on top of a moved import.
- `api/property_projection.py` no longer exists; any external doc/reference to that path (several older `docs/features/*.md` entries predate this move) is historical and not updated — those docs describe the state at the time they were written, per this project's append-only feature-doc convention.
