"""Integration: Total Monthly Cost sort, cap and deciding Listing (v0.14-s1.2).

The filter builder's SQL is unit-tested as text; it only means something against
real rows. This seeds five Properties under one throwaway platform:

* P1 — two rent Listings with a total: A (price 3000, total 4200) and
  B (price 3400, total 3900). B decides; A stays the primary Listing.
* P2 — one rent Listing, total 4100.
* P3 — one rent Listing without a total (incomplete).
* P4 — sale only; its sale Listing carries a (corrupt) low total of 500, so a
  query that dropped the ``listing_type = 'rent'`` clause would let it in.
* P5 — an *inactive* rent Listing holding total 1000 and an active one at 4100.
"""

from __future__ import annotations

import csv
import io
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from infra.config import get_config

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set",
    ),
]

_TEST_API_KEY = "total-cost-test-api-key"


def _db_ready() -> bool:
    try:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT total_monthly_cost FROM property_listings LIMIT 0"))
            return True
    except Exception:
        return False


@pytest.fixture
def client():
    if not _db_ready():
        pytest.skip("Postgres property_listings cost columns not available")
    from api.main import app

    return TestClient(app, raise_server_exceptions=True)


def _insert_property(session, *, platform: str, label: str, price: float) -> str:
    prop_id = str(uuid.uuid4())
    session.execute(
        text(
            """
            INSERT INTO properties (
                id, platform, platform_id, title, description, price, active,
                props_json
            )
            VALUES (
                CAST(:id AS uuid), :platform, :pid, :title,
                'apartamento teste total cost', :price, true,
                CAST(:props AS jsonb)
            )
            """
        ),
        {
            "id": prop_id,
            "platform": platform,
            "pid": f"{platform}-{label}",
            "title": f"s1.2 total cost {label}",
            "price": price,
            "props": '{"available_for_rent": true, "available_for_sale": true}',
        },
    )
    return prop_id


def _insert_listing(
    session,
    *,
    property_id: str,
    platform: str,
    suffix: str,
    listing_type: str = "rent",
    price: float,
    total: float | None = None,
    rent: float | None = None,
    bundled: bool = False,
    active: bool = True,
) -> str:
    listing_id = str(uuid.uuid4())
    session.execute(
        text(
            """
            INSERT INTO property_listings (
                id, property_id, platform, platform_listing_id, listing_type,
                price, currency, url, active,
                rent_monthly, fees_bundled, total_monthly_cost, cost_complete
            )
            VALUES (
                CAST(:lid AS uuid), CAST(:pid AS uuid), :platform, :plid, :lt,
                :price, 'BRL', :url, :active,
                :rent, :bundled, :total, :complete
            )
            """
        ),
        {
            "lid": listing_id,
            "pid": property_id,
            "platform": platform,
            "plid": f"{platform}-{suffix}",
            "lt": listing_type,
            "price": price,
            "url": f"https://example.test/{platform}/{suffix}",
            "active": active,
            "rent": rent,
            "bundled": bundled,
            "total": total,
            "complete": total is not None,
        },
    )
    return listing_id


@pytest.fixture
def seeded():
    if not _db_ready():
        pytest.skip("Postgres property_listings cost columns not available")

    from infra.db import SessionLocal

    platform = f"test-s12-{uuid.uuid4().hex[:8]}"
    ids: dict[str, str] = {"platform": platform}

    with SessionLocal() as session:
        ids["P1"] = _insert_property(session, platform=platform, label="p1", price=3000.0)
        ids["P1_A"] = _insert_listing(
            session, property_id=ids["P1"], platform=platform, suffix="p1a",
            price=3000.0, rent=3000.0, total=4200.0,
        )
        ids["P1_B"] = _insert_listing(
            session, property_id=ids["P1"], platform=platform, suffix="p1b",
            price=3400.0, rent=3400.0, total=3900.0, bundled=True,
        )

        ids["P2"] = _insert_property(session, platform=platform, label="p2", price=3500.0)
        ids["P2_A"] = _insert_listing(
            session, property_id=ids["P2"], platform=platform, suffix="p2a",
            price=3500.0, rent=3500.0, total=4100.0,
        )

        ids["P3"] = _insert_property(session, platform=platform, label="p3", price=2500.0)
        ids["P3_A"] = _insert_listing(
            session, property_id=ids["P3"], platform=platform, suffix="p3a",
            price=2500.0, rent=2500.0, total=None,
        )

        ids["P4"] = _insert_property(session, platform=platform, label="p4", price=450000.0)
        ids["P4_S"] = _insert_listing(
            session, property_id=ids["P4"], platform=platform, suffix="p4s",
            listing_type="sale", price=450000.0, total=500.0,
        )

        ids["P5"] = _insert_property(session, platform=platform, label="p5", price=3600.0)
        ids["P5_INACTIVE"] = _insert_listing(
            session, property_id=ids["P5"], platform=platform, suffix="p5x",
            price=900.0, rent=900.0, total=1000.0, active=False,
        )
        ids["P5_A"] = _insert_listing(
            session, property_id=ids["P5"], platform=platform, suffix="p5a",
            price=3600.0, rent=3600.0, total=4100.0,
        )
        session.commit()

    yield ids

    with SessionLocal() as session:
        for key in ("P1", "P2", "P3", "P4", "P5"):
            session.execute(
                text("DELETE FROM property_listings WHERE property_id = CAST(:id AS uuid)"),
                {"id": ids[key]},
            )
            session.execute(
                text("DELETE FROM properties WHERE id = CAST(:id AS uuid)"),
                {"id": ids[key]},
            )
        session.commit()


