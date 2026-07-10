# PYTHON BACKEND RULES — Portable to Any Python + FastAPI + SQLAlchemy Project

## SQLAlchemy / Database

- Always parameterize queries. NEVER use f-strings or string concatenation for SQL.
- Every new model requires an Alembic migration. Every migration must include
  BOTH `upgrade()` AND `downgrade()`.
- Test both migration directions: `alembic upgrade head` AND `alembic downgrade -1`.
- Use `mapped_column()` (SQLAlchemy 2.0 style), not the deprecated `Column()`.
- Models live in `src/adapters/db/models.py` (or equivalent). Do not scatter
  ORM definitions across modules.

## Pydantic v2 / FastAPI

- Use Pydantic v2 patterns: `model_validate()`, `model_dump()`, not
  `.parse_obj()` or `.dict()`.
- Response models must be explicit: every route annotates `response_model=...`.
- Async route handlers use `async def`; synchronous utility functions use
  plain `def`.
- Dependency injection via FastAPI `Depends()`, never global singletons.
- Catch validation errors at the API boundary and return structured error
  responses — never let Pydantic `ValidationError` propagate as a 500.

## Configuration

- All settings come from `AppConfig` (Pydantic model loaded from YAML + env).
  Never call `os.getenv()` directly outside of `config.py`.
- Secrets (passwords, API keys) have empty-string defaults in the config model.
  They must be supplied via env vars at runtime.
- The config singleton is cached via `@lru_cache`. In tests, remember to clear
  the cache between config changes (see guardrails.md #13).

## Logging

- Use `structlog` or `logging.getLogger(__name__)` — never `print()`.
- Log at appropriate levels: `logger.debug` for internal flow, `logger.info`
  for key events (scrape started, property created), `logger.warning` for
  recoverable issues, `logger.error` for failures.
- Include structured context: `logger.info("property_created", property_id=id)`,
  not `logger.info(f"Created property {id}")`.

## Testing

- TDD loop: write test → see it fail → implement → see it pass.
- Unit tests: use SQLite in-memory (no PostGIS dependency), mock external
  services (Redis, Ollama).
- Integration tests: use real PostGIS + Redis via `DATABASE_URL` and `REDIS_URL`
  env vars. Skip if services unavailable.
- Fixtures must clean up: truncate all tables in reverse foreign-key order in
  teardown. Use `engine.connect()` / `session.close()` patterns.
- Use `pytest.mark.unit`, `pytest.mark.integration`, `pytest.mark.e2e`,
  `pytest.mark.slow` markers consistently.

## Imports

- Use `from __future__ import annotations` in all new Python files.
- Standard library imports first, then third-party, then local (isort
  `profile = "black"`).
- Never use `import *` except in `__init__.py` re-exports.
