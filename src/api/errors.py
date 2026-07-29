"""Shared error-handling helper for API routes (BIN-132).

Before this helper existed, ~17 call sites across the API caught a broad
``Exception`` and returned ``detail=str(exc)`` on the HTTP response. That
leaks internal details — table/column names, connection strings, stack
fragments — directly to any caller, including unauthenticated ones on
endpoints gated only by an optional API key.

``raise_api_error`` centralizes the fix: it always logs the full exception
server-side via the caller's ``get_logger`` instance (never swallowed), and
only ever echoes the raw exception message back to the HTTP caller for
genuine sub-500 client-input errors (e.g. a deliberately raised
``ValueError`` for a validation failure raised by our own code). For 5xx
responses the caller always gets a fixed, generic message — the ``detail``
override, if any, is ignored for 5xx so a call site cannot accidentally
re-introduce a leak.
"""

from __future__ import annotations

from typing import Any, NoReturn, Optional

from fastapi import HTTPException

GENERIC_SERVER_ERROR_DETAIL = "Internal server error"


def raise_api_error(
    logger: Any,
    event: str,
    exc: Exception,
    *,
    status_code: int = 500,
    detail: Optional[str] = None,
    **log_fields: Any,
) -> NoReturn:
    """Log ``exc`` server-side, then raise a safe ``HTTPException``.

    Args:
        logger: a ``get_logger(__name__)`` instance from the calling module,
            so log entries keep the caller's module name.
        event: short structured-log event name (e.g. ``"watchlist_add_failed"``).
        exc: the caught exception. Always logged in full (``error=str(exc)``)
            and chained onto the raised ``HTTPException`` via ``from exc``.
        status_code: HTTP status to raise. Defaults to 500.
        detail: response ``detail`` for sub-500 status codes only. Ignored
            (and replaced with a generic message) for ``status_code >= 500``.
        **log_fields: extra structured fields passed through to ``logger.error``.

    Never returns — always raises ``HTTPException``.
    """
    logger.error(event, error=str(exc), **log_fields)

    if status_code >= 500:
        safe_detail = GENERIC_SERVER_ERROR_DETAIL
    else:
        safe_detail = detail if detail is not None else str(exc)

    raise HTTPException(status_code=status_code, detail=safe_detail) from exc
