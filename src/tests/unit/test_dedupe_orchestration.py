"""Additional unit tests for dedupe orchestration helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.dedupe import (
    DedupeMatchResult,
    _create_property,
    _find_fuzzy_match,
    _is_unchanged,
    _update_or_noop,
    match_or_create_property,
)
from core.entities import PropertyCandidate


def _candidate(**overrides):
    data = {
        "platform": "olx",
        "platform_id": "123",
        "title": "Apt",
        "description": "desc",
        "price": 1000.0,
        "area_m2": 50.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "parking": 0,
        "location": {"lat": -19.9, "lon": -43.9},
        "address": "Rua A",
        "image_urls": ["http://a"],
        "props_json": {},
        "listings": [],
        "currency": "BRL",
    }
    data.update(overrides)
    return PropertyCandidate(**data)


@pytest.mark.unit
class TestIsUnchanged:
    def test_price_change_is_not_unchanged(self):
        existing = SimpleNamespace(
            id="1", price=1000, title="Apt", description="desc", image_urls=["http://a"]
        )
        session = MagicMock()
        assert _is_unchanged(session, existing, _candidate(price=1100)) is False

    def test_identical_without_listings(self):
        existing = SimpleNamespace(
            id="1", price=1000, title="Apt", description="desc", image_urls=["http://a"]
        )
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []
        assert _is_unchanged(session, existing, _candidate()) is True

    def test_db_error_returns_false(self):
        existing = SimpleNamespace(
            id="1", price=1000, title="Apt", description="desc", image_urls=["http://a"]
        )
        session = MagicMock()
        session.query.side_effect = RuntimeError("db")
        assert _is_unchanged(session, existing, _candidate()) is False

    def test_existing_listings_missing_from_candidate(self):
        existing = SimpleNamespace(
            id="1", price=1000, title="Apt", description="desc", image_urls=["http://a"]
        )
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [MagicMock()]
        assert _is_unchanged(session, existing, _candidate(listings=[])) is False


@pytest.mark.unit
class TestMatchOrCreate:
    def test_exact_match_noop(self):
        session = MagicMock()
        existing = SimpleNamespace(id="abc")
        session.query.return_value.filter_by.return_value.one_or_none.return_value = existing
        with patch("core.dedupe._update_or_noop", return_value=DedupeMatchResult("abc", "noop")) as upd:
            result = match_or_create_property(session, _candidate())
        upd.assert_called_once()
        assert result.action == "noop"

    def test_fuzzy_match_path(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.one_or_none.return_value = None
        with patch("core.dedupe._find_fuzzy_match", return_value="fuzzy-id"):
            with patch(
                "core.dedupe._update_fuzzy_match",
                return_value=DedupeMatchResult("fuzzy-id", "updated"),
            ) as upd:
                result = match_or_create_property(session, _candidate())
        upd.assert_called_once()
        assert result.property_id == "fuzzy-id"

    def test_create_path(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.one_or_none.return_value = None
        with patch("core.dedupe._find_fuzzy_match", return_value=None):
            with patch(
                "core.dedupe._create_property",
                return_value=DedupeMatchResult("new", "created"),
            ) as create:
                result = match_or_create_property(session, _candidate())
        create.assert_called_once()
        assert result.action == "created"


@pytest.mark.unit
class TestFindFuzzyMatch:
    def test_missing_location_returns_none(self):
        session = MagicMock()
        assert _find_fuzzy_match(session, _candidate(location=None), 50, 0.65, 5, "jaro_winkler") is None

    def test_match_by_title_and_area(self):
        session = MagicMock()
        row = SimpleNamespace(id="x", title="Apt", area_m2=50.0)
        session.execute.return_value.fetchall.return_value = [row]
        with patch("core.dedupe.text_similarity", return_value=0.99):
            assert _find_fuzzy_match(session, _candidate(), 50, 0.65, 5, "jaro_winkler") == "x"


@pytest.mark.unit
class TestUpdateOrNoop:
    def test_noop_when_unchanged(self):
        session = MagicMock()
        existing = SimpleNamespace(id="1")
        with patch("core.dedupe._is_unchanged", return_value=True):
            result = _update_or_noop(session, existing, _candidate())
        assert result.action == "noop"

    def test_updated_when_changed(self):
        session = MagicMock()
        existing = SimpleNamespace(
            id="1", price=1, title="", description="", image_urls=[], props_json={}, active=False
        )
        with patch("core.dedupe._is_unchanged", return_value=False):
            with patch("core.dedupe._record_candidate_listings"):
                result = _update_or_noop(session, existing, _candidate())
        assert result.action == "updated"
        assert existing.active is True


@pytest.mark.unit
class TestCreateAndFuzzyUpdate:

    def test_update_fuzzy_missing_falls_back_to_create(self):
        from core.dedupe import _update_fuzzy_match

        session = MagicMock()
        session.get.return_value = None
        with patch(
            "core.dedupe._create_property",
            return_value=DedupeMatchResult("created", "created"),
        ) as create:
            result = _update_fuzzy_match(session, "missing", _candidate())
        create.assert_called_once()
        assert result.action == "created"

    def test_update_fuzzy_updates_existing(self):
        from core.dedupe import _update_fuzzy_match

        session = MagicMock()
        prop = SimpleNamespace(id="p1", price=0, active=False, image_urls=[], props_json={})
        session.get.return_value = prop
        with patch("core.dedupe._record_candidate_listings"):
            result = _update_fuzzy_match(session, "p1", _candidate(price=2500))
        assert result.action == "updated"
        assert prop.price == 2500
        assert prop.active is True


@pytest.mark.unit
def test_create_property_with_location():
    session = MagicMock()

    class FakeProperty:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = "created-1"

    with patch("adapters.db.models.Property", FakeProperty):
        with patch("geoalchemy2.shape.from_shape", return_value="POINT"):
            with patch("shapely.geometry.Point"):
                with patch("core.dedupe._record_candidate_listings") as record:
                    result = _create_property(session, _candidate())
    session.add.assert_called_once()
    record.assert_called_once()
    assert result.action == "created"
    assert result.property_id == "created-1"


@pytest.mark.unit
def test_create_property_without_location():
    session = MagicMock()

    class FakeProperty:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = "created-2"

    with patch("adapters.db.models.Property", FakeProperty):
        with patch("core.dedupe._record_candidate_listings"):
            result = _create_property(session, _candidate(location=None))
    assert result.action == "created"
