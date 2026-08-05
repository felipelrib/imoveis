"""CLI completion/exit-code behaviour for the Gemma backfill (v0.13-fu3).

``--continuous`` used to decide it was finished from ``total - enriched``, which
inactive un-enriched rows kept permanently positive: the "Backfill complete"
branch was dead and a finished run exited 0 through the "no progress this cycle"
message, which reads as *work remains*. These tests pin the replacement — a
census-driven terminal state, distinct exit codes, and a banner.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.backfill_runner import BackfillResult, QueueCensus

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dev" / "backfill_gemma.py"


class _FakeRedis:
    def __init__(self):
        self.hashes = {}

    def get(self, k):
        return None

    def set(self, k, v, ex=None):
        pass

    def delete(self, k):
        self.hashes.pop(k, None)

    def expire(self, k, ttl):
        pass

    def hgetall(self, k):
        return dict(self.hashes.get(k, {}))

    def hget(self, k, f):
        return self.hashes.get(k, {}).get(f)

    def hset(self, k, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(k, {})
        if mapping:
            h.update({a: str(b) for a, b in mapping.items()})
        if field is not None:
            h[field] = str(value)

    def hincrby(self, k, f, n=1):
        h = self.hashes.setdefault(k, {})
        h[f] = str(int(h.get(f, 0)) + n)
        return int(h[f])

    def hdel(self, k, *fs):
        for f in fs:
            self.hashes.setdefault(k, {}).pop(f, None)


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_gemma_completion", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg():
    cfg = MagicMock()
    cfg.backfill.redis_prefix = "t"
    cfg.backfill.daily_request_budget = 14000
    cfg.backfill.requests_per_property = 3
    cfg.backfill.rpm_limit = 30
    cfg.backfill.concurrency = 1
    cfg.backfill.tokens_per_property = 7000
    cfg.backfill.tpm_limit = 16000
    cfg.backfill.tpm_safety_margin = 0.9
    cfg.backfill.max_attempts = 3
    cfg.ai.gemini_api_key = "k"
    cfg.ai.max_images_per_property = 8
    cfg.scraping.photo_gate.enabled = True
    cfg.scraping.photo_gate.floor_min = 8
    cfg.scraping.photo_gate.coverage_ratio = 1.0
    cfg.scraping.photo_gate.min_photos = None
    return cfg


def _wire(mod, monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(mod, "get_config", lambda: cfg)
    monkeypatch.setattr(mod, "get_redis", lambda: _FakeRedis())
    monkeypatch.setattr(mod, "SessionLocal", MagicMock())
    monkeypatch.setattr(mod.time, "sleep", MagicMock())
    return cfg


def _census(**kw):
    base = dict(
        total_properties=100, enriched=100, candidates=0,
        blocked_no_photos=0, quarantined=0,
    )
    base.update(kw)
    return QueueCensus(**base)


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_continuous_exits_complete_when_the_candidate_queue_drains(monkeypatch, capsys):
    """The regression: 494 inactive rows must not stop this from reading complete."""
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=BackfillResult(processed=7)))
    # total-minus-enriched would be 494 here; candidates is what matters.
    monkeypatch.setattr(
        mod, "_census",
        MagicMock(return_value=_census(total_properties=26226, enriched=25732)),
    )

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE == 0
    out = capsys.readouterr().out
    assert "BACKFILL COMPLETE" in out
    assert "no progress this cycle" not in out


def test_continuous_exits_stalled_when_work_remains_but_nothing_processed(monkeypatch, capsys):
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=BackfillResult(processed=0)))
    monkeypatch.setattr(
        mod, "_census",
        MagicMock(return_value=_census(total_properties=100, enriched=40, candidates=60)),
    )

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_STALLED
    assert rc != 0  # a stall must not look like success
    out = capsys.readouterr().out
    assert "BACKFILL STALLED" in out
    assert "60" in out


def test_continuous_exits_complete_with_quarantine_when_rows_were_retired(monkeypatch, capsys):
    """Photo-blocked / quarantined leftovers are done — but flagged, not a stall."""
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=BackfillResult(processed=3)))
    monkeypatch.setattr(
        mod, "_census",
        MagicMock(
            return_value=_census(
                total_properties=100, enriched=80, candidates=20,
                blocked_no_photos=12, quarantined=8,
            )
        ),
    )

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE_WITH_QUARANTINE
    assert rc not in (mod.EXIT_COMPLETE, mod.EXIT_STALLED)
    out = capsys.readouterr().out
    assert "BACKFILL COMPLETE" in out
    assert "quarantined" in out.lower()


def test_continuous_does_not_sleep_a_day_when_the_last_cycle_finished_the_queue(
    monkeypatch, capsys
):
    """Budget exhausted *and* queue empty → finish now, not after a ~24h sleep."""
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(
        mod, "_run",
        MagicMock(return_value=BackfillResult(processed=9, budget_exhausted=True)),
    )
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    sleep_spy.assert_not_called()
    assert "BACKFILL COMPLETE" in capsys.readouterr().out


def test_continuous_still_sleeps_across_the_budget_reset_when_work_remains(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(
        mod, "_run",
        MagicMock(
            side_effect=[
                BackfillResult(processed=5, budget_exhausted=True),
                BackfillResult(processed=5),
            ]
        ),
    )
    monkeypatch.setattr(
        mod, "_census",
        MagicMock(side_effect=[_census(candidates=5, enriched=95), _census()]),
    )
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    sleep_spy.assert_called_once()


def test_continuous_sleeps_rather_than_stalling_when_the_window_was_already_spent(
    monkeypatch, capsys
):
    """processed=0 with the budget exhausted is a spent window, not a stall."""
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(
        mod, "_run",
        MagicMock(
            side_effect=[
                BackfillResult(processed=0, budget_exhausted=True),
                BackfillResult(processed=4),
            ]
        ),
    )
    monkeypatch.setattr(
        mod, "_census",
        MagicMock(side_effect=[_census(candidates=4, enriched=96), _census()]),
    )
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    sleep_spy.assert_called_once()
    assert "BACKFILL STALLED" not in capsys.readouterr().out


def test_reset_quarantine_clears_the_ledger_and_exits(monkeypatch, capsys):
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(mod, "_run", MagicMock(side_effect=AssertionError("must not run")))

    rc = mod.main(["--reset-quarantine"])

    assert rc == 0
    assert "released" in capsys.readouterr().out


def test_banner_reports_quarantined_rows_so_they_are_not_silently_dropped(
    monkeypatch, capsys
):
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=BackfillResult(processed=1)))
    monkeypatch.setattr(
        mod, "_census",
        MagicMock(
            return_value=_census(
                total_properties=100, enriched=99, candidates=1, quarantined=1
            )
        ),
    )
    monkeypatch.setattr(
        mod, "_quarantine_report", lambda ledger: {"prop-x": "429 rate limited"}
    )

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE_WITH_QUARANTINE
    out = capsys.readouterr().out
    assert "prop-x" in out
    assert "429 rate limited" in out


# ---------------------------------------------------------------------------
# --status honesty
# ---------------------------------------------------------------------------


def test_status_reports_the_enrichable_denominator_not_the_raw_total(monkeypatch, capsys):
    mod = _load_module()
    cfg = _wire(mod, monkeypatch)
    census = _census(total_properties=26226, enriched=7626, candidates=18106)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=census))
    monkeypatch.setattr(mod, "_observed_rate_per_day", lambda s: 2880.0)

    mod._print_status(cfg, MagicMock(), _FakeRedis())

    out = capsys.readouterr().out
    assert "7626 / 25732" in out          # enrichable denominator
    assert "18106" in out                 # true remaining, not 18600
    assert "18600" not in out
    assert "494" in out                   # non-enrichable surfaced, not hidden


def test_status_eta_uses_true_remaining(monkeypatch, capsys):
    mod = _load_module()
    cfg = _wire(mod, monkeypatch)
    # 100 remaining at 100/day → 1.0 day. The old maths (150 remaining) said 1.5.
    census = _census(total_properties=200, enriched=50, candidates=100)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=census))
    monkeypatch.setattr(mod, "_observed_rate_per_day", lambda s: 100.0)

    mod._print_status(cfg, MagicMock(), _FakeRedis())

    out = capsys.readouterr().out
    assert "1.0 (observed)" in out


# ---------------------------------------------------------------------------
# Census SQL wiring
# ---------------------------------------------------------------------------


class _CensusSession:
    """Returns the scalars/rows ``_census`` asks for, in order."""

    def __init__(self, total, enriched, candidates, blocked):
        self._results = [
            SimpleNamespace(scalar=lambda: total),
            SimpleNamespace(scalar=lambda: enriched),
            SimpleNamespace(one=lambda: (candidates, blocked)),
        ]

    def execute(self, *_a, **_k):
        return self._results.pop(0)


def test_census_builds_from_the_candidate_query(monkeypatch):
    mod = _load_module()
    cfg = _cfg()
    ledger = MagicMock()
    ledger.quarantined_ids.return_value = []
    census = mod._census(cfg, _CensusSession(26226, 7626, 18106, 0), ledger)

    assert census.candidates == 18106
    assert census.remaining == 18106
    assert census.enrichable == 25732
    assert census.non_enrichable == 494


def test_census_counts_quarantined_candidates(monkeypatch):
    mod = _load_module()
    cfg = _cfg()
    ledger = MagicMock()
    ledger.quarantined_ids.return_value = ["a", "b", "c"]
    monkeypatch.setattr(mod, "_count_quarantined_candidates", lambda s, ids, m: 2)

    census = mod._census(cfg, _CensusSession(100, 40, 60, 5), ledger)

    assert census.blocked_no_photos == 5
    assert census.quarantined == 2  # only the ones still in the queue
    assert census.remaining == 53
