# config-yaml-loader — Wire `app_config.yaml` into runtime config

> Feature branch: `feat/config-yaml-loader` · Status: implemented

## Problem

`src/infra/config.py` returned hardcoded defaults and never read the YAML config file. Every tunable (rate limits, dedup thresholds, AI model/backend, proxy settings) was inert, and `test_config.py` failed on import.

## Approach

- Rewrote `src/infra/config.py` with **Pydantic v2** frozen models matching every section of `configs/app_config.yaml`
- YAML loaded via `PyYAML.safe_load()`, validated through `AppConfig.model_validate()`
- **Environment variable overrides**: `DATABASE_URL`, `REDIS_URL`, `AI_MODEL` shorthand, plus generic `IMOVEIS_<SECTION>__<KEY>` pattern with type coercion
- **Singleton caching**: `@lru_cache(maxsize=1)` on `get_config()`; `load_config(path)` for tests/custom paths
- Created `src/core/exceptions.py` with `ConfigError` base exception
- Fixed `src/core/__init__.py` with deferred imports to avoid circular import chain

## Changes

Files touched:

```
 src/core/__init__.py     | deferred imports (avoid circular chain)
 src/core/exceptions.py   | NEW — ConfigError + base exceptions
 src/infra/config.py      | REWRITTEN — Pydantic models, YAML loader, env overrides, singleton
 src/tests/unit/test_config.py | REWRITTEN — 17 unit tests
 FEATURES.md              | status updated to done
```

## New dependencies

None — `pyyaml` and `pydantic>=2.0` were already in `requirements.txt`.

## How to test

1. Run from the worktree root:
   ```
   python -m pytest .worktrees/config-yaml-loader/src/tests/unit/test_config.py -v --rootdir .worktrees/config-yaml-loader --override-ini="testpaths=src/tests"
   ```
2. All 17 tests should pass, covering: happy path, missing file, invalid YAML, env overrides, singleton caching, frozen models.

## Notes / follow-ups

- The new `AppConfig` attribute paths differ from the old dataclass (e.g., `cfg.database.host` instead of `cfg.database_url`). Downstream consumers (`dedupe.py`, `ai/client.py`, scrapers) will need import updates in subsequent features.
- `src/core/__init__.py` now uses `__getattr__` for lazy imports — existing code that does `from core import PropertyCandidate` will still work but only triggers the import at access time.