import json
import logging
import time
from typing import Any, Dict


class _JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Adicionar campos extras se existirem
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)

        # Adicionar informações de exceção se houver
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


class _StructuredLogger:
    """Thin wrapper around stdlib Logger that accepts **kwargs as structured fields."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        """Log a message with structured data."""
        extra_fields = kwargs if kwargs else {}

        # Criar um record customizado com os campos extras
        class LogRecord(logging.LogRecord):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.extra_fields = extra_fields

        # Usar o método interno do logger para evitar problemas de formatação
        if hasattr(self.logger, "makeRecord"):
            record = self.logger.makeRecord(
                self.logger.name,
                level,
                "unknown",
                0,
                msg,
                None,
                None,
                extra=extra_fields,
            )
            self.logger.handle(record)
        else:
            # Fallback para o comportamento padrão
            self.logger.log(level, msg, extra=extra_fields)

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


def _ensure_root_handler() -> None:
    """Ensure root logger has a JSON formatter."""
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JSONFormatter())
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)


def get_logger(name: str) -> _StructuredLogger:
    """Get a structured logger."""
    _ensure_root_handler()
    return _StructuredLogger(name)
