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
        self.kv = {}
        self.hashes = {}

    def get(self, k):
        return self.kv.get(k)

    def set(self, k, v, ex=None, nx=False):
        # ``nx`` is what makes the v0.13-s1.3 lease single-instance.
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    def delete(self, k):
        self.kv.pop(k, None)
        self.hashes.pop(k, None)

    def expire(self, k, ttl):
        # Redis returns 1 when the key exists and 0 when it is already gone —
        # the non-atomic lease renew relies on that to notice a lapsed lease.
        return 1 if (k in self.kv or k in self.hashes) else 0

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
    cfg.backfill.lease_ttl_seconds = 900
    cfg.backfill.control_poll_seconds = 2.0
    cfg.backfill.quota_backoff_seconds = 900
    cfg.ai.gemini_api_key = "k"
    cfg.ai.backend = "ollama"
    cfg.ai.gemma_model = "gemma-4-31b-it"
    cfg.ai.gemini_model = "gemini-2.5-flash"
    cfg.ai.enrichment_routing = {
        "visual": "gemma",
        "sentiment": "gemma",
        "deal_verdict": "gemma",
        "valuation": "ollama",
        "embedding": "ollama",
    }
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


def _args(mod, **kw):
    """Namespace with the fields ``_run_continuous`` reads off ``args``."""
    base = dict(daily_budget=None, reset_margin=120.0, max_attempts=None, limit=None)
    base.update(kw)
    return SimpleNamespace(**base)


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
    # Chunked into control_poll_seconds steps now, so count > 1 — what matters
    # is that it waited at all between the two cycles.
    assert sleep_spy.call_count >= 1


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
    assert sleep_spy.call_count >= 1
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


# ---------------------------------------------------------------------------
# v0.13-s1.3 — operator stop is terminal and is not a stall
# ---------------------------------------------------------------------------


def test_continuous_exits_stopped_when_an_operator_asked_it_to_stop(monkeypatch, capsys):
    """A stop leaves work behind on purpose — reporting STALLED would lie."""
    mod = _load_module()
    _wire(mod, monkeypatch)
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=BackfillResult(processed=3, stopped=True))
    )
    monkeypatch.setattr(
        mod, "_census",
        MagicMock(return_value=_census(total_properties=100, enriched=50, candidates=50)),
    )
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_STOPPED
    assert "BACKFILL STOPPED" in capsys.readouterr().out
    sleep_spy.assert_not_called()


def test_budget_sleep_renews_the_lease_so_no_second_runner_slips_in(monkeypatch):
    """A ~24h sleep outlives the lease TTL unless it wakes to renew."""
    mod = _load_module()
    cfg = _cfg()
    cfg.backfill.lease_ttl_seconds = 30  # → renew every 10s
    cfg.backfill.control_poll_seconds = 5.0
    redis = _FakeRedis()
    lease = MagicMock()
    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))

    mod._sleep_for_reset(
        25.0, cfg=cfg, control=mod.BackfillControl(redis, prefix="t"), lease=lease
    )

    # Slept in control_poll_seconds steps, but the total wait is unchanged.
    assert sleeps == [5.0, 5.0, 5.0, 5.0, 5.0]
    # Renewed at t=0, 10, 20 — every lease_ttl/3, independent of the step size.
    assert lease.renew.call_count == 3
    assert redis.get("t:state") == "backing-off"


def test_budget_sleep_notices_a_stop_within_one_poll_interval(monkeypatch):
    """PEP 475: time.sleep resumes after a signal handler, so long chunks made
    Ctrl-C (which only *requests* a stop) unresponsive for up to lease_ttl/3."""
    mod = _load_module()
    cfg = _cfg()  # control_poll_seconds 2.0, lease_ttl 900 → old chunk was 300s
    redis = _FakeRedis()
    control = mod.BackfillControl(redis, prefix="t")
    sleeps = []

    def _sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:  # a SIGINT handler requests a stop mid-sleep
            control.request_stop()

    monkeypatch.setattr(mod.time, "sleep", _sleep)

    mod._sleep_for_reset(86400.0, cfg=cfg, control=control, lease=None)

    assert sleeps == [2.0, 2.0]  # noticed on the very next poll, not 300s later
    assert sum(sleeps) < 10


def test_budget_sleep_republishes_the_state_below_its_ttl(monkeypatch):
    """The state key TTLs out in 120s; a long back-off must keep it fresh."""
    mod = _load_module()
    cfg = _cfg()
    redis = _FakeRedis()
    control = mod.BackfillControl(redis, prefix="t")
    published = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        control, "publish_state", lambda state: published.append(state)
    )

    mod._sleep_for_reset(600.0, cfg=cfg, control=control, lease=None)

    # 600s of back-off at a refresh interval strictly below the 120s TTL.
    assert len(published) >= 600 / mod._STATE_REFRESH_SECONDS
    assert mod._STATE_REFRESH_SECONDS < 120


