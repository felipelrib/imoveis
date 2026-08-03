"""Unit tests for the resumable RPD-aware backfill loop (BIN-248).

Pure logic against a dict-backed fake Redis and a fake ``enrich_fn`` — no DB,
network, or Celery. Covers budget stop/resume, idempotent skip vs ``force``,
dry-run accounting, per-row error isolation, and checkpoint advance.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.backfill_runner import (
    BackfillResult,
    Checkpoint,
    DailyBudget,
    estimate_eta_days,
    pace_seconds_for_budget,
    run_backfill,
)

pytestmark = pytest.mark.unit


class FakeRedis:
    """Minimal in-memory Redis supporting the ops the runner uses."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}

    # string ops
    def get(self, key):
        return self.kv.get(key)

    def set(self, key, val, ex=None):
        self.kv[key] = str(val)
        if ex:
            self.expires[key] = ex

    def incrby(self, key, n):
        self.kv[key] = str(int(self.kv.get(key, 0)) + int(n))
        return int(self.kv[key])

    def expire(self, key, ttl):
        self.expires[key] = ttl

    def delete(self, key):
        self.kv.pop(key, None)

    # hash ops
    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, mapping=None):
        h = self.hashes.setdefault(key, {})
        for k, v in (mapping or {}).items():
            h[k] = str(v)

    def hincrby(self, key, field, n):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + int(n))
        return int(h[field])


def _rows(n, *, enriched_ids=()):
    rows = []
    for i in range(n):
        pid = f"prop-{i}"
        ai = 0.8 if pid in enriched_ids else None
        rows.append((SimpleNamespace(id=pid), SimpleNamespace(ai_score=ai)))
    return rows


def _budget(redis, limit, *, day="2026-08-03"):
    fixed = datetime.fromisoformat(f"{day}T12:00:00+00:00")
    return DailyBudget(redis, prefix="t", daily_limit=limit, now_fn=lambda: fixed)


def _checkpoint(redis, *, day="2026-08-03"):
    fixed = datetime.fromisoformat(f"{day}T12:00:00+00:00")
    return Checkpoint(redis, prefix="t", now_fn=lambda: fixed)


async def _noop_sleep(_):
    return None


# ---------------------------------------------------------------------------
# DailyBudget
# ---------------------------------------------------------------------------


def test_budget_try_consume_stops_at_limit():
    r = FakeRedis()
    b = _budget(r, 10)
    assert b.try_consume(3) is True
    assert b.try_consume(3) is True
    assert b.consumed() == 6
    assert b.remaining() == 4
    # 6 + 6 = 12 > 10 → refused, nothing reserved.
    assert b.try_consume(6) is False
    assert b.consumed() == 6


def test_budget_resets_per_utc_day():
    r = FakeRedis()
    _budget(r, 10, day="2026-08-03").try_consume(9)
    # New day → fresh counter.
    assert _budget(r, 10, day="2026-08-04").consumed() == 0


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------


def test_checkpoint_advance_tracks_total_and_last_id():
    r = FakeRedis()
    cp = _checkpoint(r)
    cp.advance("prop-1")
    cp.advance("prop-2")
    loaded = cp.load()
    assert loaded["last_property_id"] == "prop-2"
    assert loaded["last_run_date"] == "2026-08-03"
    assert cp.processed_total() == 2


# ---------------------------------------------------------------------------
# run_backfill
# ---------------------------------------------------------------------------


def _run(rows, redis, *, limit=100, **kwargs):
    seen = []

    async def enrich_fn(prop):
        seen.append(prop.id)

    async def _go():
        return await run_backfill(
            rows,
            enrich_fn=kwargs.pop("enrich_fn", enrich_fn),
            budget=_budget(redis, limit),
            checkpoint=_checkpoint(redis),
            requests_per_property=3,
            sleep_fn=_noop_sleep,
            **kwargs,
        )

    result = asyncio.run(_go())
    return result, seen


def test_processes_all_within_budget():
    r = FakeRedis()
    result, seen = _run(_rows(4), r, limit=100)
    assert result.processed == 4
    assert seen == ["prop-0", "prop-1", "prop-2", "prop-3"]
    assert result.requests_consumed == 12
    assert _checkpoint(r).processed_total() == 4


