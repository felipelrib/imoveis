"""Unit tests for CheckpointStore."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adapters.scrapers.checkpoint_store import CheckpointStore, OLXCheckpoint


@pytest.mark.unit
class TestCheckpointStore:
    def test_get_missing_returns_empty(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        assert CheckpointStore(session).get("olx") == {}

    def test_get_validates_known_platform(self):
        session = MagicMock()
        row = MagicMock()
        row.data = {"page": 3, "url_index": 1, "processed_ids": ["a"]}
        session.query.return_value.filter_by.return_value.first.return_value = row
        data = CheckpointStore(session).get("olx")
        assert data == OLXCheckpoint(page=3, url_index=1, processed_ids=["a"]).model_dump()

    def test_get_invalid_data_returns_empty(self):
        session = MagicMock()
        row = MagicMock()
        row.data = {"page": "not-an-int"}
        session.query.return_value.filter_by.return_value.first.return_value = row
        assert CheckpointStore(session).get("olx") == {}

    def test_get_unknown_platform_returns_raw(self):
        session = MagicMock()
        row = MagicMock()
        row.data = {"custom": True}
        session.query.return_value.filter_by.return_value.first.return_value = row
        assert CheckpointStore(session).get("other") == {"custom": True}

    def test_set_updates_existing(self):
        session = MagicMock()
        existing = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = existing
        CheckpointStore(session).set("olx", {"page": 2})
        assert existing.data == {"page": 2}
        session.commit.assert_called_once()

    def test_set_creates_when_missing(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        CheckpointStore(session).set("olx", {"page": 1})
        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_set_rolls_back_and_reraises(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.side_effect = RuntimeError("db")
        with pytest.raises(RuntimeError, match="db"):
            CheckpointStore(session).set("olx", {"page": 1})
        session.rollback.assert_called_once()
