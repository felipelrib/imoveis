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
    def _existing(self, **overrides):
        data = dict(
            id="1",
            price=1000,
            title="Apt",
            description="desc",
            image_urls=["http://a"],
            address="Rua A",
            props_json={},
            location=None,
        )
        data.update(overrides)
        return SimpleNamespace(**data)

    def test_price_change_is_not_unchanged(self):
        existing = self._existing()
        session = MagicMock()
        assert _is_unchanged(session, existing, _candidate(price=1100)) is False

    def test_identical_without_listings(self):
        existing = self._existing()
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []
        # Candidate has coords but existing.location is None → treat as changed
        # unless we omit intentional mismatch; match by clearing candidate coords.
        assert _is_unchanged(session, existing, _candidate(location=None)) is True

    def test_props_json_change_is_not_unchanged(self):
        existing = self._existing()
        session = MagicMock()
        assert (
            _is_unchanged(
                session,
                existing,
                _candidate(
                    location=None,
                    props_json={"olx_location_corrected": True, "neighborhood": "Itapoã"},
                ),
            )
            is False
        )

    def test_db_error_returns_false(self):
        existing = self._existing()
        session = MagicMock()
        session.query.side_effect = RuntimeError("db")
        assert _is_unchanged(session, existing, _candidate(location=None)) is False

    def test_existing_listings_missing_from_candidate(self):
        existing = self._existing()
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [MagicMock()]
        assert _is_unchanged(session, existing, _candidate(location=None, listings=[])) is False


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

    def test_characterization_fuzzy_match_ignores_room_counts_pre_bin146(self):
        """Characterization lock (BIN-146).

        Documents the pre-fix behaviour of ``_find_fuzzy_match``: a candidate
        matching purely on geo radius + area tolerance + title similarity is
        accepted even when its bedroom/bathroom/parking counts differ from the
        nearby property's. Brazilian towers commonly repeat an identical floor
        plan per floor with a platform-templated title (e.g. "Apartamento 2
        quartos para alugar, Savassi"), so this loophole lets two genuinely
        distinct units get merged into one ``Property`` record. This test
        locks that (buggy) behaviour as of BIN-145; BIN-146 tightens
        ``_find_fuzzy_match`` to also require bedroom/bathroom/parking
        equality, at which point this same scenario should return ``None``
        instead of matching. See ``TestFuzzyMatchRoomCounts`` below for the
        post-fix assertions.
        """
        session = MagicMock()
        # Same building slot (geo/area/title all satisfied) but a different
        # unit: 3 bedrooms vs the candidate's 2.
        row = SimpleNamespace(id="x", title="Apt", area_m2=50.0, bedrooms=3, bathrooms=2, parking=1)
        session.execute.return_value.fetchall.return_value = [row]
        with patch("core.dedupe.text_similarity", return_value=0.99):
            result = _find_fuzzy_match(
                session, _candidate(bedrooms=2, bathrooms=1, parking=0), 50, 0.65, 5, "jaro_winkler"
            )
        # BIN-146: tightened matcher must NOT merge distinct units — differing
        # bedroom/bathroom/parking counts now block the fuzzy match.
        assert result is None


