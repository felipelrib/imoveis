"""Integration tests for owner-scoped personalization against Postgres (BIN-45)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from adapters.db.models import Base, Property
from api.main import app
from infra.config import get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def test_db():
    """Connect to the test database and truncate after the test."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integrate with validate.sh or set manually")

    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    with engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()
    engine.dispose()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def api_headers():
    get_config.cache_clear()
    api_key = get_config().auth.api_key or os.environ.get("API_KEY", "")
    assert api_key, "API_KEY must be set for owner-scoped integration tests"
    return {"X-API-Key": api_key}


@pytest.fixture
def property_id(test_db):
    """Insert a minimal property row and return its id as str."""
    pid = uuid.uuid4()
    prop = Property(
        id=pid,
        platform="test",
        platform_id=f"bin45-{pid.hex[:8]}",
        title="Owner scope test",
        price=1000.0,
        active=True,
    )
    test_db.add(prop)
    test_db.commit()
    return str(pid)


@pytest.mark.integration
def test_favourite_requires_auth(client):
    response = client.get("/favourites")
    assert response.status_code == 401


@pytest.mark.integration
def test_favourite_roundtrip_writes_owner(client, api_headers, property_id, test_db):
    add = client.post(
        "/favourites",
        headers=api_headers,
        json={"property_id": property_id},
    )
    assert add.status_code == 201, add.text

    owner = test_db.execute(
        text("SELECT owner FROM favourites WHERE property_id = :pid"),
        {"pid": property_id},
    ).scalar()
    assert owner == get_config().auth.principal_id

    listed = client.get("/favourites", headers=api_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    removed = client.delete(f"/favourites/{property_id}", headers=api_headers)
    assert removed.status_code == 200


@pytest.mark.integration
def test_watchlist_uses_api_key_not_jwt(client, api_headers, property_id, test_db):
    add = client.post(
        "/watchlist",
        headers=api_headers,
        json={"property_id": property_id, "min_drop_pct": 5.0},
    )
    assert add.status_code == 201, add.text
    assert "user_id" not in add.json()

    owner = test_db.execute(
        text("SELECT owner FROM watchlist WHERE property_id = :pid"),
        {"pid": property_id},
    ).scalar()
    assert owner == get_config().auth.principal_id
