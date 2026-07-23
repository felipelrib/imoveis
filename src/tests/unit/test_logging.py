"""Unit tests for structured JSON logging helpers."""

from __future__ import annotations

import json
import logging

import pytest

from infra.logging import _ensure_root_handler, _JSONFormatter, get_logger


@pytest.mark.unit
class TestLogging:
    def test_json_formatter_basic(self):
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        payload = json.loads(_JSONFormatter().format(record))
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert "timestamp" in payload

    def test_json_formatter_with_exception_and_extra(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="t",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failed",
                args=(),
                exc_info=sys.exc_info(),
            )
            record.extra_fields = {"request_id": "abc"}
            payload = json.loads(_JSONFormatter().format(record))
        assert payload["request_id"] == "abc"
        assert "exception" in payload

    def test_structured_logger_info(self, caplog):
        logger = get_logger("unit.test.logging")
        with caplog.at_level(logging.INFO):
            logger.info("event", foo=1)
        assert any("event" in r.getMessage() for r in caplog.records)

    def test_ensure_root_handler_idempotent(self):
        root = logging.getLogger()
        before = list(root.handlers)
        _ensure_root_handler()
        _ensure_root_handler()
        assert len(root.handlers) >= len(before)


@pytest.mark.unit
def test_structured_logger_exception(caplog):
    logger = get_logger("unit.test.logging.exc")
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError("x")
        except RuntimeError:
            logger.exception("failed_op", code=1)
    assert any("failed_op" in r.getMessage() for r in caplog.records)
