"""Shared integration fixtures — keep wipes off the primary scraped DB (BIN-71)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from adapters.db.models import Base
from tests.db_isolation import assert_wipe_safe_database_url


@pytest.fixture(autouse=True)
def _refuse_primary_database_url():
    """Fail fast if integration tests would hit the scraped primary DB."""
    url = os.environ.get("DATABASE_URL")
    if url:
        assert_wipe_safe_database_url(url)


@pytest.fixture(scope="function")
def wipe_safe_db_session():
    """Session bound to DATABASE_URL; deletes all ORM tables after the test.

    Requires DATABASE_URL to point at a non-primary DB (``realestate_test``).
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integrate with validate.sh or set manually")
    assert_wipe_safe_database_url(database_url)

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    with engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()
    engine.dispose()
