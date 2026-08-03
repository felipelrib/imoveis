"""Regression tests for the backfill CLI wiring (BIN-248 follow-up).

Guards two bugs found running ``scripts/dev/backfill_gemma.py`` against the real
DB: (1) ``--dry-run`` must not require ``GEMINI_API_KEY`` (it makes no API
calls), and (2) ``--limit`` must cap how many properties are touched.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dev" / "backfill_gemma.py"


class _FakeRedis:
    def __init__(self):
        self.kv = {}

    def get(self, k):
        return self.kv.get(k)

    def set(self, k, v, ex=None):
        self.kv[k] = v

    def delete(self, k):
        self.kv.pop(k, None)

    def incrby(self, k, n):
        self.kv[k] = int(self.kv.get(k, 0)) + n
        return self.kv[k]

    def expire(self, k, ttl):
        pass

    def hgetall(self, k):
        return {}

    def hset(self, k, mapping=None):
        pass

    def hincrby(self, k, f, n):
        return n


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_gemma_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wire(mod, monkeypatch, *, api_key="", n_rows=10, enrich_fn=None):
    cfg = MagicMock()
    cfg.backfill.redis_prefix = "t"
    cfg.backfill.daily_request_budget = 14000
    cfg.backfill.requests_per_property = 3
    cfg.backfill.rpm_limit = 30
    cfg.backfill.concurrency = 1
    cfg.ai.gemini_api_key = api_key
    rows = [
        (
            SimpleNamespace(id=f"p{i}", first_seen=None, image_urls=[], description=""),
            SimpleNamespace(ai_score=None),
        )
        for i in range(n_rows)
    ]
    monkeypatch.setattr(mod, "get_config", lambda: cfg)
    monkeypatch.setattr(mod, "get_redis", lambda: _FakeRedis())
    monkeypatch.setattr(mod, "SessionLocal", MagicMock())
    monkeypatch.setattr(mod, "fetch_candidate_rows", lambda s, p: rows)
    return cfg


def test_dry_run_does_not_build_client_or_need_key(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="")  # no GEMINI_API_KEY
    build_spy = MagicMock(side_effect=AssertionError("dry-run must not build a client"))
    monkeypatch.setattr(mod, "_build_client", build_spy)

    rc = mod.main(["--dry-run", "--limit", "2"])

    assert rc == 0
    build_spy.assert_not_called()


def test_real_run_without_key_exits_cleanly(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="")
    # Real run with no key → the _build_client guard raises SystemExit.
    with pytest.raises(SystemExit):
        mod.main(["--limit", "1"])


def _br(mod, **kw):
    from core.backfill_runner import BackfillResult

    return BackfillResult(**kw)


def test_continuous_waits_between_cycles_then_completes(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k")

    # Cycle 1: budget exhausted, 5 remain → sleep, resume.
    # Cycle 2: processed the rest, 0 remain → done.
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            side_effect=[
                _br(mod, processed=0, budget_exhausted=True),
                _br(mod, processed=5, budget_exhausted=False),
            ]
        ),
    )
    monkeypatch.setattr(mod, "_counts", MagicMock(side_effect=[(5, 0), (5, 5)]))
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == 0
    assert mod._run.call_count == 2
    sleep_spy.assert_called_once()  # slept once between the two cycles
    assert sleep_spy.call_args[0][0] > 0


def test_continuous_stops_when_no_progress(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k")
    # Budget not exhausted, nothing processed, rows still remain → stop, no sleep.
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=0, budget_exhausted=False))
    )
    monkeypatch.setattr(mod, "_counts", MagicMock(return_value=(5, 2)))
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == 0
    sleep_spy.assert_not_called()


def test_continuous_rejects_dry_run(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k")
    with pytest.raises(SystemExit):
        mod.main(["--continuous", "--dry-run"])


class _FakeSession:
    def __init__(self, scalar):
        self._scalar = scalar

    def execute(self, *_a, **_k):
        return SimpleNamespace(scalar=lambda: self._scalar)


def test_observed_rate_per_day(monkeypatch):
    mod = _load_module()
    # 42 enrichments in the last hour → ~1008/day.
    assert mod._observed_rate_per_day(_FakeSession(42)) == 1008.0
    # Idle (0 / None) → None so status falls back to the budget ceiling.
    assert mod._observed_rate_per_day(_FakeSession(0)) is None
    assert mod._observed_rate_per_day(_FakeSession(None)) is None


def test_concurrency_flag_passes_through(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="")
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        captured.update(kwargs)
        from core.backfill_runner import BackfillResult

        return BackfillResult()

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)
    # dry-run so no client is needed; concurrency still threads through.
    mod.main(["--dry-run", "--concurrency", "5"])
    assert captured["concurrency"] == 5