def _list(client, seeded, **params):
    response = client.get(
        "/properties",
        params={"page": 1, "page_size": 100, "platform": seeded["platform"], **params},
    )
    assert response.status_code == 200, response.text
    return response.json()["properties"]


def _labels(seeded, properties) -> list[str]:
    by_id = {seeded[key]: key for key in ("P1", "P2", "P3", "P4", "P5")}
    return [by_id[p["id"]] for p in properties if p["id"] in by_id]


def test_cap_keeps_only_properties_with_a_total_under_it(client, seeded):
    labels = _labels(seeded, _list(client, seeded, max_total_monthly_cost=4000))
    assert sorted(labels) == ["P1"]


def test_cap_is_inclusive(client, seeded):
    labels = _labels(seeded, _list(client, seeded, max_total_monthly_cost=4100))
    assert sorted(labels) == ["P1", "P2", "P5"]


def test_cap_with_incomplete_requested_adds_rent_properties_without_a_total(
    client, seeded
):
    labels = _labels(
        seeded,
        _list(
            client, seeded, max_total_monthly_cost=4000, include_incomplete_totals=True
        ),
    )
    # P3 has a rent Listing and no total; the sale-only P4 stays out.
    assert sorted(labels) == ["P1", "P3"]


def test_flag_without_a_cap_filters_nothing(client, seeded):
    labels = _labels(seeded, _list(client, seeded, include_incomplete_totals=True))
    assert sorted(labels) == ["P1", "P2", "P3", "P4", "P5"]


def test_an_inactive_listing_never_supplies_the_total(client, seeded):
    """P5's inactive Listing holds total 1000; only the active 4100 counts."""
    labels = _labels(seeded, _list(client, seeded, max_total_monthly_cost=2000))
    assert labels == []

    (p5,) = [
        p
        for p in _list(client, seeded, sort_by="total_monthly_cost", sort_dir="asc")
        if p["id"] == seeded["P5"]
    ]
    assert p5["total_monthly_cost"] == 4100.0
    assert p5["deciding_listing_id"] == seeded["P5_A"]
    assert [x["id"] for x in p5["listings"]] == [seeded["P5_A"]]


def test_sort_ascending_puts_properties_without_a_total_last(client, seeded):
    labels = _labels(
        seeded, _list(client, seeded, sort_by="total_monthly_cost", sort_dir="asc")
    )
    assert labels[0] == "P1"
    assert sorted(labels[1:3]) == ["P2", "P5"]
    assert sorted(labels[3:]) == ["P3", "P4"]
    assert [x for x in labels if x in ("P1", "P2", "P3")] == ["P1", "P2", "P3"]


def test_sort_descending_still_puts_properties_without_a_total_last(client, seeded):
    labels = _labels(
        seeded, _list(client, seeded, sort_by="total_monthly_cost", sort_dir="desc")
    )
    assert sorted(labels[0:2]) == ["P2", "P5"]
    assert labels[2] == "P1"
    assert sorted(labels[3:]) == ["P3", "P4"]
    assert [x for x in labels if x in ("P1", "P2", "P3")] == ["P2", "P1", "P3"]


def test_sort_order_agrees_with_the_projected_property_total(client, seeded):
    """The SQL sort key and ``total_monthly_cost`` come from one predicate."""
    properties = _list(client, seeded, sort_by="total_monthly_cost", sort_dir="asc")
    totals = [p["total_monthly_cost"] for p in properties]
    known = [t for t in totals if t is not None]
    assert known == sorted(known)
    assert totals == known + [None] * (len(totals) - len(known))


def test_invalid_sort_key_is_rejected(client, seeded):
    response = client.get("/properties", params={"sort_by": "total"})
    assert response.status_code == 422


