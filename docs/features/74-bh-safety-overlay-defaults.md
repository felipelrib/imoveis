# BH defaults for safety overlay loader — operator-city consistency

> Feature branch: `feat/bh-safety-overlay-defaults` · Linear: n/a (follow-up to BIN-96) · Status: implemented

## Problem

After BH-first crime rates (BIN-96), `safety_overlay` and `load_safety_overlays.py` still defaulted to São Paulo / SSP-SP attribution when city/provider were omitted — easy to mis-stamp BH runs.

## Approach

- Module defaults: `DEFAULT_CITY=Belo Horizonte`, `DEFAULT_STATE=MG`, `DEFAULT_PROVIDER=sejusp-mg-regional`, BH attribution.
- CLI `--city` / `--state` defaults match.
- SP fixtures keep explicit SSP provider; regression tests lock BH defaults.

## Changes

Files touched:

```
 src/core/safety_overlay.py                        | BH module defaults
 scripts/dev/load_safety_overlays.py               | CLI defaults BH/MG
 src/tests/unit/test_safety_overlay.py             | SP literals + BH default regression
 src/tests/integration/test_safety_overlays.py     | SP provider assert literal
 docs/features/74-bh-safety-overlay-defaults.md    | NEW — this doc
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh fast
PYTHONPATH=src python scripts/dev/load_safety_overlays.py \
  --rates configs/bh_safety_rates.yaml --dry-run
```

## Notes / Follow-ups

- SP remains supported when rates YAML sets `defaults.city` / `provider` explicitly.
