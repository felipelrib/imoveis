"""Integration tests for semantic search (pgvector + GET /properties?q=)."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set",
    ),
]


def _db_ready() -> bool:
    try:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            has_vector = session.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            return bool(has_vector)
    except Exception:
        return False


@pytest.fixture
def client():
    if not _db_ready():
        pytest.skip("Postgres with pgvector not available")
    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def seeded_embeddings():
    """Insert two properties with known 768-d embeddings, clean up after."""
    if not _db_ready():
        pytest.skip("Postgres with pgvector not available")

    from infra.db import SessionLocal

    id_near = str(uuid.uuid4())
    id_far = str(uuid.uuid4())
    near = [1.0] + [0.0] * 767
    far = [0.0, 1.0] + [0.0] * 766
    near_lit = "[" + ",".join(str(x) for x in near) + "]"
    far_lit = "[" + ",".join(str(x) for x in far) + "]"

    with SessionLocal() as session:
        session.execute(
            text(
                """
                INSERT INTO properties (id, platform, platform_id, title, description, price, active, embedding)
                VALUES
                  (CAST(:id_near AS uuid), 'test', :pid_near, 'Near metro',
                   'apartamento perto do metro', 1000, true, CAST(:near AS vector)),
                  (CAST(:id_far AS uuid), 'test', :pid_far, 'Rural farm',
                   'fazenda no interior', 2000, true, CAST(:far AS vector))
                """
            ),
            {
                "id_near": id_near,
                "id_far": id_far,
                "pid_near": f"sem-{id_near[:8]}",
                "pid_far": f"sem-{id_far[:8]}",
                "near": near_lit,
                "far": far_lit,
            },
        )
        session.commit()

    yield {"near": id_near, "far": id_far, "query_vec": near}

    with SessionLocal() as session:
        session.execute(
            text("DELETE FROM properties WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"),
            {"a": id_near, "b": id_far},
        )
        session.commit()


def test_semantic_search_orders_by_cosine(client, seeded_embeddings):
    """Query embedding close to 'near' property should rank it first."""
    ids = seeded_embeddings
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.embed = AsyncMock(return_value=ids["query_vec"])

    with patch("adapters.ai.client.create_ai_client", return_value=mock_client):
        response = client.get("/properties?q=apartamento+metro&page_size=50")

    assert response.status_code == 200, response.text
    data = response.json()
    ours = [p for p in data["properties"] if p["id"] in (ids["near"], ids["far"])]
    assert len(ours) == 2
    assert ours[0]["id"] == ids["near"]
    assert ours[1]["id"] == ids["far"]
