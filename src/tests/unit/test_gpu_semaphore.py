"""Unit tests for Redis-backed GPU semaphore."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import redis

from adapters.queue.gpu_semaphore import GPUSemaphore


def _sem(fake_redis: MagicMock, name: str = "gpu", max_concurrent: int = 2) -> GPUSemaphore:
    with patch("adapters.queue.gpu_semaphore.get_redis", return_value=fake_redis):
        return GPUSemaphore(name=name, max_concurrent=max_concurrent)


@pytest.mark.unit
class TestGPUSemaphore:
    def test_max_concurrent_default_and_override(self):
        r = MagicMock()
        r.get.return_value = None
        sem = _sem(r, max_concurrent=3)
        assert sem.max_concurrent == 3
        r.get.return_value = b"5"
        assert sem.max_concurrent == 5

    def test_available_fallback_on_error(self):
        r = MagicMock()
        # First get (semaphore counter) fails; property should still return default.
        # The fallback asks for the configured limit, so let that second lookup
        # succeed with the default value.
        r.get.side_effect = [RuntimeError("boom"), None]
        sem = _sem(r, max_concurrent=4)
        assert sem.available == 4

    def test_available_reads_counter(self):
        r = MagicMock()
        r.get.side_effect = [b"1", None]  # counter then unused for max
        sem = _sem(r, max_concurrent=2)
        # first get is semaphore key
        r.get.side_effect = None
        r.get.return_value = b"1"
        assert sem.available == 1

    def test_acquire_success(self):
        r = MagicMock()
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        pipe.get.return_value = b"2"
        sem = _sem(r, max_concurrent=2)
        assert sem.acquire(timeout=10) is True
        pipe.multi.assert_called_once()
        pipe.execute.assert_called_once()

    def test_acquire_without_slot_ttl_uses_default(self):
        """No `slot_ttl` passed -> falls back to DEFAULT_SLOT_TTL_SECONDS (3600),
        matching pre-BIN-147 behavior for callers that don't opt in."""
        r = MagicMock()
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        pipe.get.return_value = b"2"
        sem = _sem(r, max_concurrent=2)
        assert sem.acquire(timeout=10) is True
        _key, ttl, _value = pipe.setex.call_args[0]
        assert ttl == 3600

    def test_acquire_ttl_comes_from_slot_ttl_not_caller_timeout(self):
        """BIN-147 regression: the held-slot Redis key TTL must be set from an
        explicit `slot_ttl` (meant to be derived from the task's hard time
        limit), never from the caller's short wait-intent `timeout` — passing
        both with very different values proves they're decoupled."""
        r = MagicMock()
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        pipe.get.return_value = b"2"
        sem = _sem(r, max_concurrent=2)

        task_hard_time_limit_plus_margin = 660  # e.g. AI_ENRICH_GPU_SLOT_TTL_SECONDS
        assert sem.acquire(timeout=30, slot_ttl=task_hard_time_limit_plus_margin) is True

        _key, ttl_used, _value = pipe.setex.call_args[0]
        assert ttl_used == task_hard_time_limit_plus_margin
        assert ttl_used != 30

    def test_acquire_exhausted(self):
        r = MagicMock()
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        pipe.get.return_value = b"0"
        sem = _sem(r, max_concurrent=2)
        assert sem.acquire() is False
        pipe.unwatch.assert_called_once()

    def test_acquire_retries_watch_error_then_succeeds(self):
        r = MagicMock()
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        calls = {"n": 0}

        def watch(_key):
            calls["n"] += 1
            if calls["n"] == 1:
                raise redis.WatchError()

        pipe.watch.side_effect = watch
        pipe.get.return_value = b"1"
        sem = _sem(r)
        assert sem.acquire() is True

    def test_acquire_fallback_true_on_redis_error(self):
        r = MagicMock()
        r.pipeline.side_effect = RuntimeError("redis down")
        sem = _sem(r)
        assert sem.acquire() is True

    def test_release_caps_at_limit(self):
        r = MagicMock()
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        pipe.get.return_value = b"9"
        r.get.return_value = b"2"  # max_concurrent override
        sem = _sem(r, max_concurrent=2)
        sem.release()
        args = pipe.setex.call_args[0]
        assert args[2] == 2

    def test_scale_sets_limit(self):
        r = MagicMock()
        sem = _sem(r)
        sem.scale(7)
        r.set.assert_called_once_with("semaphore:limit:gpu", 7)

    def test_scale_logs_on_error(self):
        r = MagicMock()
        r.set.side_effect = RuntimeError("nope")
        sem = _sem(r)
        sem.scale(3)  # should not raise


