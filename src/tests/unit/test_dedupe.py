"""Unit tests for the text similarity function (now using rapidfuzz Jaro-Winkler)."""

from __future__ import annotations

import pytest

from core.dedupe import text_similarity


def test_identical_strings_score_one():
    assert text_similarity("Apartamento 2 quartos", "Apartamento 2 quartos") == pytest.approx(1.0, abs=0.01)


def test_empty_strings_score_zero():
    assert text_similarity("", "") == 0.0
    assert text_similarity(None, "anything") == 0.0
    assert text_similarity("anything", None) == 0.0


def test_completely_different_strings_score_low():
    score = text_similarity("Apartamento moderno", "Casa com piscina e churrasqueira")
    assert score < 0.7


def test_similar_strings_score_high():
    # Real estate copy-paste with minor change (price diff, same text)
    a = "Lindo apartamento com 2 quartos, 1 vaga, próximo ao metrô"
    b = "Lindo apartamento com 2 quartos, 1 vaga, próximo ao metrô."
    assert text_similarity(a, b) > 0.85


def test_token_order_variation():
    # Jaro-Winkler handles transpositions better than SequenceMatcher
    a = "quarto sala cozinha"
    b = "sala cozinha quarto"
    score = text_similarity(a, b)
    # Both contain the same words — should score reasonably high
    assert score > 0.5


def test_returns_normalized_float():
    score = text_similarity("foo", "bar")
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Price-history tracking tests
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, call

from core.dedupe import _record_price_change


class FakeRow:
    """Minimal stand-in for a SQLAlchemy row with .id and .price attributes."""

    def __init__(self, row_id: str, price: float):
        self.id = row_id
        self.price = price


def _make_mock_session(open_row=None):
    """Build a mock Session that returns *open_row* for the first query."""
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = open_row
    return session


