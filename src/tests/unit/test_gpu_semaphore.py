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
