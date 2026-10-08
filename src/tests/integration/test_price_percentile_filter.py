"""Integration: cohort price/m2 percentile on the wire and as a filter (v0.14-s1.7).

The stored ``metrics_scoring.price_per_m2_percentile_rent/_sale`` (Story 1.6)
are seeded directly - this story only reads them - under one throwaway
platform, then read back through the API:

* A / B / C - rent only, percentile 0.2 / 0.25 / 0.3.
* H - rent only, 501/2000 (0.2505): three-place rounding would make it 0.25.
* D - rent only, cohort too small: percentile NULL, cohort size stored.
* E - dual, rent 0.1 and sale 0.9.
* F - dual, rent 0.9 and sale 0.2.
* G - rent only, no ``metrics_scoring`` row at all.
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

_TEST_API_KEY = "price-percentile-test-api-key"
_LABELS = ("A", "B", "C", "D", "E", "F", "G", "H")
_UNROUNDED = 501 / 2000


def _db_ready() -> bool:
    try:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(
                text("SELECT price_per_m2_percentile_rent FROM metrics_scoring LIMIT 0")
            )
            return True
    except Exception:
        return False


@pytest.fixture
def client():
    if not _db_ready():
        pytest.skip("Postgres metrics_scoring percentile columns not available")
    from api.main import app

    return TestClient(app, raise_server_exceptions=True)


def _insert_property(session, *, platform: str, label: str, rent: bool, sale: bool) -> str:
    prop_id = str(uuid.uuid4())
    session.execute(
        text(
            """
            INSERT INTO properties (
                id, platform, platform_id, title, description, price, area_m2,
                active, props_json
            )
            VALUES (
                CAST(:id AS uuid), :platform, :pid, :title,
                'apartamento teste percentil', 3000, 100, true,
                jsonb_build_object(
                    'available_for_rent', CAST(:rent AS boolean),
                    'available_for_sale', CAST(:sale AS boolean)
                )
            )
            """
        ),
        {
            "id": prop_id,
            "platform": platform,
            "pid": f"{platform}-{label}",
            "title": f"s1.7 percentile {label}",
            "rent": rent,
            "sale": sale,
        },
    )
    for listing_type, wanted, price in (("rent", rent, 3000.0), ("sale", sale, 500000.0)):
        if not wanted:
            continue
        session.execute(
            text(
                """
                INSERT INTO property_listings (
                    id, property_id, platform, platform_listing_id, listing_type,
                    price, currency, url, active
                )
                VALUES (
                    CAST(:lid AS uuid), CAST(:pid AS uuid), :platform, :plid, :lt,
                    :price, 'BRL', :url, true
                )
                """
            ),
            {
                "lid": str(uuid.uuid4()),
                "pid": prop_id,
                "platform": platform,
                "plid": f"{platform}-{label}-{listing_type}",
                "lt": listing_type,
                "price": price,
                "url": f"https://example.test/{platform}/{label}/{listing_type}",
            },
        )
    return prop_id


def _insert_scoring(
    session,
    *,
    property_id: str,
    rent: float | None = None,
    sale: float | None = None,
    rent_size: int | None = None,
    sale_size: int | None = None,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO metrics_scoring (
                property_id, combined_score,
                price_per_m2_percentile_rent, price_per_m2_percentile_sale,
                percentile_cohort_size_rent, percentile_cohort_size_sale
            )
            VALUES (
                CAST(:pid AS uuid), 0.5, :rent, :sale, :rent_size, :sale_size
            )
            """
        ),
        {
            "pid": property_id,
            "rent": rent,
            "sale": sale,
            "rent_size": rent_size,
            "sale_size": sale_size,
        },
    )


