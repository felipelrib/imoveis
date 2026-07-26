"""Integration: max_price + price_type filter dual-listed properties (BIN-79)."""

from __future__ import annotations

import os
import uuid

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
            session.execute(text("SELECT 1 FROM property_listings LIMIT 0"))
            return True
    except Exception:
        return False


@pytest.fixture
def client():
    if not _db_ready():
        pytest.skip("Postgres property_listings table not available")
    from api.main import app

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def seeded_dual_listed_property():
    """Active property with cheap rent and expensive sale listings."""
    if not _db_ready():
        pytest.skip("Postgres property_listings table not available")

    from infra.db import SessionLocal

    prop_id = str(uuid.uuid4())
    platform_id = f"bin79-{prop_id[:8]}"

    with SessionLocal() as session:
        session.execute(
            text(
                """
                INSERT INTO properties (
                    id, platform, platform_id, title, description, price, active,
                    props_json
                )
                VALUES (
                    CAST(:id AS uuid), 'test', :pid, 'BIN-79 dual list filter',
                    'apartamento teste dual', 3500, true,
                    CAST(:props AS jsonb)
                )
                """
            ),
            {
                "id": prop_id,
                "pid": platform_id,
                "props": '{"available_for_rent": true, "available_for_sale": true}',
            },
        )
        for listing_type, price, suffix in (
            ("rent", 3500.0, "r"),
            ("sale", 400000.0, "s"),
        ):
            session.execute(
                text(
                    """
                    INSERT INTO property_listings (
                        id, property_id, platform, platform_listing_id,
                        listing_type, price, currency, url
                    )
                    VALUES (
                        CAST(:lid AS uuid), CAST(:pid AS uuid), 'test', :plid,
                        :lt, :price, 'BRL', :url
                    )
                    """
                ),
                {
                    "lid": str(uuid.uuid4()),
                    "pid": prop_id,
                    "plid": f"{platform_id}-{suffix}",
                    "lt": listing_type,
                    "price": price,
                    "url": f"https://example.test/{platform_id}/{suffix}",
                },
            )
        session.commit()

    yield prop_id

    with SessionLocal() as session:
        session.execute(
            text("DELETE FROM property_listings WHERE property_id = CAST(:id AS uuid)"),
            {"id": prop_id},
        )
        session.execute(
            text("DELETE FROM properties WHERE id = CAST(:id AS uuid)"),
            {"id": prop_id},
        )
        session.commit()


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {p["id"] for p in response.json()["properties"]}


def test_max_price_sale_excludes_cheap_rent_expensive_sale(client, seeded_dual_listed_property):
    """Sale cap must not match on rent; rent cap still matches dual-listed homes."""
    prop_id = seeded_dual_listed_property

    sale_tight = client.get(
        "/properties",
        params={
            "page": 1,
            "page_size": 100,
            "platform": "test",
            "max_price": 5000,
            "price_type": "sale",
        },
    )
    assert prop_id not in _ids(sale_tight)

    rent_tight = client.get(
        "/properties",
        params={
            "page": 1,
            "page_size": 100,
            "platform": "test",
            "max_price": 5000,
            "price_type": "rent",
        },
    )
    assert prop_id in _ids(rent_tight)

    sale_wide = client.get(
        "/properties",
        params={
            "page": 1,
            "page_size": 100,
            "platform": "test",
            "max_price": 500000,
            "price_type": "sale",
        },
    )
    assert prop_id in _ids(sale_wide)
