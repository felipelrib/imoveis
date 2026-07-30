"""Integration: indexes on properties.active and metrics_scoring.property_id (BIN-152)."""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.fixture(scope="function")
def db_session(wipe_safe_db_session):
    """DB session on the isolated test database (BIN-71)."""
    yield wipe_safe_db_session


def _index_row(db_session, tablename: str, indexname: str):
    return db_session.execute(
        text(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = :tablename
              AND indexname = :indexname
            """
        ),
        {"tablename": tablename, "indexname": indexname},
    ).fetchone()


def test_properties_active_index_exists(db_session):
    """Alembic head must create ix_properties_active (full, non-partial btree).

    properties.active is ~97% true in production (BIN-152 distribution check),
    so a partial index scoped to WHERE active would cover nearly the whole
    table anyway — a plain index is used instead.
    """
    row = _index_row(db_session, "properties", "ix_properties_active")
    assert row is not None, "expected ix_properties_active after migrations"
    indexdef = row.indexdef.lower()
    assert "using btree" in indexdef
    assert "(active)" in indexdef
    assert "where" not in indexdef  # not a partial index


def test_metrics_scoring_property_id_index_exists(db_session):
    """Alembic head must create ix_metrics_scoring_property_id (btree).

    metrics_scoring.property_id is joined in every properties list/detail/
    export query and had no index before this migration.
    """
    row = _index_row(db_session, "metrics_scoring", "ix_metrics_scoring_property_id")
    assert row is not None, "expected ix_metrics_scoring_property_id after migrations"
    indexdef = row.indexdef.lower()
    assert "using btree" in indexdef
    assert "(property_id)" in indexdef
