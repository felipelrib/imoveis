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


# ---------------------------------------------------------------------------
# New-match alert flag and threshold (v0.14-s1.9)
# ---------------------------------------------------------------------------


def test_new_match_flag_defaults_off_on_create():
    from api.saved_searches import SavedSearchCreate

    body = SavedSearchCreate.model_validate({"name": "x", "filters": {}})
    assert body.notify_new_matches is False
    assert body.min_price_drop is None


@pytest.mark.parametrize("model_name", ["SavedSearchCreate", "SavedSearchUpdate"])
def test_negative_min_price_drop_is_rejected(model_name):
    import api.saved_searches as saved_searches

    model = getattr(saved_searches, model_name)
    with pytest.raises(ValidationError):
        model.model_validate({"name": "x", "filters": {}, "min_price_drop": -0.01})
    assert model.model_validate({"name": "x", "filters": {}, "min_price_drop": 0}).min_price_drop == 0


@pytest.mark.parametrize("model_name", ["SavedSearchCreate", "SavedSearchUpdate"])
@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_non_finite_min_price_drop_is_rejected(model_name, value):
    # A stored infinity cannot be serialised: it would turn every later
    # GET /saved-searches into a 500.
    import api.saved_searches as saved_searches

    model = getattr(saved_searches, model_name)
    with pytest.raises(ValidationError):
        model.model_validate({"name": "x", "filters": {}, "min_price_drop": value})


def test_update_tells_an_explicit_null_threshold_from_an_absent_one():
    from api.saved_searches import SavedSearchUpdate

    absent = SavedSearchUpdate.model_validate({"name": "x"})
    explicit = SavedSearchUpdate.model_validate({"min_price_drop": None})
    assert "min_price_drop" not in absent.model_fields_set
    assert "min_price_drop" in explicit.model_fields_set
    assert absent.notify_new_matches is None


def test_item_reports_a_semantic_search_as_unsupported():
    from datetime import date, datetime

    from api.saved_searches import _item_from_row

    stamp = datetime(2026, 10, 8, 13, 0)
    row = (
        "id-1",
        "Com varanda",
        {"q": "varanda"},
        stamp,
        True,
        5.0,
        stamp,
        date(2026, 10, 8),
        None,
        None,
    )
    item = _item_from_row(row)
    assert item.notify_new_matches is True
    assert item.min_price_drop == 5.0
    assert item.notify_enabled_at == "2026-10-08T13:00:00"
    assert item.new_match_alerts_supported is False
    assert item.last_new_match_alert_on == "2026-10-08"

    plain = _item_from_row(
        ("id-2", "Sem busca", {"q": " "}, None, False, None, None, None, None, None)
    )
    assert plain.new_match_alerts_supported is True
    assert plain.notify_enabled_at is None
    assert plain.last_new_match_alert_on is None


@pytest.mark.parametrize("stored", [None, [], "rent", 3])
def test_item_reports_a_blob_that_is_not_an_object_as_unsupported(stored):
    # The matcher never fires for such a blob; the API must not say it would.
    from api.saved_searches import _item_from_row

    item = _item_from_row(("id-3", "Estranha", stored, None, True, None, None, None, None, None))
    assert item.filters == {}
    assert item.new_match_alerts_supported is False


def test_item_reports_a_blob_with_an_unknown_key_as_unsupported():
    from api.saved_searches import _item_from_row

    legacy = {"listingType": "rent", "maxPrice": 3000}  # camelCase, pre-normalisation
    item = _item_from_row(("id-4", "Antiga", legacy, None, True, None, None, None, None, None))
    assert item.new_match_alerts_supported is False


# ---------------------------------------------------------------------------
# Price-drop activation stamp (v0.14-s1.10)
# ---------------------------------------------------------------------------


def test_item_reports_the_drop_floor_and_the_last_drop_email_date():
    from datetime import date, datetime

    from api.saved_searches import _item_from_row

    stamp = datetime(2026, 10, 8, 13, 0)
    row = ("id-5", "Savassi", {}, None, True, 100.0, stamp, None, stamp, date(2026, 10, 9))
    item = _item_from_row(row)
    assert item.price_drop_enabled_at == "2026-10-08T13:00:00"
    assert item.last_price_drop_alert_on == "2026-10-09"

    never = _item_from_row(("id-6", "Savassi", {}, None, True, None, stamp, None, None, None))
    assert never.price_drop_enabled_at is None
    assert never.last_price_drop_alert_on is None


