"""Structured JSON logging for the application.

Provides a pre-configured logger that outputs structured JSON lines
suitable for log aggregation (ELK, Loki, CloudWatch, etc.).

Usage:
    from infra.logging import get_logger
    logger = get_logger(__name__)
    logger.info("scrape_started", platform="quintoandar", page=1)
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class _JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge any extra structured fields
        if hasattr(record, "_extra"):
            log_entry.update(record._extra)
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


class _StructuredLogger:
    """Thin wrapper around stdlib Logger that accepts **kwargs as structured fields."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        record = self._logger.makeRecord(
            name=self._logger.name,
            level=level,
            fn="",
            lno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        record._extra = kwargs  # type: ignore[attr-defined]
        self._logger.handle(record)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, **kwargs)


_initialized = False


def _ensure_root_handler() -> None:
    global _initialized
    if _initialized:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    _initialized = True


def get_logger(name: str) -> _StructuredLogger:
    """Return a structured logger for the given module name."""
    _ensure_root_handler()
    return _StructuredLogger(logging.getLogger(name))
