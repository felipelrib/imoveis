"""Unit tests for thread-local asyncio bridge (BIN-122)."""

from __future__ import annotations

import asyncio

import pytest

from adapters.queue.async_bridge import run_coro


@pytest.mark.unit
def test_run_coro_reuses_same_loop_across_calls():
    loops: list[asyncio.AbstractEventLoop] = []

    async def _capture():
        loops.append(asyncio.get_running_loop())
        return 1

    assert run_coro(_capture()) == 1
    assert run_coro(_capture()) == 1
    assert len(loops) == 2
    assert loops[0] is loops[1]
    assert not loops[0].is_closed()


@pytest.mark.unit
def test_run_coro_propagates_exception_and_loop_stays_usable():
    async def _boom():
        raise ValueError("enrich failed")

    with pytest.raises(ValueError, match="enrich failed"):
        run_coro(_boom())

    async def _ok():
        return "recovered"

    assert run_coro(_ok()) == "recovered"


@pytest.mark.unit
def test_run_coro_rejects_nested_running_loop():
    async def _outer():
        inner = asyncio.sleep(0)
        try:
            return run_coro(inner)
        except RuntimeError:
            inner.close()
            raise

    with pytest.raises(RuntimeError, match="already running"):
        run_coro(_outer())
