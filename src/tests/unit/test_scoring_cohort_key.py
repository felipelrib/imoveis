"""Unit tests: scoring cohort key prefers spatial neighbourhood over props_json."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from adapters.metrics.scoring import _COHORT_KEY_SQL, _property_neighborhood_key


class TestPropertyNeighborhoodKey:
    def test_prefers_spatial_fk_name_over_props_json(self):
        nid = uuid4()
        prop = MagicMock()
        prop.neighborhood_id = nid
        prop.props_json = {"neighborhood": "StringOnlyCohort"}

        neighborhood = MagicMock()
        neighborhood.name = "FixtureA"
        session = MagicMock()
        session.get.return_value = neighborhood

        assert _property_neighborhood_key(session, prop) == "FixtureA"
        session.get.assert_called_once()

    def test_string_fallback_when_no_fk(self):
        prop = MagicMock()
        prop.neighborhood_id = None
        prop.props_json = {"neighborhood": "StringOnlyCohort"}
        session = MagicMock()

        assert _property_neighborhood_key(session, prop) == "StringOnlyCohort"
        session.get.assert_not_called()

    def test_unknown_when_no_fk_and_no_string(self):
        prop = MagicMock()
        prop.neighborhood_id = None
        prop.props_json = {}
        session = MagicMock()

        assert _property_neighborhood_key(session, prop) == "Unknown"

    def test_unknown_when_props_json_none(self):
        prop = MagicMock()
        prop.neighborhood_id = None
        prop.props_json = None
        session = MagicMock()

        assert _property_neighborhood_key(session, prop) == "Unknown"

    def test_falls_back_to_string_when_fk_row_missing(self):
        prop = MagicMock()
        prop.neighborhood_id = uuid4()
        prop.props_json = {"neighborhood": "StringOnlyCohort"}
        session = MagicMock()
        session.get.return_value = None

        assert _property_neighborhood_key(session, prop) == "StringOnlyCohort"


class TestCohortKeySqlFragment:
    def test_sql_prefers_fk_name_before_props_json(self):
        assert "n.name" in _COHORT_KEY_SQL
        assert "props_json->>'neighborhood'" in _COHORT_KEY_SQL
        assert _COHORT_KEY_SQL.index("n.name") < _COHORT_KEY_SQL.index(
            "props_json->>'neighborhood'"
        )