@pytest.mark.unit
class TestFuzzyMatchRoomCounts:
    """BIN-146: bedrooms/bathrooms/parking as an additional required-match gate."""

    def _row(self, **overrides):
        base = dict(id="x", title="Apt", area_m2=50.0, bedrooms=2, bathrooms=1, parking=0)
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_differing_bedrooms_does_not_match(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [self._row(bedrooms=3)]
        with patch("core.dedupe.text_similarity", return_value=0.99):
            assert (
                _find_fuzzy_match(session, _candidate(bedrooms=2), 50, 0.65, 5, "jaro_winkler")
                is None
            )

    def test_differing_bathrooms_does_not_match(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [self._row(bathrooms=2)]
        with patch("core.dedupe.text_similarity", return_value=0.99):
            assert (
                _find_fuzzy_match(session, _candidate(bathrooms=1), 50, 0.65, 5, "jaro_winkler")
                is None
            )

    def test_differing_parking_does_not_match(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [self._row(parking=1)]
        with patch("core.dedupe.text_similarity", return_value=0.99):
            assert (
                _find_fuzzy_match(session, _candidate(parking=0), 50, 0.65, 5, "jaro_winkler")
                is None
            )

    def test_identical_rooms_still_matches(self):
        """Legitimate match: geo/area/title AND bedrooms/bathrooms/parking all align."""
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [self._row()]
        with patch("core.dedupe.text_similarity", return_value=0.99):
            assert (
                _find_fuzzy_match(session, _candidate(), 50, 0.65, 5, "jaro_winkler") == "x"
            )

    def test_missing_room_data_falls_back_to_permissive_match(self):
        """Older/incomplete rows without bedroom/bathroom/parking data should not
        become permanently unmatchable — only block when BOTH sides report a
        value and they differ, mirroring the existing area-tolerance pattern."""
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [
            self._row(bedrooms=None, bathrooms=None, parking=None)
        ]
        with patch("core.dedupe.text_similarity", return_value=0.99):
            assert (
                _find_fuzzy_match(session, _candidate(), 50, 0.65, 5, "jaro_winkler") == "x"
            )


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
            id="1",
            price=1,
            title="",
            description="",
            image_urls=[],
            props_json={},
            address=None,
            location=None,
            active=False,
        )
        with patch("core.dedupe._is_unchanged", return_value=False):
            with patch("core.dedupe._record_candidate_listings"):
                result = _update_or_noop(session, existing, _candidate())
        assert result.action == "updated"
        assert existing.active is True

    def test_blank_candidate_does_not_wipe_description(self):
        session = MagicMock()
        existing = SimpleNamespace(
            id="1",
            price=1000.0,
            title="Apt",
            description="Keep me",
            image_urls=["http://a"],
            props_json={},
            address="Savassi",
            location="OLD_POINT",
            active=True,
        )
        candidate = _candidate(description="", price=1100.0)
        with patch("core.dedupe._is_unchanged", return_value=False):
            with patch("core.dedupe._record_candidate_listings"):
                result = _update_or_noop(session, existing, candidate)
        assert result.action == "updated"
        assert existing.description == "Keep me"
        assert existing.price == 1100.0

    def test_olx_correction_clears_stale_seller_pin(self):
        session = MagicMock()
        existing = SimpleNamespace(
            id="1",
            price=1000.0,
            title="Apt",
            description="x",
            image_urls=[],
            props_json={},
            address="São Tomáz, Belo Horizonte",
            location="SELLER_PIN",
            active=True,
        )
        candidate = _candidate(
            address="Itapoã, Belo Horizonte, MG",
            location=None,
            props_json={
                "neighborhood": "Itapoã",
                "city": "Belo Horizonte",
                "state": "MG",
                "olx_location_corrected": True,
            },
        )
        with patch("core.dedupe._is_unchanged", return_value=False):
            with patch("core.dedupe._record_candidate_listings"):
                result = _update_or_noop(session, existing, candidate)
        assert result.action == "updated"
        assert existing.location is None
        assert existing.address == "Itapoã, Belo Horizonte, MG"
        assert existing.props_json["olx_location_corrected"] is True

    def test_missing_coords_without_correction_keeps_pin(self):
        session = MagicMock()
        existing = SimpleNamespace(
            id="1",
            price=1000.0,
            title="Apt",
            description="x",
            image_urls=[],
            props_json={"city": "Belo Horizonte"},
            address="Savassi",
            location="KEEP_ME",
            active=True,
        )
        candidate = _candidate(location=None, price=1100.0)
        with patch("core.dedupe._is_unchanged", return_value=False):
            with patch("core.dedupe._record_candidate_listings"):
                result = _update_or_noop(session, existing, candidate)
        assert result.action == "updated"
        assert existing.location == "KEEP_ME"


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
