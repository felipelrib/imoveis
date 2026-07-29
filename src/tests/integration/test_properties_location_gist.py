"""Integration: GIST index on properties.location (BIN-121)."""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    """DB session on the isolated test database (BIN-71)."""
    yield wipe_safe_db_session


def test_properties_location_gist_index_exists(db_session):
    """Alembic head must create ix_properties_location_gist (GIST)."""
    row = db_session.execute(
        text(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'properties'
              AND indexname = 'ix_properties_location_gist'
            """
        )
    ).fetchone()
    assert row is not None, "expected ix_properties_location_gist after migrations"
    indexdef = row.indexdef.lower()
    assert "using gist" in indexdef
    assert "location" in indexdef
