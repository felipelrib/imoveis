"""Completion detection + non-enrichable accounting for the backfill (v0.13-fu3).

The runner only ever processes **active** rows, but ``--continuous`` measured
completion as ``total properties - enriched``. Inactive un-enriched rows (494 on
2026-08-05) made that difference permanently positive, so the ``remaining == 0``
branch was dead and every finished run fell through the "no progress this cycle"
safety valve instead.

These tests pin the replacement: a :class:`QueueCensus` measured against the real
candidate queue, an :class:`AttemptLedger` that retires rows which never leave
that queue, and the row partition that keeps permanently non-enrichable rows out
of the work set. Pure logic — dict-backed fake Redis, no DB or network.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.backfill_runner import (
    AttemptLedger,
    QueueCensus,
    partition_candidates,
    run_backfill,
)

pytestmark = pytest.mark.unit


class FakeRedis:
    """In-memory Redis covering the hash ops the ledger uses."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(key, {})
        if mapping:
            for k, v in mapping.items():
                h[k] = str(v)
        if field is not None:
            h[field] = str(value)

    def hincrby(self, key, field, n=1):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + int(n))
        return int(h[field])

    def hdel(self, key, *fields):
        h = self.hashes.setdefault(key, {})
        for f in fields:
            h.pop(f, None)

    def delete(self, key):
        self.hashes.pop(key, None)

    def expire(self, key, ttl):
        self.expires[key] = ttl


def _prop(pid, *, images=8):
    return SimpleNamespace(
        id=pid,
        image_urls=[f"http://img/{pid}/{i}.jpg" for i in range(images)],
        description="",
        first_seen=None,
    )


GATE_KWARGS = {
    "enabled": True,
    "floor_min": 8,
    "max_images_per_property": 8,
    "coverage_ratio": 1.0,
    "min_photos": None,
}


# ---------------------------------------------------------------------------
# QueueCensus — the honest denominator
# ---------------------------------------------------------------------------


def test_census_remaining_excludes_inactive_rows():
    """The bug: total-minus-enriched counted 494 inactive rows the runner never fetches."""
    census = QueueCensus(
        total_properties=26226, enriched=7626, candidates=18106,
        blocked_no_photos=0, quarantined=0,
    )
    # Naive arithmetic said 18,600; the real work queue is the candidate count.
    assert census.remaining == 18106
    assert 26226 - 7626 == 18600  # what the old _remaining() reported
    assert census.enrichable == 25732
    assert census.non_enrichable == 494
    assert not census.is_complete


def test_census_is_complete_when_queue_drains_despite_unenriched_rows():
    census = QueueCensus(
        total_properties=26226, enriched=25732, candidates=0,
        blocked_no_photos=0, quarantined=0,
    )
    assert census.remaining == 0
    assert census.is_complete
    assert census.non_enrichable == 494  # inactive rows never become enrichable


def test_census_subtracts_photo_blocked_and_quarantined_from_remaining():
    census = QueueCensus(
        total_properties=1000, enriched=400, candidates=100,
        blocked_no_photos=30, quarantined=10,
    )
    assert census.remaining == 60
    assert census.enrichable == 460
    assert census.non_enrichable == 540
    assert not census.is_complete


def test_census_complete_when_only_unworkable_rows_remain():
    """Photo-blocked + quarantined rows must not keep --continuous alive."""
    census = QueueCensus(
        total_properties=100, enriched=80, candidates=20,
        blocked_no_photos=12, quarantined=8,
    )
    assert census.remaining == 0
    assert census.is_complete
    assert census.blocked_total == 20


def test_census_never_reports_negative_remaining():
    census = QueueCensus(
        total_properties=10, enriched=5, candidates=3,
        blocked_no_photos=3, quarantined=3,
    )
    assert census.remaining == 0
    assert census.non_enrichable >= 0


def test_census_progress_pct():
    census = QueueCensus(
        total_properties=100, enriched=25, candidates=75,
        blocked_no_photos=0, quarantined=0,
    )
    assert census.progress_pct == pytest.approx(25.0)
    empty = QueueCensus(
        total_properties=0, enriched=0, candidates=0,
        blocked_no_photos=0, quarantined=0,
    )
    assert empty.progress_pct == 100.0  # nothing to do reads as done, not a ZeroDivisionError


