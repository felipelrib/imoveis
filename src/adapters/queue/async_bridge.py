"""Thread-local event-loop bridge for sync Celery tasks (BIN-122).

Prefork AI workers call async httpx/Ollama clients from sync tasks. ``asyncio.run``
creates and closes a fresh loop per invocation — safe but wasteful. This helper
reuses one loop per worker thread without changing enrichment outputs.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Awaitable, TypeVar

T = TypeVar("T")

_thread_local = threading.local()


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _thread_local.loop = loop
    return loop


def run_coro(coro: Awaitable[T]) -> T:
    """Run ``coro`` on this thread's persistent event loop.

    Raises ``RuntimeError`` if a loop is already running on this thread (nested
    use from async code is not supported — sync Celery must not nest).
    """
    loop = _get_or_create_loop()
    if loop.is_running():
        raise RuntimeError(
            "run_coro: event loop is already running; "
            "cannot bridge from inside a running loop"
        )
    return loop.run_until_complete(coro)