@pytest.fixture
def seeded():
    if not _db_ready():
        pytest.skip("Postgres metrics_scoring percentile columns not available")

    from infra.db import SessionLocal

    platform = f"test-s17-{uuid.uuid4().hex[:8]}"
    ids: dict[str, str] = {"platform": platform}

    with SessionLocal() as session:
        for label in ("A", "B", "C", "D", "G", "H"):
            ids[label] = _insert_property(
                session, platform=platform, label=label.lower(), rent=True, sale=False
            )
        for label in ("E", "F"):
            ids[label] = _insert_property(
                session, platform=platform, label=label.lower(), rent=True, sale=True
            )
        _insert_scoring(session, property_id=ids["A"], rent=0.2, rent_size=20)
        _insert_scoring(session, property_id=ids["B"], rent=0.25, rent_size=20)
        _insert_scoring(session, property_id=ids["C"], rent=0.3, rent_size=20)
        _insert_scoring(session, property_id=ids["H"], rent=_UNROUNDED, rent_size=2000)
        # Suppressed: the cohort is below the minimum, the size is still stored.
        _insert_scoring(session, property_id=ids["D"], rent=None, rent_size=4)
        _insert_scoring(
            session, property_id=ids["E"], rent=0.1, sale=0.9, rent_size=20, sale_size=20
        )
        _insert_scoring(
            session, property_id=ids["F"], rent=0.9, sale=0.2, rent_size=20, sale_size=20
        )
        # G: no metrics_scoring row.
        session.commit()

    yield ids

    with SessionLocal() as session:
        for label in _LABELS:
            for table, column in (
                ("metrics_scoring", "property_id"),
                ("property_listings", "property_id"),
                ("properties", "id"),
            ):
                # table / column come from the literal tuple above.
                session.execute(
                    text("DELETE FROM " + table + " WHERE " + column + " = CAST(:id AS uuid)"),
                    {"id": ids[label]},
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
    by_id = {seeded[label]: label for label in _LABELS}
    return sorted(by_id[p["id"]] for p in properties if p["id"] in by_id)


def test_rent_filter_reads_the_rent_column_inclusively(client, seeded):
    properties = _list(
        client, seeded, listing_type="rent", max_price_per_m2_percentile=0.25
    )
    # 0.2 and 0.25 pass, 0.3 does not; 0.2505 does not (it is not rounded to
    # 0.25); E passes on its rent 0.1; F's sale 0.2 does not leak into rent.
    assert _labels(seeded, properties) == ["A", "B", "E"]
    for prop in properties:
        assert prop["price_per_m2_percentile_rent"] <= 0.25


def test_type_switch_reads_the_sale_column(client, seeded):
    properties = _list(
        client, seeded, listing_type="sale", max_price_per_m2_percentile=0.25
    )
    # E (rent 0.1, sale 0.9) is out: the sale column decides.
    assert _labels(seeded, properties) == ["F"]


@pytest.mark.parametrize("listing_type", [None, "both"])
def test_both_or_no_type_keeps_a_property_when_either_column_qualifies(
    client, seeded, listing_type
):
    params = {"max_price_per_m2_percentile": 0.25}
    if listing_type is not None:
        params["listing_type"] = listing_type
    # F is in on its sale 0.2 although its rent is 0.9.
    assert _labels(seeded, _list(client, seeded, **params)) == ["A", "B", "E", "F"]


def test_a_stored_value_of_a_type_without_an_active_listing_does_not_match(
    client, seeded
):
    """The stored percentile outlives a deactivated Listing until the next
    scoring run; the card has no price line for that type, so no badge."""
    from infra.db import SessionLocal

    with SessionLocal() as session:
        session.execute(
            text(
                "UPDATE property_listings SET active = false "
                "WHERE property_id = CAST(:pid AS uuid) AND listing_type = 'sale'"
            ),
            {"pid": seeded["F"]},
        )
        session.commit()

    # F still carries sale 0.2 and ``available_for_sale``; only its rent 0.9 line is live.
    for params in ({"listing_type": "sale"}, {"listing_type": "both"}, {}):
        labels = _labels(
            seeded, _list(client, seeded, max_price_per_m2_percentile=0.25, **params)
        )
        assert "F" not in labels, params
    assert "F" in _labels(
        seeded, _list(client, seeded, listing_type="rent", max_price_per_m2_percentile=1)
    )


def test_wider_option_includes_the_unrounded_and_the_third(client, seeded):
    properties = _list(
        client, seeded, listing_type="rent", max_price_per_m2_percentile=0.5
    )
    assert _labels(seeded, properties) == ["A", "B", "C", "E", "H"]


def test_suppressed_and_unscored_never_match_even_the_widest_value(client, seeded):
    for params in (
        {"listing_type": "rent"},
        {"listing_type": "sale"},
        {"listing_type": "both"},
        {},
    ):
        labels = _labels(
            seeded, _list(client, seeded, max_price_per_m2_percentile=1, **params)
        )
        assert "D" not in labels, params
        assert "G" not in labels, params


def test_without_the_filter_everything_is_listed_with_the_stored_values(client, seeded):
    properties = _list(client, seeded)
    assert _labels(seeded, properties) == sorted(_LABELS)
    by_id = {p["id"]: p for p in properties}

    def pair(label):
        prop = by_id[seeded[label]]
        return prop["price_per_m2_percentile_rent"], prop["price_per_m2_percentile_sale"]

    assert pair("A") == (0.2, None)
    assert pair("B") == (0.25, None)
    assert pair("E") == (0.1, 0.9)
    assert pair("F") == (0.9, 0.2)
    # Served as stored, not rounded to three places.
    assert pair("H") == (_UNROUNDED, None)
    # Suppressed and unscored read null, never a default.
    assert pair("D") == (None, None)
    assert pair("G") == (None, None)


def test_detail_and_batch_carry_the_same_two_fields(client, seeded):
    for label, expected in (
        ("E", (0.1, 0.9)),
        ("H", (_UNROUNDED, None)),
        ("D", (None, None)),
        ("G", (None, None)),
    ):
        detail = client.get(f"/properties/{seeded[label]}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert (
            body["price_per_m2_percentile_rent"],
            body["price_per_m2_percentile_sale"],
        ) == expected, label

        batch = client.get("/properties/by-ids", params={"ids": seeded[label]})
        assert batch.status_code == 200, batch.text
        (item,) = batch.json()["properties"]
        assert (
            item["price_per_m2_percentile_rent"],
            item["price_per_m2_percentile_sale"],
        ) == expected, label


@pytest.mark.parametrize("value", ["0", "1.5", "abc", "-0.25"])
def test_out_of_range_is_rejected(client, seeded, value):
    response = client.get("/properties", params={"max_price_per_m2_percentile": value})
    assert response.status_code == 422


def test_export_returns_the_same_properties_and_the_columns_last(
    client, seeded, monkeypatch
):
    monkeypatch.setenv("API_KEY", _TEST_API_KEY)
    monkeypatch.setenv("JWT_SECRET", "price-percentile-test-jwt-secret")
    params = {
        "platform": seeded["platform"],
        "listing_type": "rent",
        "max_price_per_m2_percentile": 0.25,
    }
    get_config.cache_clear()
    try:
        json_response = client.get(
            "/properties/export",
            params={"format": "json", **params},
            headers={"X-API-Key": _TEST_API_KEY},
        )
        csv_response = client.get(
            "/properties/export",
            params={"format": "csv", **params},
            headers={"X-API-Key": _TEST_API_KEY},
        )
        rejected = client.get(
            "/properties/export",
            params={"max_price_per_m2_percentile": 1.5},
            headers={"X-API-Key": _TEST_API_KEY},
        )
    finally:
        get_config.cache_clear()

    listed = _labels(
        seeded,
        _list(client, seeded, listing_type="rent", max_price_per_m2_percentile=0.25),
    )
    assert json_response.status_code == 200, json_response.text
    assert _labels(seeded, json_response.json()["properties"]) == listed == ["A", "B", "E"]

    assert csv_response.status_code == 200, csv_response.text
    rows = list(csv.reader(io.StringIO(csv_response.text)))
    assert rows[0][-2:] == ["price_per_m2_percentile_rent", "price_per_m2_percentile_sale"]
    by_id = {row[0]: row for row in rows[1:]}
    assert sorted(by_id) == sorted(seeded[label] for label in listed)
    assert [float(by_id[seeded["E"]][-2]), float(by_id[seeded["E"]][-1])] == [0.1, 0.9]
    # A null percentile is an empty cell.
    assert by_id[seeded["A"]][-2:] == ["0.2", ""]

    assert rejected.status_code == 422
