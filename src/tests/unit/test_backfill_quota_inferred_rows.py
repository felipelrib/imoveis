"""Rows whose quota refusal was inferred are counted by ``run_backfill`` (v0.14-s1.14).

The adapter reads a storm of identical transport failures as a provider throttle
when a stated refusal licenses it, and raises a quota error that also carries
``is_quota_inferred``. The runner must treat it exactly like a stated refusal —
roll the attempt back, set ``quota_exhausted`` (the signal Story 1.13's
no-progress rule counts) — and additionally count the row, so the end-of-run
banner can say how much of a run rests on that guess (DW-16).

A storm that is *not* read as quota stays what it was: a hard row error that
charges the row and feeds neither ``quota_exhausted`` nor the count.

Pure ``src/core`` logic against dict-backed doubles, with a real
``run_backfill`` and a real ``AttemptLedger``. No adapter import (AD-1): the
doubles carry the same duck-typed attributes the real errors do.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.backfill_runner import (
    AttemptLedger,
    BackfillResult,
    Checkpoint,
    DailyBudget,
    is_quota_exhausted,
    is_quota_inferred,
    run_backfill,
)

pytestmark = pytest.mark.unit


class FakeRedis:
    """Dict-backed Redis: the hash and key calls the runner makes, nothing else."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        return True

    def expire(self, key, ttl):
        return 1 if key in self.kv or key in self.hashes else 0

    def delete(self, key):
        existed = key in self.kv or key in self.hashes
        self.kv.pop(key, None)
        self.hashes.pop(key, None)
        return 1 if existed else 0

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update({k: str(v) for k, v in mapping.items()})
        if field is not None:
            h[field] = str(value)

    def hincrby(self, key, field, n=1):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + int(n))
        return int(h[field])

    def hdel(self, key, *fields):
        for f in fields:
            self.hashes.setdefault(key, {}).pop(f, None)


class _StatedQuota(RuntimeError):
    """Stand-in for ``adapters.ai.client.AIQuotaExhaustedError``."""

    is_quota_exhausted = True


class _InferredQuota(_StatedQuota):
    """Stand-in for ``adapters.ai.client.AITransportQuotaInferredError``."""

    is_quota_inferred = True


class _TransportError(ConnectionError):
    """A storm the adapter did not read as quota: the raw transport error."""


_FIXED = datetime.fromisoformat("2026-10-09T12:00:00+00:00")


async def _noop_sleep(_):
    return None


def _rows(n):
    return [
        (SimpleNamespace(id=f"prop-{i}"), SimpleNamespace(ai_score=None))
        for i in range(n)
    ]


def _run(rows, enrich, redis, ledger):
    return asyncio.run(
        run_backfill(
            rows,
            enrich_fn=enrich,
            budget=DailyBudget(redis, prefix="t", daily_limit=1000, now_fn=lambda: _FIXED),
            checkpoint=Checkpoint(redis, prefix="t", now_fn=lambda: _FIXED),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            ledger=ledger,
        )
    )


def _ledger(redis):
    return AttemptLedger(redis, prefix="t", max_attempts=3)


def _raising(exc):
    async def enrich(prop):
        raise exc

    return enrich


def test_predicate_reads_the_attribute_and_nothing_else():
    assert is_quota_inferred(_InferredQuota("quota exhausted (inferred)")) is True
    assert is_quota_inferred(_StatedQuota("429 quota exhausted")) is False
    # No class-name or text net: the flag is set by our own adapter.
    assert is_quota_inferred(RuntimeError("quota inferred from transport")) is False

    class AITransportQuotaInferredError(RuntimeError):
        pass

    assert is_quota_inferred(AITransportQuotaInferredError("x")) is False
    # An inferred refusal is still a quota refusal for the rollback predicate.
    assert is_quota_exhausted(_InferredQuota("anything")) is True


def test_an_inferred_refusal_rolls_the_attempt_back_and_counts_one_row():
    redis = FakeRedis()
    ledger = _ledger(redis)

    result = _run(_rows(3), _raising(_InferredQuota("storm")), redis, ledger)

    assert isinstance(result, BackfillResult)
    # The 1.13 signal: this pass ended on a provider refusal.
    assert result.quota_exhausted is True
    assert result.budget_exhausted is True
    assert result.quota_inferred_rows == 1
    assert result.processed == 0
    assert result.errors == 0
    # The row was charged before launch and the charge was taken back.
    assert ledger.attempts("prop-0") == 0
    assert result.to_dict()["quota_inferred_rows"] == 1


def test_a_stated_refusal_counts_no_inferred_row():
    redis = FakeRedis()
    ledger = _ledger(redis)

    result = _run(_rows(3), _raising(_StatedQuota("429 quota exhausted")), redis, ledger)

    assert result.quota_exhausted is True
    assert result.quota_inferred_rows == 0
    assert ledger.attempts("prop-0") == 0
    assert result.to_dict()["quota_inferred_rows"] == 0


def test_a_storm_not_read_as_quota_charges_the_row_and_feeds_no_quota_signal():
    redis = FakeRedis()
    ledger = _ledger(redis)

    result = _run(
        _rows(2), _raising(_TransportError("Connection reset by peer")), redis, ledger
    )

    # Not a refusal: Story 1.13's no-progress count must not be fed by this.
    assert result.quota_exhausted is False
    assert result.quota_inferred_rows == 0
    assert result.errors == 2
    assert ledger.attempts("prop-0") == 1
    assert ledger.attempts("prop-1") == 1


def test_inferred_rows_are_counted_per_row_not_per_pass():
    """Rows already in flight when the first refusal lands are counted too."""
    redis = FakeRedis()
    ledger = _ledger(redis)
    seen: list[str] = []

    async def enrich(prop):
        seen.append(prop.id)
        if prop.id == "prop-0":
            return None
        raise _InferredQuota("storm")

    result = _run(_rows(4), enrich, redis, ledger)

    assert result.processed == 1
    assert result.quota_inferred_rows == len(seen) - 1 >= 1
    for pid in seen[1:]:
        assert ledger.attempts(pid) == 0


def test_the_result_names_the_inferred_rows_and_the_count_follows():
    """A run sums rows over cycles, and a rolled-back row comes back: the ids
    are what lets the CLI count each row once."""
    redis = FakeRedis()
    ledger = _ledger(redis)
    rows = _rows(1)
    pid = str(rows[0][0].id)

    result = _run(rows, _raising(_InferredQuota("quota exhausted (inferred)")), redis, ledger)

    assert result.quota_inferred_ids == [pid]
    assert result.quota_inferred_rows == 1
