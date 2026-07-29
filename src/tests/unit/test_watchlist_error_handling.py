"""Regression test: watchlist API must not leak raw exception text on 500 (BIN-132).

Before the fix, ``add_to_watchlist`` (and 16 other call sites) caught a broad
``Exception`` and returned ``detail=str(exc)`` directly to the HTTP caller —
leaking internal details such as DB error strings. This test fails against
the pre-fix code (the old assertion would have been ``detail == raw message``)
and passes now that the route uses the shared ``raise_api_error`` helper.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.errors import GENERIC_SERVER_ERROR_DETAIL
from api.watchlist import WatchlistCreate, add_to_watchlist


@pytest.mark.unit
@patch("api.watchlist.resolve_property_uuid")
@patch("api.watchlist.SessionLocal")
def test_add_to_watchlist_returns_generic_500_body(mock_session_local, mock_resolve):
    """A DB/internal failure must surface as a generic 500, never the raw exception."""
    sensitive_message = 'password authentication failed for user "imoveis_app" on db-prod-01'
    mock_resolve.side_effect = RuntimeError(sensitive_message)

    session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = session

    principal = MagicMock(id="owner-1")
    req = WatchlistCreate(property_id="123")

    with pytest.raises(HTTPException) as exc_info:
        add_to_watchlist(req, principal)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == GENERIC_SERVER_ERROR_DETAIL
    assert "password" not in str(exc_info.value.detail)
    assert "imoveis_app" not in str(exc_info.value.detail)
    session.rollback.assert_called_once()


@pytest.mark.unit
@patch("api.watchlist.resolve_property_uuid")
@patch("api.watchlist.SessionLocal")
def test_remove_from_watchlist_returns_generic_500_body(mock_session_local, mock_resolve):
    sensitive_message = "relation \"watchlist\" does not exist at connection host db-internal:5432"
    mock_resolve.side_effect = RuntimeError(sensitive_message)

    session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = session

    principal = MagicMock(id="owner-1")

    from api.watchlist import remove_from_watchlist

    with pytest.raises(HTTPException) as exc_info:
        remove_from_watchlist("123", principal)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == GENERIC_SERVER_ERROR_DETAIL
    assert "db-internal" not in str(exc_info.value.detail)
    session.rollback.assert_called_once()