# ---------------------------------------------------------------------------
# AttemptLedger — retire rows that never leave the queue
# ---------------------------------------------------------------------------


def test_ledger_quarantines_after_max_attempts():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=3)
    assert not ledger.is_quarantined("p1")
    for expected in (1, 2):
        assert ledger.record_attempt("p1") == expected
        assert not ledger.is_quarantined("p1")
    assert ledger.record_attempt("p1") == 3
    assert ledger.is_quarantined("p1")
    assert ledger.quarantined_count() == 1
    assert ledger.quarantined_ids() == ["p1"]


def test_ledger_counts_attempts_not_only_errors():
    """A row that 'succeeds' but stays a candidate (ai_score=0) also loops forever."""
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=2)
    ledger.record_attempt("p1")  # succeeded, but row came back next cycle
    ledger.record_attempt("p1")
    assert ledger.is_quarantined("p1")
    # No error was ever recorded, so the reason states the observed symptom.
    assert "attempt" in ledger.reason_for("p1").lower()


def test_ledger_reason_prefers_the_last_recorded_error():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=2)
    ledger.record_attempt("p1")
    ledger.record_error("p1", "429 rate limited")
    ledger.record_attempt("p1")
    ledger.record_error("p1", "image download failed")
    assert ledger.is_quarantined("p1")
    assert ledger.reason_for("p1") == "image download failed"
    assert ledger.quarantine_report() == {"p1": "image download failed"}


def test_ledger_clear_and_reset_release_rows():
    redis = FakeRedis()
    ledger = AttemptLedger(redis, prefix="t", max_attempts=1)
    ledger.record_attempt("p1")
    ledger.record_attempt("p2")
    assert ledger.quarantined_count() == 2

    ledger.clear("p1")
    assert not ledger.is_quarantined("p1")
    assert ledger.quarantined_count() == 1

    ledger.reset_all()
    assert ledger.quarantined_count() == 0
    assert ledger.attempts("p2") == 0


def test_ledger_max_attempts_floors_at_one():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=0)
    assert ledger.max_attempts == 1
    ledger.record_attempt("p1")
    assert ledger.is_quarantined("p1")


def test_ledger_tolerates_bytes_redis_clients():
    class BytesRedis(FakeRedis):
        def hgetall(self, key):
            return {k.encode(): v.encode() for k, v in super().hgetall(key).items()}

        def hget(self, key, field):
            v = super().hget(key, field)
            return None if v is None else v.encode()

    ledger = AttemptLedger(BytesRedis(), prefix="t", max_attempts=2)
    ledger.record_attempt("p1")
    ledger.record_attempt("p1")
    ledger.record_error("p1", "boom")
    assert ledger.is_quarantined("p1")
    assert ledger.quarantined_ids() == ["p1"]
    assert ledger.reason_for("p1") == "boom"


# ---------------------------------------------------------------------------
# partition_candidates — keep unworkable rows out of the work set
# ---------------------------------------------------------------------------


def test_partition_drops_rows_that_fail_the_photo_gate():
    rows = [
        (_prop("ok", images=8), None),
        (_prop("thin", images=3), None),
        (_prop("none", images=0), None),
    ]
    part = partition_candidates(rows, gate_kwargs=GATE_KWARGS)

    assert [p.id for p, _ in part.workable] == ["ok"]
    assert sorted(part.blocked_no_photos) == ["none", "thin"]
    assert part.quarantined == []


def test_partition_drops_quarantined_rows():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=1)
    ledger.record_attempt("bad")
    rows = [(_prop("ok"), None), (_prop("bad"), None)]

    part = partition_candidates(rows, gate_kwargs=GATE_KWARGS, ledger=ledger)

    assert [p.id for p, _ in part.workable] == ["ok"]
    assert part.quarantined == ["bad"]


