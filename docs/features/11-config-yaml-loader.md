# config-yaml-loader — Typed YAML configuration with Pydantic v2 and env-variable overrides

> Feature branch: `feat/config-yaml-loader` · Linear: `BIN-XX` · Status: implemented

## Problem

`src/infra/config.py` returned hardcoded defaults and never read `configs/app_config.yaml`.
Every tunable parameter (rate limits, dedup thresholds, AI model/backend, proxy settings)
was inert at runtime. The downstream test suite (`test_config.py`) failed on import due to
missing field references.

## Approach

- **Pydantic v2 frozen models** (`AppConfig`, `DatabaseConfig`, `AIConfig`, `ScrapingConfig`, etc.)
  that map 1-to-1 with every section of `configs/app_config.yaml`.
- **YAML loading** via `PyYAML.safe_load()`, validated through `AppConfig.model_validate()`.
  A `ConfigError` is raised on missing file, invalid YAML, or schema violations.
- **Environment variable overrides** applied after YAML in priority order:
  1. `DATABASE_URL` → parsed into `database.*` fields
  2. `REDIS_URL` → parsed into `redis.*` fields
  3. `AI_MODEL` / `AI_TEXT_MODEL` → `ai.visual_model` / `ai.text_model`
  4. `OLLAMA_HOST` → `ai.ollama_url`
  5. Generic `IMOVEIS_<SECTION>__<KEY>` with automatic type coercion (bool, int, float)
- **Singleton caching** via `@lru_cache(maxsize=1)` on `get_config()`. `load_config(path)`
  is the uncached escape hatch used in tests and custom scenarios.
- `src/core/exceptions.py` was added with `ConfigError` so the rest of the application
  has a typed exception to catch.

## Changes

Files touched:

```
 src/infra/config.py               | REWRITTEN — Pydantic v2 models, YAML loader, env overrides, singleton
 src/core/exceptions.py            | NEW — ConfigError + CircuitBreakerOpenError base exceptions
 src/core/__init__.py              | Deferred imports to break circular dependency chain
 src/tests/unit/test_config.py     | REWRITTEN — 17 unit tests covering happy path, missing file, invalid YAML, env overrides, singleton caching, frozen model
```

## New Dependencies

None — `pyyaml` and `pydantic>=2.0` were already in `requirements.txt`.

## How to Test

```bash
python -m pytest src/tests/unit/test_config.py -v
```

All 17 tests cover: YAML loading, missing file, invalid YAML, env variable overrides,
singleton caching, and frozen model immutability.

## Notes / Follow-ups

- **Downstream attribute path change**: `cfg.database.host` instead of the old `cfg.database_url`.
  All consumers (`dedupe.py`, `ai/client.py`, scrapers) must use the new nested paths.
- **`AppConfig` is frozen**: Mutating a field at runtime raises `ValidationError`. Tests that
  need to change config must call `load_config(path=...)` with a custom YAML fixture instead
  of monkeypatching the singleton.
- **`ScoringWeights` and `ScoringConfig`** live in `core/entities.py` but are referenced by
  `infra/config.py`'s `AppConfig`. A circular import risk exists if `core/` ever imports
  `infra/config.py` directly — the current deferred `__getattr__` pattern in `core/__init__.py`
  mitigates this.
- **No hot-reload**: Config is loaded once per process. Changing `app_config.yaml` while the
  server is running has no effect until restart.
