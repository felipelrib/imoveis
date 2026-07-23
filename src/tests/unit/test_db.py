"""Unit tests for infra.db session helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_get_session_yields_and_closes():
    fake_session = MagicMock()
    with patch("infra.db.SessionLocal", return_value=fake_session):
        from infra.db import get_session

        gen = get_session()
        assert next(gen) is fake_session
        with pytest.raises(StopIteration):
            next(gen)
    fake_session.close.assert_called_once()


@pytest.mark.unit
def test_close_db_disposes_engine():
    with patch("infra.db.SessionLocal") as session_local:
        with patch("infra.db.engine") as engine:
            from infra.db import close_db

            close_db()
    session_local.close_all.assert_called_once()
    engine.dispose.assert_called_once()
