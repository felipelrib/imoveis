---
paths:
  - "src/**"
  - "alembic/**"
  - "requirements.txt"
---

# Python Backend Rules

## SQLAlchemy / Database

- Always parameterize queries. NEVER use f-strings or string concatenation for SQL.
- Every new model requires an Alembic migration with BOTH `upgrade()` AND `downgrade()`.
- Test both directions: `alembic upgrade head` AND `alembic downgrade -1`.
- Use `mapped_column()` (SQLAlchemy 2.0 style), not the deprecated `Column()`.
- Models live in `src/adapters/db/models.py`. Do not scatter ORM definitions.

## Pydantic v2 / FastAPI

- Use Pydantic v2: `model_validate()`, `model_dump()`, not `.parse_obj()` or `.dict()`.
- Every route annotates `response_model=...`.
- Async handlers use `async def`; sync utilities use plain `def`.
- Dependency injection via `Depends()`, never global singletons.
- Catch `ValidationError` at the API boundary — never let it propagate as a 500.

## Configuration

- All settings from `AppConfig` (Pydantic model from YAML + env). Never `os.getenv()` outside `config.py`.
- Secrets have empty-string defaults. Supplied via env vars at runtime.
- Config singleton cached via `@lru_cache`. Clear cache between config changes in tests.

## Logging

- Use `structlog` or `logging.getLogger(__name__)` — never `print()`.
- Appropriate levels: `debug` for flow, `info` for key events, `warning` for recoverable, `error` for failures.
- Structured context: `logger.info("property_created", property_id=id)`, not f-strings.

## Imports

- `from __future__ import annotations` in all new Python files.
- Standard library → third-party → local (isort `profile = "black"`).
- Never `import *` except in `__init__.py` re-exports.