def test_deciding_listing_and_cost_are_projected_from_stored_rows(client, seeded):
    properties = _list(client, seeded)
    by_label = dict(zip(_labels(seeded, properties), properties, strict=True))

    p1 = by_label["P1"]
    assert p1["deciding_listing_id"] == seeded["P1_B"]
    assert p1["deciding_rule"] == "lowest-complete-total"
    assert p1["total_monthly_cost"] == 3900.0
    # Legacy fields keep their meaning: the headline-lowest Listing is primary.
    assert p1["primary_listing"]["id"] == seeded["P1_A"]
    assert p1["price"] == 3000.0
    costs = {x["id"]: x["cost"] for x in p1["listings"]}
    assert costs[seeded["P1_A"]]["total_state"] == "complete"
    assert costs[seeded["P1_A"]]["total_monthly_cost"] == 4200.0
    assert costs[seeded["P1_A"]]["rent_monthly"] == 3000.0
    assert costs[seeded["P1_B"]]["total_state"] == "bundled"
    assert costs[seeded["P1_B"]]["condo_fee_state"] == "bundled"
    assert costs[seeded["P1_B"]]["iptu_state"] == "bundled"
    assert costs[seeded["P1_B"]]["fees_bundled"] is True

    p3 = by_label["P3"]
    assert p3["deciding_listing_id"] == seeded["P3_A"] == p3["primary_listing"]["id"]
    assert p3["deciding_rule"] == "lowest-headline-price"
    assert p3["total_monthly_cost"] is None
    assert p3["listings"][0]["cost"]["total_state"] == "incomplete"
    assert p3["listings"][0]["cost"]["condo_fee_monthly"] is None
    assert p3["listings"][0]["cost"]["condo_fee_state"] == "unknown"

    p4 = by_label["P4"]
    assert p4["deciding_listing_id"] == seeded["P4_S"]
    assert p4["deciding_rule"] == "lowest-headline-price"
    assert p4["total_monthly_cost"] is None
    assert p4["listings"][0]["cost"]["rent_state"] == "not-applicable"
    assert p4["listings"][0]["cost"]["total_state"] == "not-applicable"

    for prop in by_label.values():
        assert prop["deciding_listing_id"] in {x["id"] for x in prop["listings"]}


def test_detail_and_by_ids_carry_the_same_deciding_listing(client, seeded):
    detail = client.get(f"/properties/{seeded['P1']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["deciding_listing_id"] == seeded["P1_B"]
    assert body["deciding_rule"] == "lowest-complete-total"
    assert body["total_monthly_cost"] == 3900.0
    assert {x["id"] for x in body["listings"]} == {seeded["P1_A"], seeded["P1_B"]}

    batch = client.get("/properties/by-ids", params={"ids": seeded["P1"]})
    assert batch.status_code == 200, batch.text
    (item,) = batch.json()["properties"]
    assert item["deciding_listing_id"] == seeded["P1_B"]
    assert item["total_monthly_cost"] == 3900.0


def test_export_accepts_the_same_params(client, seeded, monkeypatch):
    monkeypatch.setenv("API_KEY", _TEST_API_KEY)
    monkeypatch.setenv("JWT_SECRET", "total-cost-test-jwt-secret")
    get_config.cache_clear()
    try:
        response = client.get(
            "/properties/export",
            params={
                "format": "json",
                "platform": seeded["platform"],
                "max_total_monthly_cost": 4000,
                "include_incomplete_totals": "true",
                "sort_by": "total_monthly_cost",
                "sort_dir": "asc",
            },
            headers={"X-API-Key": _TEST_API_KEY},
        )
    finally:
        get_config.cache_clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert _labels(seeded, body["properties"]) == ["P1", "P3"]
    assert body["properties"][0]["deciding_listing_id"] == seeded["P1_B"]
    assert body["properties"][0]["listings"][0]["cost"]["total_state"] in (
        "complete",
        "bundled",
    )

    get_config.cache_clear()
    try:
        csv_response = client.get(
            "/properties/export",
            params={
                "format": "csv",
                "platform": seeded["platform"],
                "max_total_monthly_cost": 4000,
                "include_incomplete_totals": "true",
                "sort_by": "total_monthly_cost",
                "sort_dir": "asc",
            },
            headers={"X-API-Key": _TEST_API_KEY},
        )
    finally:
        get_config.cache_clear()
    assert csv_response.status_code == 200, csv_response.text
    rows = list(csv.reader(io.StringIO(csv_response.text)))
    assert rows[0][-3:] == ["deciding_listing_id", "deciding_rule", "total_monthly_cost"]
    (p1_row,) = [row for row in rows[1:] if row[0] == seeded["P1"]]
    assert p1_row[-3:-1] == [seeded["P1_B"], "lowest-complete-total"]
    # Postgres JSON renders the stored float 3900 without a fraction.
    assert float(p1_row[-1]) == 3900.0