@pytest.mark.unit
def test_available_uses_counter_value():
    r = MagicMock()
    r.get.return_value = b"3"
    sem = _sem(r, max_concurrent=5)
    assert sem.available == 3


@pytest.mark.unit
def test_release_initializes_from_zero():
    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value = pipe
    pipe.get.return_value = None
    r.get.return_value = None
    sem = _sem(r, max_concurrent=2)
    sem.release()
    assert pipe.setex.call_args[0][2] == 1


@pytest.mark.unit
def test_release_logs_on_error():
    r = MagicMock()
    r.pipeline.side_effect = RuntimeError("pipe fail")
    sem = _sem(r)
    sem.release()  # should not raise


class _TTLFakeRedis:
    """Minimal Redis double with real SETEX/GET TTL decay, driven by an
    injectable fake clock (no real sleeping needed in the test).

    GPUSemaphore.acquire()/release() use `pipeline()` purely for WATCH/MULTI/
    EXEC optimistic-locking around a single key — there's no concurrent writer
    in this test, so `pipeline()` returning `self` and treating watch/multi/
    unwatch/execute as no-ops is enough for GET/SETEX to behave like the real
    thing.
    """

    def __init__(self):
        self._value: dict = {}
        self._expires_at: dict = {}
        self.now = 0.0

    def _expire_if_due(self, key):
        exp = self._expires_at.get(key)
        if exp is not None and self.now >= exp:
            self._value.pop(key, None)
            self._expires_at.pop(key, None)

    def get(self, key):
        self._expire_if_due(key)
        return self._value.get(key)

    def setex(self, key, ttl, value):
        self._value[key] = str(value).encode()
        self._expires_at[key] = self.now + ttl

    def pipeline(self):
        return self

    def watch(self, _key):
        pass

    def unwatch(self):
        pass

    def multi(self):
        pass

    def execute(self):
        pass


@pytest.mark.unit
def test_long_running_task_does_not_lose_slot_before_it_finishes():
    """BIN-147 regression (end-to-end through real TTL decay): a task that
    passes a short `timeout` wait-intent (mirrors tasks.py's historical
    `sem.acquire(timeout=30)`) but a `slot_ttl` derived from its actual hard
    time limit must still show its slot held well past `timeout` seconds —
    proving the fix, since the pre-BIN-147 code set the Redis TTL from
    `timeout` and would have silently freed the slot at 30s.
    """
    fake = _TTLFakeRedis()
    with patch("adapters.queue.gpu_semaphore.get_redis", return_value=fake):
        sem = GPUSemaphore(name="gpu", max_concurrent=1)

    task_hard_time_limit_plus_margin = 660  # e.g. AI_ENRICH_GPU_SLOT_TTL_SECONDS
    assert sem.acquire(timeout=30, slot_ttl=task_hard_time_limit_plus_margin) is True
    assert sem.available == 0  # slot held immediately after acquire

    # Old conflated behavior would have expired the key here (TTL == 30).
    fake.now += 90
    assert sem.available == 0, "slot must still be held long after the old 30s timeout"

    # Still held right up to just before the real (decoupled) TTL.
    fake.now += task_hard_time_limit_plus_margin - 100
    assert sem.available == 0

    # Only expires once the real TTL elapses (e.g. worker was hard-killed and
    # never reached `finally: sem.release()`).
    fake.now += 20
    assert sem.available == 1  # max_concurrent, i.e. Redis key finally expired


@pytest.mark.unit
def test_ai_enrich_call_site_uses_task_time_limit_not_wait_timeout():
    """BIN-147 wiring check: tasks.ai_enrich must pass a `slot_ttl` derived
    from its own Celery hard `time_limit` (not the 30s retry/backoff
    `timeout`), and the task itself must declare that hard time limit so
    Celery's own SIGKILL backstop and the semaphore TTL stay consistent."""
    from adapters.queue import tasks

    assert tasks.AI_ENRICH_GPU_SLOT_TTL_SECONDS > tasks.AI_ENRICH_TIME_LIMIT_SECONDS
    assert tasks.ai_enrich.time_limit == tasks.AI_ENRICH_TIME_LIMIT_SECONDS
    assert tasks.ai_enrich.soft_time_limit == tasks.AI_ENRICH_SOFT_TIME_LIMIT_SECONDS
    # The old bug: TTL sourced from the 30s wait-intent. Guard against
    # regressing back to that by asserting the real gap is generous.
    assert tasks.AI_ENRICH_GPU_SLOT_TTL_SECONDS - 30 > 60