class TestRecordPriceChange:
    def test_first_seen_seeds_open_interval(self):
        """When no open row exists, an initial history row is inserted."""
        session = _make_mock_session(open_row=None)

        _record_price_change(session, "prop-1", 5000.0)

        # Should execute: one SELECT + one INSERT (seed)
        assert session.execute.call_count == 2
        insert_call = session.execute.call_args_list[1]
        sql = str(insert_call[0][0])
        assert "INSERT INTO price_history" in sql
        assert "NULL" in sql  # open interval — end_ts is NULL in SQL
        params = insert_call[0][1]
        assert params["pid"] == "prop-1"
        assert params["price"] == 5000.0

    def test_unchanged_price_noop(self):
        """When the open interval has the same price, nothing is inserted."""
        open_row = FakeRow("hist-1", 5000.0)
        session = _make_mock_session(open_row=open_row)

        _record_price_change(session, "prop-1", 5000.0)

        # Only the SELECT should have been executed — no UPDATE or INSERT
        assert session.execute.call_count == 1

    def test_price_change_closes_and_inserts(self):
        """When price differs, the old interval is closed and a new one is opened."""
        open_row = FakeRow("hist-1", 5000.0)
        session = _make_mock_session(open_row=open_row)

        _record_price_change(session, "prop-1", 5500.0)

        # SELECT + UPDATE (close old) + INSERT (new open interval)
        assert session.execute.call_count == 3
        update_call = session.execute.call_args_list[1]
        assert "UPDATE price_history SET end_ts" in str(update_call[0][0])
        insert_call = session.execute.call_args_list[2]
        insert_sql = str(insert_call[0][0])
        assert "INSERT INTO price_history" in insert_sql
        assert "NULL" in insert_sql  # open interval
        assert insert_call[0][1]["price"] == 5500.0

    def test_price_drop_still_records(self):
        """A price decrease is treated the same as an increase."""
        open_row = FakeRow("hist-2", 6000.0)
        session = _make_mock_session(open_row=open_row)

        _record_price_change(session, "prop-2", 4500.0)

        assert session.execute.call_count == 3
        insert_call = session.execute.call_args_list[2]
        assert insert_call[0][1]["price"] == 4500.0

    def test_listing_type_and_platform_included_in_seed(self):
        """First-seen seed includes listing_type and platform parameters."""
        session = _make_mock_session(open_row=None)

        _record_price_change(
            session, "prop-1", 2000.0,
            listing_type="rent", platform="olx", property_listing_id="pl-1",
        )

        assert session.execute.call_count == 2
        insert_call = session.execute.call_args_list[1]
        params = insert_call[0][1]
        assert params["lt"] == "rent"
        assert params["platform"] == "olx"
        assert params["plid"] == "pl-1"
        sql = str(insert_call[0][0])
        assert "INSERT INTO price_history" in sql

    def test_listing_type_filters_open_interval_query(self):
        """SELECT filters by listing_type and platform."""
        session = _make_mock_session(open_row=None)

        _record_price_change(
            session, "prop-1", 2000.0,
            listing_type="rent", platform="quintoandar",
        )

        # Verify the SELECT query includes listing_type and platform filters
        select_call = session.execute.call_args_list[0]
        sql = str(select_call[0][0])
        assert "listing_type = :lt" in sql
        assert "platform = :platform" in sql
        params = select_call[0][1]
        assert params["lt"] == "rent"
        assert params["platform"] == "quintoandar"

    def test_rent_and_sale_independent_noop(self):
        """Changing rent price does not affect sale history (noop on sale)."""
        # First: record a sale price
        session_seed = _make_mock_session(open_row=None)
        _record_price_change(session_seed, "prop-1", 500000.0, listing_type="sale", platform="olx")
        assert session_seed.execute.call_count == 2  # SELECT + INSERT

        # Now: record a rent price — sale has no open interval, so it seeds rent
        session_rent = _make_mock_session(open_row=None)
        _record_price_change(session_rent, "prop-1", 2000.0, listing_type="rent", platform="olx")
        assert session_rent.execute.call_count == 2  # SELECT + INSERT (new rent)

        # Verify rent params are correct (not confused with sale)
        insert_call = session_rent.execute.call_args_list[1]
        params = insert_call[0][1]
        assert params["lt"] == "rent"
        assert params["price"] == 2000.0

    def test_per_platform_independence(self):
        """Price change on one platform does not affect another platform's history."""
        # Seed OLX open interval
        session_olx = _make_mock_session(open_row=None)
        _record_price_change(session_olx, "prop-1", 2000.0, listing_type="rent", platform="olx")
        assert session_olx.execute.call_count == 2

        # Seed QuintoAndar open interval
        session_qa = _make_mock_session(open_row=None)
        _record_price_change(session_qa, "prop-1", 2200.0, listing_type="rent", platform="quintoandar")
        assert session_qa.execute.call_count == 2

        # Now change OLX price — should only affect OLX
        olx_open = FakeRow("hist-olx", 2000.0)
        session_update = _make_mock_session(open_row=olx_open)
        _record_price_change(session_update, "prop-1", 1900.0, listing_type="rent", platform="olx")
        # SELECT + UPDATE (close) + INSERT (new)
        assert session_update.execute.call_count == 3
        insert_call = session_update.execute.call_args_list[2]
        params = insert_call[0][1]
        assert params["platform"] == "olx"
        assert params["price"] == 1900.0

    def test_property_listing_id_in_insert(self):
        """property_listing_id is included in INSERT statements."""
        session = _make_mock_session(open_row=None)

        _record_price_change(
            session, "prop-1", 3000.0,
            listing_type="rent", platform="olx", property_listing_id="pl-42",
        )

        insert_call = session.execute.call_args_list[1]
        params = insert_call[0][1]
        assert params["plid"] == "pl-42"

    def test_untyped_default_is_sale(self):
        """When listing_type is not specified, defaults to 'sale'."""
        session = _make_mock_session(open_row=None)

        _record_price_change(session, "prop-1", 500000.0)

        select_call = session.execute.call_args_list[0]
        params = select_call[0][1]
        assert params["lt"] == "sale"
