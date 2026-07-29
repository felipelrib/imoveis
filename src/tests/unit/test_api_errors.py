"""Unit tests for the shared API error-handling helper (BIN-132).

`raise_api_error` is the single choke point ~17 API call sites now use
instead of `raise HTTPException(status_code=500, detail=str(exc))`, which
leaked internal exception text (table/column names, connection strings,
stack fragments) directly to callers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.errors import GENERIC_SERVER_ERROR_DETAIL, raise_api_error


@pytest.mark.unit
def test_raise_api_error_500_hides_exception_detail_but_logs_it():
    logger = MagicMock()
    exc = RuntimeError("connection to postgresql://user:hunter2@db:5432/prod failed")

    with pytest.raises(HTTPException) as exc_info:
        raise_api_error(logger, "some_op_failed", exc)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == GENERIC_SERVER_ERROR_DETAIL
    assert "postgresql" not in str(exc_info.value.detail)
    assert "hunter2" not in str(exc_info.value.detail)

    logger.error.assert_called_once()
    args, kwargs = logger.error.call_args
    assert args[0] == "some_op_failed"
    assert "postgresql" in kwargs.get("error", "")


@pytest.mark.unit
def test_raise_api_error_500_ignores_detail_override():
    """Even an explicit `detail=` must not leak past the generic 5xx message."""
    logger = MagicMock()
    exc = RuntimeError("boom")

    with pytest.raises(HTTPException) as exc_info:
        raise_api_error(logger, "some_op_failed", exc, detail="raw detail should be dropped")

    assert exc_info.value.detail == GENERIC_SERVER_ERROR_DETAIL


@pytest.mark.unit
def test_raise_api_error_4xx_preserves_message():
    logger = MagicMock()
    exc = ValueError("stale_before is required when mode=stale_before")

    with pytest.raises(HTTPException) as exc_info:
        raise_api_error(logger, "validation_failed", exc, status_code=400)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == str(exc)
    logger.error.assert_called_once()


@pytest.mark.unit
def test_raise_api_error_4xx_custom_detail_override():
    logger = MagicMock()
    exc = ValueError("internal validator message")

    with pytest.raises(HTTPException) as exc_info:
        raise_api_error(
            logger, "validation_failed", exc, status_code=400, detail="Bad input"
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Bad input"


@pytest.mark.unit
def test_raise_api_error_chains_original_exception():
    logger = MagicMock()
    exc = RuntimeError("boom")

    with pytest.raises(HTTPException) as exc_info:
        raise_api_error(logger, "some_op_failed", exc)

    assert exc_info.value.__cause__ is exc
