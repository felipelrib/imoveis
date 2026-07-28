"""Integration: sort-by-price uses rent/sale listing price (BIN-106)."""

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
def seeded_crossed_dual_listed():
    """Two dual-listed homes with crossed rent/sale prices.

    A: cheap rent (2000) / expensive sale (900000) — decisioning price ~2000
    B: expensive rent (5000) / cheap sale (300000) — decisioning price ~5000
    """
    if not _db_ready():
        pytest.skip("Postgres property_listings table not available")

    from infra.db import SessionLocal

    props = {
        "A": {
            "id": str(uuid.uuid4()),
            "rent": 2000.0,
            "sale": 900000.0,
            "decisioning": 2000.0,
        },
        "B": {
            "id": str(uuid.uuid4()),
            "rent": 5000.0,
            "sale": 300000.0,
            "decisioning": 5000.0,
        },
    }
    tag = f"bin106-{uuid.uuid4().hex[:8]}"
    platform = f"test-{tag}"

    with SessionLocal() as session:
        for label, meta in props.items():
            platform_id = f"{tag}-{label}"
            session.execute(
                text(
                    """
                    INSERT INTO properties (
                        id, platform, platform_id, title, description, price, active,
                        props_json
                    )
                    VALUES (
                        CAST(:id AS uuid), :platform, :pid, :title,
                        'apartamento teste sort price', :price, true,
                        CAST(:props AS jsonb)
                    )
                    """
                ),
                {
                    "id": meta["id"],
                    "platform": platform,
                    "pid": platform_id,
                    "title": f"BIN-106 sort {label}",
                    "price": meta["decisioning"],
                    "props": '{"available_for_rent": true, "available_for_sale": true}',
                },
            )
            for listing_type, price, suffix in (
                ("rent", meta["rent"], "r"),
                ("sale", meta["sale"], "s"),
            ):
                session.execute(
                    text(
                        """
                        INSERT INTO property_listings (
                            id, property_id, platform, platform_listing_id,
                            listing_type, price, currency, url
                        )
                        VALUES (
                            CAST(:lid AS uuid), CAST(:pid AS uuid), :platform, :plid,
                            :lt, :price, 'BRL', :url
                        )
                        """
                    ),
                    {
                        "lid": str(uuid.uuid4()),
                        "pid": meta["id"],
                        "platform": platform,
                        "plid": f"{platform_id}-{suffix}",
                        "lt": listing_type,
                        "price": price,
                        "url": f"https://example.test/{platform_id}/{suffix}",
                    },
                )
        session.commit()

    yield {"A": props["A"]["id"], "B": props["B"]["id"], "platform": platform}

    ids = [props["A"]["id"], props["B"]["id"]]
    with SessionLocal() as session:
        for prop_id in ids:
            session.execute(
                text(
                    "DELETE FROM property_listings WHERE property_id = CAST(:id AS uuid)"
                ),
                {"id": prop_id},
            )
            session.execute(
                text("DELETE FROM properties WHERE id = CAST(:id AS uuid)"),
                {"id": prop_id},
            )
        session.commit()


def _ordered_ids(response, wanted: set[str]) -> list[str]:
    assert response.status_code == 200, response.text
    return [p["id"] for p in response.json()["properties"] if p["id"] in wanted]


def test_sort_price_sale_orders_by_sale_listing(client, seeded_crossed_dual_listed):
    ids = seeded_crossed_dual_listed
    wanted = {ids["A"], ids["B"]}
    resp = client.get(
        "/properties",
        params={
            "page": 1,
            "page_size": 100,
            "platform": ids["platform"],
            "listing_type": "sale",
            "sort_by": "price",
            "sort_dir": "asc",
        },
    )
    ordered = _ordered_ids(resp, wanted)
    assert ordered == [ids["B"], ids["A"]], ordered


def test_sort_price_rent_orders_by_rent_listing(client, seeded_crossed_dual_listed):
    ids = seeded_crossed_dual_listed
    wanted = {ids["A"], ids["B"]}
    resp = client.get(
        "/properties",
        params={
            "page": 1,
            "page_size": 100,
            "platform": ids["platform"],
            "listing_type": "rent",
            "sort_by": "price",
            "sort_dir": "asc",
        },
    )
    ordered = _ordered_ids(resp, wanted)
    assert ordered == [ids["A"], ids["B"]], ordered


def test_sort_price_both_uses_decisioning_price(client, seeded_crossed_dual_listed):
    ids = seeded_crossed_dual_listed
    wanted = {ids["A"], ids["B"]}
    resp = client.get(
        "/properties",
        params={
            "page": 1,
            "page_size": 100,
            "platform": ids["platform"],
            "listing_type": "both",
            "sort_by": "price",
            "sort_dir": "asc",
        },
    )
    ordered = _ordered_ids(resp, wanted)
    assert ordered == [ids["A"], ids["B"]], ordered