def test_partition_counts_a_row_once_when_both_blocked_and_quarantined():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=1)
    ledger.record_attempt("thin")
    rows = [(_prop("thin", images=1), None)]

    part = partition_candidates(rows, gate_kwargs=GATE_KWARGS, ledger=ledger)

    assert part.workable == []
    assert len(part.blocked_no_photos) + len(part.quarantined) == 1


def test_partition_still_drops_zero_image_rows_when_the_gate_is_disabled():
    rows = [(_prop("none", images=0), None)]
    part = partition_candidates(
        rows, gate_kwargs={**GATE_KWARGS, "enabled": False}
    )
    # Gate off still drops zero-image rows: the visual stage cannot run at all.
    assert part.workable == []
    assert part.blocked_no_photos == ["none"]


# ---------------------------------------------------------------------------
# run_backfill ledger integration
# ---------------------------------------------------------------------------


class _Budget:
    """Always-funded budget stub."""

    def remaining(self):
        return 10_000

    def try_consume(self, n):
        return True

    def seconds_until_reset(self):
        return 0.0


class _Checkpoint:
    def __init__(self):
        self.advanced = []

    def advance(self, pid):
        self.advanced.append(pid)


def _run(rows, **kw):
    return asyncio.run(run_backfill(rows, **kw))


def test_run_backfill_records_attempts_and_errors_in_the_ledger():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=3)
    rows = [(_prop("good"), None), (_prop("bad"), None)]

    async def enrich(prop):
        if prop.id == "bad":
            raise RuntimeError("boom")

    result = _run(
        rows,
        enrich_fn=enrich,
        budget=_Budget(),
        checkpoint=_Checkpoint(),
        requests_per_property=3,
        ledger=ledger,
    )

    assert result.processed == 1
    assert result.errors == 1
    assert ledger.attempts("good") == 1
    assert ledger.attempts("bad") == 1
    assert ledger.reason_for("bad") == "boom"
    assert ledger.quarantined_count() == 0  # one failure is not yet terminal


def test_run_backfill_skips_already_quarantined_rows_without_spending_budget():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=1)
    ledger.record_attempt("bad")
    calls = []

    async def enrich(prop):
        calls.append(prop.id)

    result = _run(
        [(_prop("bad"), None), (_prop("good"), None)],
        enrich_fn=enrich,
        budget=_Budget(),
        checkpoint=_Checkpoint(),
        requests_per_property=3,
        ledger=ledger,
    )

    assert calls == ["good"]
    assert result.processed == 1
    assert result.skipped_quarantined == 1
    assert result.requests_consumed == 3  # quarantined row cost nothing


def test_run_backfill_quarantines_a_row_that_keeps_failing_across_runs():
    """Three cycles of the same failing row → excluded on the fourth."""
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=3)
    attempts = []

    async def enrich(prop):
        attempts.append(prop.id)
        raise RuntimeError("always fails")

    for _ in range(4):
        _run(
            [(_prop("bad"), None)],
            enrich_fn=enrich,
            budget=_Budget(),
            checkpoint=_Checkpoint(),
            requests_per_property=3,
            ledger=ledger,
        )

    assert attempts == ["bad", "bad", "bad"]  # 4th cycle skipped it
    assert ledger.is_quarantined("bad")


def test_run_backfill_without_a_ledger_is_unchanged():
    async def enrich(prop):
        return None

    result = _run(
        [(_prop("a"), None), (_prop("b"), None)],
        enrich_fn=enrich,
        budget=_Budget(),
        checkpoint=_Checkpoint(),
        requests_per_property=3,
    )
    assert result.processed == 2
    assert result.skipped_quarantined == 0


def test_dry_run_reports_quarantined_rows_it_would_skip():
    ledger = AttemptLedger(FakeRedis(), prefix="t", max_attempts=1)
    ledger.record_attempt("bad")

    async def enrich(prop):  # pragma: no cover - dry run must not call it
        raise AssertionError("dry run must not enrich")

    result = _run(
        [(_prop("bad"), None), (_prop("good"), None)],
        enrich_fn=enrich,
        budget=_Budget(),
        checkpoint=_Checkpoint(),
        requests_per_property=3,
        dry_run=True,
        ledger=ledger,
    )

    assert result.would_process == 1
    assert result.skipped_quarantined == 1