class _StampSession:
    """Answers the PATCH / POST statements and keeps what they wrote."""

    def __init__(self, *, notify: bool = False, min_drop: float | None = None):
        self.existing = ("id-1", "Savassi", {}, notify, min_drop)
        self.writes: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        result = MagicMock(rowcount=1)
        if sql.startswith(("UPDATE", "INSERT")):
            self.writes.append((sql, dict(params or {})))
        elif "min_price_drop FROM saved_searches" in sql:
            result.fetchone.return_value = self.existing
        else:
            result.fetchone.return_value = (
                "id-1", "Savassi", {}, None, True, 100.0, None, None, None, None,
            )
        return result


def _stamp_client(monkeypatch: pytest.MonkeyPatch, store: _StampSession) -> TestClient:
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
    return TestClient(app, raise_server_exceptions=False)


def _patch_writes(monkeypatch, body: dict, **stored) -> dict:
    store = _StampSession(**stored)
    response = _stamp_client(monkeypatch, store).patch(
        "/saved-searches/id-1", headers={"X-API-Key": "key-a"}, json=body
    )
    assert response.status_code == 200, response.text
    assert len(store.writes) == 1
    return store.writes[0][1]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body", "stored"),
    [
        # Switched on with a threshold already stored.
        ({"notify_new_matches": True}, {"notify": False, "min_drop": 100.0}),
        # Threshold set while the switch is on.
        ({"min_price_drop": 100}, {"notify": True, "min_drop": None}),
        ({"min_price_drop": 0}, {"notify": True, "min_drop": None}),
        # Both in one write.
        ({"notify_new_matches": True, "min_price_drop": 240}, {"notify": False, "min_drop": None}),
    ],
)
def test_patch_that_activates_drop_alerts_stamps_the_floor(monkeypatch, body, stored):
    from datetime import datetime, timezone

    written = _patch_writes(monkeypatch, body, **stored)

    stamp = written["price_drop_enabled_at"]
    assert stamp.tzinfo is None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((now - stamp).total_seconds()) < 60


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body", "stored"),
    [
        # Changing the value while active leaves the floor.
        ({"min_price_drop": 50}, {"notify": True, "min_drop": 100.0}),
        ({"notify_new_matches": True}, {"notify": True, "min_drop": 100.0}),
        # Switching off, or clearing the threshold, leaves it too.
        ({"notify_new_matches": False}, {"notify": True, "min_drop": 100.0}),
        ({"min_price_drop": None}, {"notify": True, "min_drop": 100.0}),
        # Not active after the write: on without a threshold, threshold while off.
        ({"notify_new_matches": True}, {"notify": False, "min_drop": None}),
        ({"min_price_drop": 100}, {"notify": False, "min_drop": None}),
        ({"notify_new_matches": True, "min_price_drop": None}, {"notify": False, "min_drop": 100.0}),
        ({"name": "Outro nome"}, {"notify": True, "min_drop": 100.0}),
    ],
)
def test_any_other_patch_leaves_the_drop_floor(monkeypatch, body, stored):
    written = _patch_writes(monkeypatch, body, **stored)

    assert "price_drop_enabled_at" not in written


@pytest.mark.unit
@pytest.mark.parametrize(
    ("extra", "stamped"),
    [
        ({"notify_new_matches": True, "min_price_drop": 100}, True),
        ({"notify_new_matches": True, "min_price_drop": 0}, True),
        ({"notify_new_matches": True}, False),
        ({"min_price_drop": 100}, False),
        ({}, False),
    ],
)
def test_create_stamps_the_drop_floor_only_when_drop_alerts_are_active(
    monkeypatch, extra, stamped
):
    store = _StampSession()
    response = _stamp_client(monkeypatch, store).post(
        "/saved-searches",
        headers={"X-API-Key": "key-a"},
        json={"name": "Savassi", "filters": {}, **extra},
    )

    assert response.status_code == 201, response.text
    written = store.writes[0][1]
    assert (written["price_drop_enabled_at"] is not None) is stamped
    assert (response.json()["price_drop_enabled_at"] is not None) is stamped
    assert response.json()["last_price_drop_alert_on"] is None
