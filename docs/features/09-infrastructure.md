# Infrastructure & Configuration — YAML+env config, database setup, Redis integration, logging

> Feature branch: `feat/infrastructure` · Linear: `BIN-XX` · Status: implemented

## Problem

A complex multi-service application needs centralized configuration management, database connection pooling, Redis client management, and structured logging. All of these must be configurable via YAML + environment variable overrides.

## Approach

- **Pydantic v2 configuration** (`AppConfig`): Nested Pydantic models parse `configs/app_config.yaml` with strict validation. Environment variables override specific fields via `dotenv`.
- **Singleton pattern**: `get_config()` returns a cached global `AppConfig` instance. `reset_config()` available for testing.
- **Database layer**:
  - SQLAlchemy 2.0 with `sessionmaker` + `SessionLocal` factory
  - PostGIS via GeoAlchemy2 for spatial operations
  - `get_session()` generator for dependency injection
  - Alembic for migrations (configured separately)
- **Redis client**: `get_redis()` returns a thread-safe Redis connection pool instance. URL defaults to `redis://localhost:6379/0`.
- **Structured logging**: `structlog` configuration via `get_logger()` for machine-parseable JSON log output. Project rules mandate no `print()` calls.

## Changes

Files touched:

```
 src/infra/config.py       | AppConfig Pydantic model, YAML loading, env overrides
 src/infra/db.py            | SQLAlchemy engine, SessionLocal, get_session
 src/infra/redis_client.py  | Redis connection factory
 src/infra/logging.py       | structlog configuration
 configs/app_config.yaml    | Master configuration file
```

## New Dependencies

- `pydantic>=2.0` — Configuration validation
- `pyyaml` — YAML parsing
- `python-dotenv` — Environment variable loading
- `sqlalchemy>=2.0` — ORM
- `psycopg2-binary` — PostgreSQL driver
- `geoalchemy2` — PostGIS integration
- `redis` — Redis client
- `alembic` — Database migrations

## How to Test

1. Verify config loading:
   ```bash
   python -c "from infra.config import get_config; c = get_config(); print(c.model_dump())"
   ```
2. Run config unit tests:
   ```bash
   pytest src/tests/unit/test_config.py -v
   ```

## Notes / Follow-ups

### Bugs Found

- **BUG (Moderate): `AppConfig` schema incomplete** — The YAML has sections (`scoring`, `alerts`, `image_storage_path`) that are not defined in the Pydantic model. Access via `cfg.scoring.stat_weight` will raise `AttributeError` at runtime. The model either needs to be updated or `model_config = {"extra": "allow"}` must be set.

- **BUG (Minor): `api/auth.py` uses `logging.getLogger` instead of `structlog`** (auth.py L1,7): The project rules mandate `structlog` via `infra.logging.get_logger()`, but `auth.py` uses the standard library logger. This breaks structured log aggregation.

- **BUG (Minor): `_api_key` is evaluated at import time** (auth.py L9-12): If `API_KEY` is set after the module is imported (e.g., by a test fixture), the key will be empty and all admin requests will fail.

### Tech Debt

- **No connection pool tuning** — SQLAlchemy engine uses default pool settings. Should configure `pool_size`, `max_overflow`, `pool_timeout` for production.
- **No health check on Redis connection** — `get_redis()` creates a connection but doesn't ping. A bad Redis URL will only fail on first use.
- **Database URL hardcoded in fallback** — If `DATABASE_URL` env var is not set, the code may use a hardcoded development URL.
- **No secret management** — API keys and database passwords are plain environment variables.