def test_budget_sleep_is_cut_short_by_a_stop_request(monkeypatch):
    mod = _load_module()
    cfg = _cfg()
    redis = _FakeRedis()
    control = mod.BackfillControl(redis, prefix="t")
    control.request_stop()
    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))

    mod._sleep_for_reset(3600.0, cfg=cfg, control=control, lease=None)

    assert sleeps == []


# ---------------------------------------------------------------------------
# Follow-up review pass 3 (v0.13-s1.3)
# ---------------------------------------------------------------------------


def _quota_pass():
    """A pass the provider refused outright: nothing enriched, quota flagged."""
    return BackfillResult(processed=0, budget_exhausted=True, quota_exhausted=True)


def test_repeated_quota_refusals_stop_hammering_a_refusing_account(monkeypatch):
    """A quota refusal sets ``budget_exhausted``, which puts the pass out of
    reach of the stall detector — so a provider refusing everything produced
    ~96 identical short-back-off passes a day, forever, each re-spending the
    client's retry budget. After a few consecutive zero-progress refusals the
    per-minute-throttle reading is ruled out and the runner waits out the RPD
    window instead."""
    from datetime import datetime, timezone

    mod = _load_module()
    cfg = _wire(mod, monkeypatch)
    cfg.backfill.quota_backoff_seconds = 900
    cycles = mod._MAX_QUOTA_BACKOFF_CYCLES + 1
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(side_effect=[_quota_pass()] * cycles + [BackfillResult(processed=1)]),
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(
            side_effect=[_census(enriched=1, candidates=5)] * cycles + [_census()]
        ),
    )
    redis = mod.get_redis()
    # A live 24h window with plenty of local headroom: the short cap is what
    # applies until the escalation kicks in.
    now = datetime.now(timezone.utc)
    redis.hashes["t:budget"] = {
        "count": "30",
        "start": now.isoformat(),
        "start_epoch": str(now.timestamp()),
    }
    waits = []
    monkeypatch.setattr(mod, "_sleep_for_reset", lambda w, **kw: waits.append(w))

    rc = mod._run_continuous(cfg, redis, _args(mod, continuous=True))

    assert rc == mod.EXIT_COMPLETE
    assert len(waits) == cycles
    # Short back-off while a per-minute throttle is still plausible...
    assert sum(1 for w in waits if w <= 900) == mod._MAX_QUOTA_BACKOFF_CYCLES - 1
    # ...then the whole window, instead of retrying every 15 minutes forever.
    assert waits[-1] > 3600


def test_a_completed_queue_retires_the_operator_requests_it_served(monkeypatch):
    """A pause/stop is moot once the queue is drained, and a request left set is
    reported as pending for the 7-day TTL with no runner alive."""
    mod = _load_module()
    cfg = _wire(mod, monkeypatch)
    redis = mod.get_redis()
    control = mod.BackfillControl(redis, prefix="t")
    control.request_stop()
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=BackfillResult(processed=2)))
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))

    rc = mod._run_continuous(cfg, redis, _args(mod, continuous=True), control=control)

    assert rc == mod.EXIT_COMPLETE
    assert control.should_stop() is False
    assert control.is_paused() is False


def test_a_lease_lost_on_the_final_pass_is_not_reported_as_completion(monkeypatch):
    """The successor may have drained the queue — this run was displaced, and
    exiting 0 would hide that (and let ``main`` stamp state over the successor)."""
    mod = _load_module()
    cfg = _wire(mod, monkeypatch)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(return_value=BackfillResult(processed=1, lease_lost=True)),
    )
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))

    rc = mod._run_continuous(cfg, mod.get_redis(), _args(mod, continuous=True))

    assert rc == mod.EXIT_LEASE_LOST


def test_a_completed_continuous_run_does_not_exit_backing_off(monkeypatch):
    """The last pass may have published ``backing-off`` on its way to draining
    the queue; a finished backfill must not read as backing off."""
    mod = _load_module()
    cfg = _wire(mod, monkeypatch)
    redis = mod.get_redis()
    monkeypatch.setattr(mod, "get_redis", lambda: redis)
    monkeypatch.setattr(
        mod, "_run_continuous", MagicMock(return_value=mod.EXIT_COMPLETE)
    )
    control = mod.BackfillControl(redis, prefix="t")
    control.publish_state(mod.BackfillState.BACKING_OFF)
    monkeypatch.setattr(mod, "_control_for", lambda c, r: control)
    del cfg

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    assert control.state() is mod.BackfillState.IDLE