def test_stops_at_budget_and_resumes_next_invocation():
    r = FakeRedis()
    # Budget 6 → 2 properties (3 req each), then exhausted.
    result1, seen1 = _run(_rows(5), r, limit=6)
    assert result1.processed == 2
    assert result1.budget_exhausted is True
    assert seen1 == ["prop-0", "prop-1"]

    # Same day, same budget → already exhausted, nothing more.
    result_same, seen_same = _run(_rows(5), r, limit=6)
    assert result_same.processed == 0
    assert result_same.budget_exhausted is True

    # Next day → budget resets, resume the rest.
    def _next_day_run(rows):
        seen = []

        async def enrich_fn(prop):
            seen.append(prop.id)

        async def _go():
            return await run_backfill(
                rows,
                enrich_fn=enrich_fn,
                budget=_budget(r, 6, day="2026-08-04"),
                checkpoint=_checkpoint(r, day="2026-08-04"),
                requests_per_property=3,
                sleep_fn=_noop_sleep,
            )

        return asyncio.run(_go()), seen

    result2, seen2 = _next_day_run(_rows(3))
    assert result2.processed == 2
    assert seen2 == ["prop-0", "prop-1"]


def test_skips_already_enriched_unless_forced():
    r = FakeRedis()
    rows = _rows(3, enriched_ids={"prop-1"})
    result, seen = _run(rows, r, limit=100)
    assert result.processed == 2
    assert result.skipped_already_enriched == 1
    assert "prop-1" not in seen

    # force re-runs the enriched one too.
    r2 = FakeRedis()
    rows2 = _rows(3, enriched_ids={"prop-1"})
    result2, seen2 = _run(rows2, r2, limit=100, force=True)
    assert result2.processed == 3
    assert "prop-1" in seen2


def test_dry_run_counts_without_consuming_budget():
    r = FakeRedis()
    result, seen = _run(_rows(5), r, limit=100, dry_run=True)
    assert result.would_process == 5
    assert result.processed == 0
    assert seen == []
    assert _budget(r, 100).consumed() == 0


def test_dry_run_capped_by_remaining_budget():
    r = FakeRedis()
    # Budget 9 / 3-per-prop → 3 would-process.
    result, _ = _run(_rows(10), r, limit=9, dry_run=True)
    assert result.would_process == 3
    assert result.budget_exhausted is True


def test_row_error_isolated_and_counted():
    r = FakeRedis()
    rows = _rows(3)

    async def enrich_fn(prop):
        if prop.id == "prop-1":
            raise RuntimeError("boom")

    result, _ = _run(rows, r, limit=100, enrich_fn=enrich_fn)
    assert result.processed == 2
    assert result.errors == 1
    assert result.error_ids == ["prop-1"]
    # Budget still consumed for the failed attempt (conservative).
    assert result.requests_consumed == 9
    # Checkpoint only advanced for successes.
    assert _checkpoint(r).processed_total() == 2


def test_pacing_sleep_invoked_between_properties():
    r = FakeRedis()
    calls = []

    async def sleep_fn(secs):
        calls.append(secs)

    async def enrich_fn(prop):
        return None

    async def _go():
        return await run_backfill(
            _rows(3),
            enrich_fn=enrich_fn,
            budget=_budget(r, 100),
            checkpoint=_checkpoint(r),
            requests_per_property=3,
            pace_seconds=6.0,
            sleep_fn=sleep_fn,
        )

    asyncio.run(_go())
    assert calls == [6.0, 6.0, 6.0]


def test_estimate_eta_days():
    assert estimate_eta_days(9200, 4600) == 2.0
    assert estimate_eta_days(0, 4600) == 0.0
    assert estimate_eta_days(100, 0) == float("inf")


def test_pace_seconds_for_budget():
    # 3 req/prop over 14,000/day → ~18.5s between properties (well under 30 RPM).
    assert pace_seconds_for_budget(3, 14000) == pytest.approx(18.51, abs=0.1)
    # Disabled when budget non-positive.
    assert pace_seconds_for_budget(3, 0) == 0.0


def test_result_to_dict_shape():
    d = BackfillResult(processed=3, requests_consumed=9).to_dict()
    assert d["processed"] == 3 and d["requests_consumed"] == 9
    assert "budget_exhausted" in d
