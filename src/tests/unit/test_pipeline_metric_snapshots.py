"""Unit tests for pipeline metric snapshots (BIN-61)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from adapters.db.models import Base, PipelineMetricSnapshot
from adapters.metrics import pipeline_snapshots as snaps_mod
from adapters.metrics.pipeline_snapshots import (
    list_snapshots_since,
    prune_old_snapshots,
    write_snapshot,
)
from api.main import app
from infra.config import get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[PipelineMetricSnapshot.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.unit
def test_write_and_list_snapshots(memory_session):
    now = datetime.now(timezone.utc)
    write_snapshot(
        memory_session,
        {
            "ts": now - timedelta(minutes=2),
            "total_properties": 10,
            "enriched_properties": 3,
            "scraper_queue": 1,
            "ai_queue": 5,
            "throughput_per_min": 2.5,
        },
    )
    write_snapshot(
        memory_session,
        {
            "ts": now,
            "total_properties": 12,
            "enriched_properties": 4,
            "scraper_queue": 0,
            "ai_queue": 2,
            "throughput_per_min": 1.0,
        },
    )
    memory_session.commit()

    rows = list_snapshots_since(memory_session, now - timedelta(minutes=5))
    assert len(rows) == 2
    assert rows[0].total_properties == 10
    assert rows[1].throughput_per_min == 1.0


@pytest.mark.unit
def test_prune_old_snapshots(memory_session):
    now = datetime.now(timezone.utc)
    write_snapshot(
        memory_session,
        {
            "ts": now - timedelta(days=10),
            "total_properties": 1,
            "enriched_properties": 0,
            "scraper_queue": 0,
            "ai_queue": 0,
            "throughput_per_min": 0.0,
        },
    )
    write_snapshot(
        memory_session,
        {
            "ts": now - timedelta(hours=1),
            "total_properties": 2,
            "enriched_properties": 1,
            "scraper_queue": 0,
            "ai_queue": 0,
            "throughput_per_min": 0.5,
        },
    )
    memory_session.commit()

    deleted = prune_old_snapshots(memory_session, retention_days=7)
    memory_session.commit()
    assert deleted == 1
    rows = list_snapshots_since(memory_session, now - timedelta(days=30))
    assert len(rows) == 1
    assert rows[0].total_properties == 2


@pytest.mark.unit
def test_pipeline_history_endpoint_returns_points():
    client = TestClient(app, raise_server_exceptions=False)
    now = datetime.now(timezone.utc)
    row = MagicMock()
    row.ts = now
    row.total_properties = 7
    row.enriched_properties = 2
    row.scraper_queue = 3
    row.ai_queue = 4
    row.throughput_per_min = 1.5

    session = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session
    session_cm.__exit__.return_value = False

    with (
        patch("infra.db.SessionLocal", return_value=session_cm),
        patch.object(snaps_mod, "list_snapshots_since", return_value=[row]),
    ):
        response = client.get("/system/pipeline/history?minutes=60")

    assert response.status_code == 200
    data = response.json()
    assert len(data["points"]) == 1
    assert data["points"][0]["total_properties"] == 7
    assert data["points"][0]["ai_queue"] == 4
    assert data["points"][0]["throughput_per_min"] == 1.5
