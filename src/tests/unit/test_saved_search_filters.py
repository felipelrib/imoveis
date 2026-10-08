"""Unit tests for saved-search EN wire filters (BIN-100 / BIN-109)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import app
from api.saved_searches import SavedSearchFilters
from infra.config import AuthConfig, get_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def test_camel_case_filters_normalize_to_snake_en_wire():
    filters = SavedSearchFilters.model_validate(
        {
            "sortBy": "price",
            "sortDir": "asc",
            "listingType": "rent",
            "propertyType": "apartment",
            "platform": "olx",
            "maxPrice": "5000",
            "priceType": "rent",
            "minBedrooms": "2",
            "minParking": "1",
            "minScore": "0.5",
            "neighborhood": "Savassi",
            "city": "Belo Horizonte",
            "isFurnished": True,
            "acceptsPets": True,
            "q": "varanda",
        }
    )
    wire = filters.to_wire()
    assert wire == {
        "sort_by": "price",
        "sort_dir": "asc",
        "listing_type": "rent",
        "property_type": "apartment",
        "platform": "olx",
        "max_price": 5000.0,
        "price_type": "rent",
        "min_bedrooms": 2,
        "min_parking": 1,
        "min_score": 0.5,
        "neighborhood": "Savassi",
        "city": "Belo Horizonte",
        "is_furnished": True,
        "accepts_pets": True,
        "q": "varanda",
    }


def test_pt_listing_and_property_aliases_normalize_on_save():
    filters = SavedSearchFilters.model_validate(
        {
            "listing_type": "aluguel",
            "price_type": "venda",
            "property_type": "apartamento",
        }
    )
    wire = filters.to_wire()
    assert wire["listing_type"] == "rent"
    assert wire["price_type"] == "sale"
    assert wire["property_type"] == "apartment"


def test_legacy_furnished_pets_neighbourhood_aliases():
    filters = SavedSearchFilters.model_validate(
        {
            "furnished": True,
            "pets": False,
            "neighbourhood": ["Savassi", "Lourdes"],
        }
    )
    wire = filters.to_wire()
    assert wire["is_furnished"] is True
    assert "accepts_pets" not in wire  # false flags omitted (SPA default)
    assert wire["neighborhood"] == "Savassi,Lourdes"


def test_empty_strings_excluded_from_wire():
    filters = SavedSearchFilters.model_validate(
        {
            "listingType": "both",
            "propertyType": "",
            "platform": "",
            "maxPrice": "",
            "isFurnished": False,
            "acceptsPets": False,
            "q": "",
        }
    )
    wire = filters.to_wire()
    assert wire.get("listing_type") == "both"
    assert "property_type" not in wire
    assert "platform" not in wire
    assert "max_price" not in wire
    assert "is_furnished" not in wire
    assert "accepts_pets" not in wire
    assert "q" not in wire


def test_price_percentile_cap_round_trips_under_its_wire_key():
    for payload in (
        {"max_price_per_m2_percentile": 0.25},
        {"maxPricePerM2Percentile": "0.25"},
    ):
        wire = SavedSearchFilters.model_validate(payload).to_wire()
        assert wire == {"max_price_per_m2_percentile": 0.25}
        # What was stored reads back unchanged.
        assert SavedSearchFilters.model_validate(wire).to_wire() == wire


def test_blank_price_percentile_cap_is_omitted_from_the_wire():
    wire = SavedSearchFilters.model_validate(
        {"listingType": "rent", "maxPricePerM2Percentile": ""}
    ).to_wire()
    assert wire == {"listing_type": "rent"}


@pytest.mark.parametrize("value", [0, -0.25, 1.5, 25, "abc"])
def test_price_percentile_cap_outside_the_range_is_rejected(value):
    with pytest.raises(ValidationError):
        SavedSearchFilters.model_validate({"max_price_per_m2_percentile": value})


class _InsertCapturingSession:
    """Minimal session that records INSERT filter JSON for create assertions."""

    def __init__(self):
        self.inserted_filters: dict | None = None
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def execute(self, statement, params=None):
        sql = str(statement).lower()
        params = params or {}
        if "insert into saved_searches" in sql:
            raw = params.get("filters")
            if isinstance(raw, str):
                self.inserted_filters = json.loads(raw)
            elif isinstance(raw, dict):
                self.inserted_filters = raw
            else:
                self.inserted_filters = {}
        return MagicMock(rowcount=1)


@pytest.mark.unit
def test_create_saved_search_accepts_camel_case_price_type(
    monkeypatch: pytest.MonkeyPatch,
):
    """BIN-109: POST /saved-searches with camelCase filters → snake_case wire."""
    store = _InsertCapturingSession()
    monkeypatch.setattr("api.saved_searches.SessionLocal", lambda: store)

    cfg = MagicMock()
    cfg.auth = AuthConfig(
        api_key="key-a",
        jwt_secret="test-jwt-secret",
        principal_id="alice",
        admin_user="admin",
        admin_pass="admin",
    )
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)

    client = TestClient(app, raise_server_exceptions=False)
    created = client.post(
        "/saved-searches",
        headers={"X-API-Key": "key-a"},
        json={
            "name": "Sale budget BH",
            "filters": {
                "maxPrice": 500000,
                "priceType": "sale",
                "listingType": "sale",
                "propertyType": "apartment",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["filters"]["max_price"] == 500000.0
    assert body["filters"]["price_type"] == "sale"
    assert body["filters"]["listing_type"] == "sale"
    assert body["filters"]["property_type"] == "apartment"
    assert "priceType" not in body["filters"]
    assert "maxPrice" not in body["filters"]

    assert store.committed is True
    assert store.inserted_filters is not None
    assert store.inserted_filters["max_price"] == 500000.0
    assert store.inserted_filters["price_type"] == "sale"
    assert "priceType" not in store.inserted_filters


@pytest.mark.unit
def test_create_saved_search_keeps_or_rejects_the_price_percentile_cap(
    monkeypatch: pytest.MonkeyPatch,
):
    """v0.14-s1.7: the cap is stored under its wire key; out of range is a 422."""
    store = _InsertCapturingSession()
    monkeypatch.setattr("api.saved_searches.SessionLocal", lambda: store)

    cfg = MagicMock()
    cfg.auth = AuthConfig(
        api_key="key-a",
        jwt_secret="test-jwt-secret",
        principal_id="alice",
        admin_user="admin",
        admin_pass="admin",
    )
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)

    client = TestClient(app, raise_server_exceptions=False)
    created = client.post(
        "/saved-searches",
        headers={"X-API-Key": "key-a"},
        json={
            "name": "Cheapest quarter, rent",
            "filters": {"listing_type": "rent", "max_price_per_m2_percentile": 0.25},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["filters"] == {
        "listing_type": "rent",
        "max_price_per_m2_percentile": 0.25,
    }
    assert store.inserted_filters == {
        "listing_type": "rent",
        "max_price_per_m2_percentile": 0.25,
    }

    store.inserted_filters = None
    store.committed = False
    rejected = client.post(
        "/saved-searches",
        headers={"X-API-Key": "key-a"},
        json={"name": "Bad", "filters": {"max_price_per_m2_percentile": 1.5}},
    )
    assert rejected.status_code == 422, rejected.text
    assert store.inserted_filters is None
    assert store.committed is False


def test_update_saved_search_body_keeps_or_rejects_the_price_percentile_cap():
    """PATCH validates filters through the same model as POST."""
    from pydantic import ValidationError

    from api.saved_searches import SavedSearchUpdate

    body = SavedSearchUpdate.model_validate(
        {"filters": {"maxPricePerM2Percentile": "0.5"}}
    )
    assert body.filters is not None
    assert body.filters.to_wire() == {"max_price_per_m2_percentile": 0.5}
    for value in (0, 1.5, 25):
        with pytest.raises(ValidationError):
            SavedSearchUpdate.model_validate(
                {"filters": {"max_price_per_m2_percentile": value}}
            )
