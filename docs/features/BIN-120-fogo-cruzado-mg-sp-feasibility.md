# Fogo Cruzado MG/SP feasibility — armed-violence overlay parked

> Feature branch: `feat/bin-120-fogo-cruzado-overlay` · Linear: `BIN-120` · Status: implemented

## Problem

Feature 72 parked Fogo Cruzado as a possible armed-violence grain for MG/SP beyond curated/open-data rates. Before ingest, we need a hard feasibility call on API coverage and terms so we never invent gunfire numbers for Belo Horizonte or São Paulo.

## Approach

- Re-read [Fogo Cruzado API docs](https://api.fogocruzado.org.br/docs) and homepage: coverage is **RJ, PE (Recife metro), BA, PA only** — not MG/SP.
- Access requires prior authorization + JWT; terms are presented after the access form. `/states` is auth-gated (401 without credentials).
- **Decision (BIN-120):** do **not** ingest Fogo Cruzado into `safety_score` / `quality_meta.safety` for operator cities. Keep SEJUSP (BH) and SSP-SP loaders.
- Lock the decision in `core.fogo_cruzado_coverage` so a future client cannot silently treat MG/SP as covered. Never invent rates from listing AI prompts.

## Changes

Files touched:

```
 src/core/fogo_cruzado_coverage.py                    | NEW — covered UF codes + supports_state / assert_supported_for_overlay
 src/tests/unit/test_fogo_cruzado_coverage.py         | NEW — MG/SP rejected; RJ/PE/BA/PA accepted
 docs/features/BIN-120-fogo-cruzado-mg-sp-feasibility.md   | NEW — this doc
 docs/features/BIN-92-crime-safety-open-data.md           | UPDATE — spike row + follow-up → BIN-120 decision
```

## New Dependencies

None.

## How to Test

1. Unit gate:
   ```bash
   bash scripts/agent/validate.sh fast
   ```
2. Or directly:
   ```bash
   PYTHONPATH=src pytest src/tests/unit/test_fogo_cruzado_coverage.py -q
   ```

## Notes / Follow-ups

- If Fogo Cruzado later expands into MG/SP, reopen with a new ticket: update `COVERED_STATE_CODES`, obtain API authorization, then design point→neighbourhood aggregation + attribution — do not reuse invented listing text.
- RJ/PE/BA/PA ingest remains out of scope while operator cities are BH/SP only.
- Related: BIN-92 (crime open-data), BIN-96 (BH rates), feature [72](BIN-92-crime-safety-open-data.md).
