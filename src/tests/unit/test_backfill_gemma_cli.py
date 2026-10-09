"""Regression tests for the backfill CLI wiring (BIN-248 follow-up).

Guards two bugs found running ``scripts/dev/backfill_gemma.py`` against the real
DB: (1) ``--dry-run`` must not require ``GEMINI_API_KEY`` (it makes no API
calls), and (2) ``--limit`` must cap how many properties are touched.
"""

from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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

    def incrby(self, k, n):
        self.kv[k] = int(self.kv.get(k, 0)) + n
        return self.kv[k]

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
        h[f] = str(int(h.get(f, 0)) + int(n))
        return int(h[f])

    def hdel(self, k, *fs):
        for f in fs:
            self.hashes.setdefault(k, {}).pop(f, None)


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_gemma_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ALL_LOCAL_ROUTING = {
    "visual": "ollama",
    "sentiment": "ollama",
    "deal_verdict": "ollama",
    "valuation": "ollama",
    "embedding": "ollama",
}


def _wire(mod, monkeypatch, *, api_key="", n_rows=10, enrich_fn=None, routing=None,
          redis=None):
    cfg = MagicMock()
    cfg.backfill.redis_prefix = "t"
    cfg.backfill.daily_request_budget = 14000
    cfg.backfill.requests_per_property = 3
    cfg.backfill.rpm_limit = 30
    cfg.backfill.concurrency = 1
    cfg.backfill.tokens_per_property = 7000
    cfg.backfill.tpm_safety_margin = 0.9
    cfg.backfill.max_attempts = 3
    # A real int: ``int(MagicMock())`` is 1, so leaving this a mock would build
    # every run with a one-row circuit breaker instead of raising.
    cfg.backfill.max_consecutive_ai_failures = 3
    cfg.backfill.lease_ttl_seconds = 900
    cfg.backfill.control_poll_seconds = 2.0
    cfg.backfill.quota_backoff_seconds = 900
    cfg.backfill.migration_wait_seconds = 1800
    # Real numbers (v0.14-s1.13): ``int(MagicMock())`` is 1, which would end
    # every refused cycle with exit 10 and give the watchdog a 1-second limit.
    cfg.backfill.max_no_progress_cycles = 6
    cfg.backfill.main_thread_stall_seconds = 3600
    cfg.ai.gemini_api_key = api_key
    cfg.ai.backend = "ollama"
    cfg.ai.gemma_model = "gemma-4-31b-it"
    cfg.ai.gemini_model = "gemini-2.5-flash"
    # Real float: ``float(MagicMock())`` is ``1.0``, so leaving this a mock
    # would silently build every client with a 1-second DW-7 window instead of
    # raising — which is why the value is asserted, not just set. Deliberately
    # NOT the client's own 300.0 default, or a dropped kwarg would still assert.
    cfg.ai.gemini_transport_quota_window_seconds = 120.0
    # Same reason (v0.14-s1.14), and again not the client default (7200.0).
    # Longer than ``quota_backoff_seconds`` above, as the shipped pair is.
    cfg.ai.gemini_transport_quota_hold_seconds = 1800.0
    # Real number: the hold warning adds it to the back-off.
    cfg.ai.timeout = 120
    cfg.ai.enrichment_routing = dict(routing or _ALL_LOCAL_ROUTING)
    rows = [
        (
            SimpleNamespace(id=f"p{i}", first_seen=None, image_urls=[], description=""),
            SimpleNamespace(ai_score=None),
        )
        for i in range(n_rows)
    ]
    shared = redis if redis is not None else _FakeRedis()
    monkeypatch.setattr(mod, "get_config", lambda: cfg)
    monkeypatch.setattr(mod, "get_redis", lambda: shared)
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


def _census(**kw):
    """Queue census stub. Completion is measured on ``candidates`` (v0.13-fu3)."""
    from core.backfill_runner import QueueCensus

    base = dict(total_properties=5, enriched=5, candidates=0)
    base.update(kw)
    return QueueCensus(**base)


def test_continuous_waits_between_cycles_then_completes(monkeypatch):
    mod = _load_module()
    # Cloud routing: ``main`` now resolves the backend *before* taking the
    # lease, so an all-local map refuses the run outright.
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

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
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=0, candidates=5), _census()]),
    )
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    assert mod._run.call_count == 2
    # The wait is slept in control_poll_seconds steps (so a stop/SIGINT is
    # noticed promptly), not one long chunk — but it still adds up to the wait.
    assert sleep_spy.call_count > 1
    assert sum(call[0][0] for call in sleep_spy.call_args_list) == pytest.approx(120.0)


def test_continuous_stops_when_no_progress(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    # Budget not exhausted, nothing processed, rows still remain → stop, no sleep.
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=0, budget_exhausted=False))
    )
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=2, candidates=3))
    )
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    # A stall exits non-zero now: "0 remaining but no progress" read as success.
    assert rc == mod.EXIT_STALLED
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


# ---------------------------------------------------------------------------
# v0.13-s1.3 — single-instance lease, operator control, routed backend
# ---------------------------------------------------------------------------

_CLOUD_ROUTING = {**_ALL_LOCAL_ROUTING, "visual": "gemma", "sentiment": "gemma",
                  "deal_verdict": "gemma"}


def test_second_runner_is_refused_while_the_lease_is_held(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    run_spy = MagicMock(side_effect=AssertionError("a refused runner must not enrich"))
    monkeypatch.setattr(mod, "_run", run_spy)

    # A live run already holds the lease.
    from core.backfill_runner import BackfillLease

    holder = BackfillLease(redis, prefix="t", ttl_seconds=900, owner="host-a:123")
    assert holder.acquire() is True

    rc = mod.main(["--limit", "1"])

    assert rc == mod.EXIT_LEASE_HELD
    run_spy.assert_not_called()
    err = capsys.readouterr().err
    assert "host-a:123" in err          # names the holder
    assert "last seen" in err           # and when it was last seen
    assert holder.is_held_by_self()     # the refused start took nothing


def test_a_transport_quota_inference_is_logged_before_the_first_milestone(monkeypatch):
    """DW-7: the counter has to reach the operator in the run that inferred it.

    An inferred throttle stops the pass immediately, so gating the progress tick
    on the 25-row milestone alone means a pass that infers inside its first 25
    rows — where ``milestone`` is ``0`` and never exceeds the stored ``0`` —
    logs nothing at all. That leaves the operator with exactly the confusing
    combination the counter exists to explain: a pass backing off "on quota"
    with ``rate_limit_hits`` flat.
    """
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    class _StubClient:
        """Only the counters the progress hook reads, plus the run's session ctx."""

        rate_limit_hits = 0
        retry_count = 0
        transport_quota_inferences = 0

        @asynccontextmanager
        async def session_context(self):
            yield

    client = _StubClient()
    monkeypatch.setattr(mod, "_build_client", lambda cfg, scope=None, **_kw: client)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))

    captured = {}

    async def _fake_run_backfill(rows, **kw):
        captured["on_progress"] = kw["on_progress"]
        return _br(mod, processed=0)

    monkeypatch.setattr(mod, "run_backfill", _fake_run_backfill)
    mod.main(["--limit", "3"])

    on_progress = captured["on_progress"]
    info_spy = MagicMock()
    monkeypatch.setattr(mod.logger, "info", info_spy)

    def _progress_ticks():
        return [c for c in info_spy.call_args_list if c[0] and c[0][0] == "backfill_progress"]

    # Three rows in, nothing inferred: below the milestone, so still silent.
    on_progress(_br(mod, processed=3))
    assert _progress_ticks() == []

    # The pass infers a throttle and is about to stop. This must be reported.
    client.transport_quota_inferences = 1
    on_progress(_br(mod, processed=3))
    ticks = _progress_ticks()
    assert len(ticks) == 1
    assert ticks[0][1]["transport_quota_inferences"] == 1
    # ...and it must not then re-log the same inference on every later row.
    on_progress(_br(mod, processed=4))
    assert len(_progress_ticks()) == 1


def test_a_failed_lease_beat_does_not_swallow_the_inference_tick(monkeypatch):
    """The hook's one chance to report an inference must survive a Redis blip.

    ``heartbeat.beat()`` used to run inside the same ``try`` as the progress
    log, so a transient Redis failure on the very row that inferred a throttle
    took the counter down with it — and because an inferred throttle stops the
    pass immediately, there is no later row to re-emit it. The lease itself is
    renewed by ``run_backfill``'s background timer, so losing a bookkeeping
    beat here costs nothing; losing the tick costs the operator the explanation.
    """
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    beat_fails = {"now": False}

    class _FlakyHeartbeat:
        def __init__(self, *args, **kwargs):
            pass

        def beat(self):
            if beat_fails["now"]:
                raise RuntimeError("redis blip")

        def clear(self):
            pass

    class _StubClient:
        rate_limit_hits = 0
        retry_count = 0
        transport_quota_inferences = 0

        @asynccontextmanager
        async def session_context(self):
            yield

    client = _StubClient()
    monkeypatch.setattr(mod, "Heartbeat", _FlakyHeartbeat)
    monkeypatch.setattr(mod, "_build_client", lambda cfg, scope=None, **_kw: client)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))

    captured = {}

    async def _fake_run_backfill(rows, **kw):
        captured["on_progress"] = kw["on_progress"]
        return _br(mod, processed=0)

    monkeypatch.setattr(mod, "run_backfill", _fake_run_backfill)
    mod.main(["--limit", "3"])

    info_spy = MagicMock()
    monkeypatch.setattr(mod.logger, "info", info_spy)

    beat_fails["now"] = True
    client.transport_quota_inferences = 1
    captured["on_progress"](_br(mod, processed=3))

    ticks = [c for c in info_spy.call_args_list if c[0] and c[0][0] == "backfill_progress"]
    assert len(ticks) == 1
    assert ticks[0][1]["transport_quota_inferences"] == 1


def test_a_successful_run_releases_the_lease(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))

    assert mod.main(["--limit", "1"]) == 0
    assert redis.get("t:lease") is None  # next runner can start immediately


def test_dry_run_and_status_never_take_the_lease(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    monkeypatch.setattr(mod, "_observed_rate_per_day", lambda s: None)

    assert mod.main(["--dry-run", "--limit", "1"]) == 0
    assert redis.get("t:lease") is None
    assert mod.main(["--status"]) == 0
    assert redis.get("t:lease") is None


@pytest.mark.parametrize(
    "flag,key,expected",
    [("--pause", "t:control:pause", True), ("--stop", "t:control:stop", True)],
)
def test_control_flags_request_without_taking_the_lease(monkeypatch, flag, key, expected):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod, "_run", MagicMock(side_effect=AssertionError("control flags must not run"))
    )

    assert mod.main([flag]) == 0
    assert bool(redis.get(key)) is expected
    # Must work *while* a run holds the lease — so it never takes one itself.
    assert redis.get("t:lease") is None


def test_resume_clears_a_pause_request(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)

    mod.main(["--pause"])
    assert redis.get("t:control:pause")
    mod.main(["--resume"])
    assert redis.get("t:control:pause") is None


def test_resume_also_clears_a_pending_stop(monkeypatch, capsys):
    """--resume that leaves a stop in force ends the run it promised to continue."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)

    mod.main(["--stop"])
    mod.main(["--pause"])
    capsys.readouterr()

    assert mod.main(["--resume"]) == 0

    assert redis.get("t:control:stop") is None
    assert redis.get("t:control:pause") is None
    assert "cleared a pending stop" in capsys.readouterr().out


def test_a_discarded_pending_request_is_announced_not_swallowed(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))
    redis.set("t:control:pause", "1")

    assert mod.main(["--limit", "1"]) == 0

    out = capsys.readouterr().out
    assert "Discarding a pending pause request" in out


def test_status_lists_pending_control_requests(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    monkeypatch.setattr(mod, "_observed_rate_per_day", lambda s: None)
    mod.main(["--pause"])
    capsys.readouterr()

    mod._print_status(cfg, MagicMock(), redis)

    out = capsys.readouterr().out
    assert "pending requests" in out
    assert "pause" in out


def test_a_fresh_run_clears_a_stale_stop_request(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))
    redis.set("t:control:stop", "1")

    assert mod.main(["--limit", "1"]) == 0
    assert redis.get("t:control:stop") is None


def test_all_local_routing_refuses_and_names_the_config_keys(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_ALL_LOCAL_ROUTING, redis=redis)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--limit", "1"])

    msg = str(exc.value)
    assert "ai.enrichment_routing.visual" in msg
    assert "ai.enrichment_routing.sentiment" in msg
    assert "ai.enrichment_routing.deal_verdict" in msg
    assert "GEMINI_API_KEY" in msg
    assert redis.get("t:lease") is None  # the lease is handed back


def test_mixed_cloud_backends_are_refused(monkeypatch):
    mod = _load_module()
    _wire(
        mod,
        monkeypatch,
        api_key="k",
        routing={**_CLOUD_ROUTING, "sentiment": "gemini"},
    )

    with pytest.raises(SystemExit) as exc:
        mod.main(["--limit", "1"])

    msg = str(exc.value)
    assert "visual=gemma" in msg
    assert "sentiment=gemini" in msg


def test_client_is_built_from_the_routing_map_not_a_hardcoded_gemma(monkeypatch):
    mod = _load_module()
    cfg = _wire(
        mod,
        monkeypatch,
        api_key="k",
        routing={**_ALL_LOCAL_ROUTING, "deal_verdict": "gemini"},
    )
    from adapters.ai.client import GeminiClient
    from core.enrichment import EnrichmentTaskClass

    client = mod._build_client(cfg, {EnrichmentTaskClass.DEAL_VERDICT})

    # Routed to gemini → the gemini model, not cfg.ai.gemma_model.
    assert client.model == "gemini-2.5-flash"
    # DW-7: this is the only production construction site, and dropping the
    # kwarg here would leave the suite green while shipping a 1-second window
    # (``float(MagicMock())`` is ``1.0``, not an error). The expected value
    # differs from GeminiClient's own default so the assertion can tell the
    # difference between "threaded through" and "fell back to the default".
    assert client.transport_quota_window_seconds == 120.0
    assert (
        client.transport_quota_window_seconds
        != GeminiClient._DEFAULT_TRANSPORT_QUOTA_WINDOW_SECONDS
    )


def test_task_classes_flag_drives_the_stages(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    seen = {}
    monkeypatch.setattr(
        mod, "fetch_candidate_rows", lambda s, p: seen.setdefault("stages", p.stages) and []
    )

    async def fake_run_backfill(rows, **kwargs):
        from core.backfill_runner import BackfillResult

        return BackfillResult()

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)
    mod.main(["--dry-run", "--task-classes", "visual,sentiment,deal_verdict"])

    assert seen["stages"] == "all"


def test_visual_sentiment_scope_is_refused_by_the_cli(monkeypatch):
    """A partial scope strands every row it touches — refuse before spending.

    ``stages=visual+sentiment`` writes ``ai_score`` but no deal verdict, and
    candidate selection (``mode=missing``) keys *only* on ``ai_score``. Every
    row the pass touches therefore stops being a candidate and never receives a
    verdict from a later full pass; recovering costs a ``--force`` re-run of the
    entire visual+sentiment spend.
    """
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--dry-run", "--task-classes", "visual,sentiment"])

    msg = str(exc.value)
    assert "visual+sentiment backfill is not supported" in msg
    assert "mode=missing" in msg  # names *why* the rows are stranded
    assert "visual,sentiment,deal_verdict" in msg  # names the supported scope


def test_partial_scopes_stay_valid_in_the_core_vocabulary():
    """Both refusals are CLI policy, not a change to the shared helper."""
    from core.backfill_runner import stages_for_task_classes
    from core.enrichment import EnrichmentTaskClass

    assert (
        stages_for_task_classes(
            {EnrichmentTaskClass.VISUAL, EnrichmentTaskClass.SENTIMENT}
        )
        == "visual+sentiment"
    )


def test_deal_verdict_only_scope_is_refused_by_the_cli(monkeypatch):
    """``run_enrichment`` cannot do a verdict-only pass — refuse before spending.

    ``stages=verdict_only`` still makes it run visual+sentiment (overwriting
    ``ai_score`` with cloud-scored values) and writes the verdict only when
    ``stages == "all"``, so this scope burns quota and never delivers what it
    was asked for.
    """
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--dry-run", "--task-classes", "deal_verdict"])

    msg = str(exc.value)
    assert "deal_verdict-only" in msg
    assert "visual,sentiment,deal_verdict" in msg  # names the supported scope


def test_verdict_only_stays_valid_in_the_core_vocabulary(monkeypatch):
    """The refusal is a CLI policy, not a change to the shared helper."""
    from core.backfill_runner import stages_for_task_classes
    from core.enrichment import EnrichmentTaskClass

    assert (
        stages_for_task_classes({EnrichmentTaskClass.DEAL_VERDICT}) == "verdict_only"
    )


def test_unsupported_task_class_combination_is_rejected(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--dry-run", "--task-classes", "visual,deal_verdict"])

    assert "--task-classes" in str(exc.value)


def test_local_routing_refusal_does_not_advise_narrowing_the_scope(monkeypatch):
    """The old advice ("narrow --task-classes") led straight to a second error."""
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_ALL_LOCAL_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--limit", "1"])

    msg = str(exc.value)
    assert "narrow --task-classes to the cloud-routed classes" not in msg
    assert "visual,sentiment,deal_verdict" in msg


# ---------------------------------------------------------------------------
# --dry-run pre-flights the routing a real run would demand
# ---------------------------------------------------------------------------


def test_dry_run_warns_when_the_scope_would_refuse_a_real_run(monkeypatch, capsys):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="", routing=_ALL_LOCAL_ROUTING)

    rc = mod.main(["--dry-run", "--limit", "1"])

    assert rc == 0  # a dry run still plans; it must not hard-fail
    err = capsys.readouterr().err
    assert "would refuse to start a real run" in err
    assert "ai.enrichment_routing.visual" in err


def test_dry_run_warns_when_the_key_is_missing(monkeypatch, capsys):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="", routing=_CLOUD_ROUTING)

    assert mod.main(["--dry-run", "--limit", "1"]) == 0

    err = capsys.readouterr().err
    assert "would refuse to start a real run" in err
    assert "GEMINI_API_KEY" in err


def test_dry_run_names_the_backend_when_the_scope_is_cloud_routed(monkeypatch, capsys):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    assert mod.main(["--dry-run", "--limit", "1"]) == 0

    captured = capsys.readouterr()
    assert "gemma" in captured.out
    assert "would refuse" not in captured.err


# ---------------------------------------------------------------------------
# Bounded back-off: a provider 429 is not proof the daily budget is gone
# ---------------------------------------------------------------------------


def _open_budget_window(redis, *, consumed: int) -> None:
    """Stamp a live rolling window so ``seconds_until_reset()`` is ~24h."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    redis.hashes["t:budget"] = {
        "count": str(consumed),
        "start": now.isoformat(),
        "start_epoch": str(now.timestamp()),
    }


def _continuous_after_quota(mod, monkeypatch, redis, *, daily_budget=None):
    """One quota-refused cycle, then a completing one. Returns the slept seconds."""
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            side_effect=[
                _br(mod, processed=2, budget_exhausted=True, quota_exhausted=True),
                _br(mod, processed=3),
            ]
        ),
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=2, candidates=3), _census()]),
    )
    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))
    argv = ["--continuous"]
    if daily_budget is not None:
        argv += ["--daily-budget", str(daily_budget)]
    rc = mod.main(argv)
    return rc, sum(slept)


def test_provider_429_with_local_headroom_backs_off_briefly_not_a_day(
    monkeypatch, capsys
):
    """A per-minute throttle must not park the runner until the RPD window rolls."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.quota_backoff_seconds = 900
    _open_budget_window(redis, consumed=30)  # ~24h left, 13,970 requests spare

    rc, slept = _continuous_after_quota(mod, monkeypatch, redis)

    assert rc == mod.EXIT_COMPLETE
    assert slept == pytest.approx(900.0)  # capped, not ~86,520s
    out = capsys.readouterr().out
    assert "per-minute throttle" in out
    assert "still has" in out


def test_provider_429_with_the_local_budget_spent_still_sleeps_to_the_reset(
    monkeypatch, capsys
):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.quota_backoff_seconds = 900
    # --daily-budget 30 with 30 already consumed → no headroom for another row.
    _open_budget_window(redis, consumed=30)

    rc, slept = _continuous_after_quota(mod, monkeypatch, redis, daily_budget=30)

    assert rc == mod.EXIT_COMPLETE
    assert slept > 3600.0  # the full window, as before
    assert "local daily budget is spent" in capsys.readouterr().out


def test_a_window_the_real_requests_overshot_sleeps_instead_of_stalling(
    monkeypatch, capsys
):
    """A retry storm spends the day early; the loop must wait, not give up.

    This locks the *loop's* branching over a state only reconciliation can
    produce — a window sitting **above** ``daily_request_budget`` — not the
    reconciliation itself (``run_backfill`` is stubbed here as in every other
    continuous-branch test; the arithmetic is covered by
    ``test_backfill_request_reconciliation.py``). The pass that follows an
    overshoot processes nothing because its first reservation is refused, and
    that pair (``processed == 0`` with ``budget_exhausted``) has to route to the
    sleep-to-reset branch. The stall detector is the wrong answer: nothing is
    stuck, the day is simply spent, and exiting non-zero would take a supervised
    runner down for the night.
    """
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    # 14,010 sent against a 14,000 cap: the overshoot the reconciliation records
    # rather than hides.
    _open_budget_window(redis, consumed=14_010)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            side_effect=[
                _br(mod, processed=0, budget_exhausted=True),
                _br(mod, processed=3),
            ]
        ),
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=2, candidates=3), _census()]),
    )
    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    assert mod._run.call_count == 2  # it resumed after the window, not exited
    # ``remaining()`` floors at 0, so ``rpd_spent`` is True and the wait is the
    # whole window — not the short per-minute back-off.
    assert sum(slept) > 3600.0
    assert "Daily budget spent" in capsys.readouterr().out


def test_a_refusal_whose_drain_gave_headroom_back_runs_on_instead_of_sleeping(
    monkeypatch, capsys
):
    """Refunds can un-exhaust a window that a refusal already latched.

    Before v0.13-s3.3 a refused reservation was final for the window, so
    ``budget_exhausted`` and "no headroom left" were the same fact and nothing
    checked twice. Reconciliation breaks that: rows still draining settle down
    to what they really sent, and one that cost less than its 3-request forecast
    hands the difference back — so a pass can end refused and still fund more
    properties. Sleeping ~24h on that throws away most of a day's quota for a
    window that is not actually spent.
    """
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    # 13,000 of 14,000: the refusal happened, then the drain refunded — 1,000
    # requests of headroom are left, far more than one property's forecast.
    _open_budget_window(redis, consumed=13_000)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            side_effect=[
                _br(mod, processed=5, budget_exhausted=True),
                _br(mod, processed=3),
            ]
        ),
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=2, candidates=3), _census()]),
    )
    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    assert mod._run.call_count == 2  # it went straight into the next pass
    assert slept == []  # and never waited on a window it can still spend
    assert "Daily budget spent" not in capsys.readouterr().out


def test_a_refusal_with_headroom_but_no_progress_still_sleeps(monkeypatch, capsys):
    """The headroom shortcut must not become a spin.

    A pass that enriched nothing proves the headroom is not usable — every
    remaining row is failing, quarantined or skipped — so it falls through to
    the wait exactly as before. Only a pass that really moved rows is allowed to
    go straight round again.
    """
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=13_000)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            side_effect=[
                _br(mod, processed=0, budget_exhausted=True),
                _br(mod, processed=3),
            ]
        ),
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=2, candidates=3), _census()]),
    )
    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_COMPLETE
    assert sum(slept) > 3600.0  # the full window wait, not a spin
    assert "Daily budget spent" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Losing the lease mid-run is terminal
# ---------------------------------------------------------------------------


def test_a_run_that_lost_its_lease_exits_seven(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=2, lease_lost=True))
    )

    rc = mod.main(["--limit", "5"])

    assert rc == mod.EXIT_LEASE_LOST == 7
    assert "LEASE LOST" in capsys.readouterr().out


def test_continuous_that_lost_its_lease_exits_seven(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=2, lease_lost=True))
    )
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=2, candidates=8))
    )
    monkeypatch.setattr(mod.time, "sleep", MagicMock())

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_LEASE_LOST
    assert "two writers" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The run's checkpoint is lease-gated; the read-only ones are not (v0.13-s3.4)
# ---------------------------------------------------------------------------


def _checkpoint_spy(mod, monkeypatch):
    """Spy that still builds the real ``Checkpoint`` it is standing in for."""
    from core.backfill_runner import Checkpoint as _RealCheckpoint

    spy = MagicMock(side_effect=_RealCheckpoint)
    monkeypatch.setattr(mod, "Checkpoint", spy)
    return spy


def _stub_run_backfill(mod, monkeypatch):
    async def fake_run_backfill(rows, **kwargs):
        from core.backfill_runner import BackfillResult

        return BackfillResult()

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)


def test_the_runs_checkpoint_is_gated_on_the_lease_it_holds(monkeypatch):
    """DW-11: the run writes the *shared* hash, so it must prove ownership."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    _stub_run_backfill(mod, monkeypatch)
    spy = _checkpoint_spy(mod, monkeypatch)
    lease = mod._lease_for(cfg, redis)
    assert lease.acquire() is True

    mod._run(cfg, MagicMock(), redis, _run_args(limit=1), lease=lease)

    spy.assert_called_once()
    assert spy.call_args.kwargs["lease"] is lease


def test_a_dry_runs_checkpoint_carries_no_lease(monkeypatch):
    """A dry run takes no lease and writes nothing — gating it would refuse it."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _stub_run_backfill(mod, monkeypatch)
    spy = _checkpoint_spy(mod, monkeypatch)

    mod._run(cfg, MagicMock(), redis, _run_args(limit=1, dry_run=True), lease=None)

    assert spy.call_args.kwargs.get("lease") is None


def test_the_status_checkpoint_is_never_lease_gated(monkeypatch):
    """It only reads. Gating it on a lease it never holds would gate a read."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    monkeypatch.setattr(mod, "_observed_rate_per_day", lambda s: None)
    spy = _checkpoint_spy(mod, monkeypatch)
    # Someone else is mid-run and holds the lease.
    mod._lease_for(cfg, redis).acquire()

    mod._print_status(cfg, MagicMock(), redis)

    spy.assert_called_once()
    assert spy.call_args.kwargs.get("lease") is None


def test_the_lease_lost_banner_names_the_completions_it_could_not_record(
    monkeypatch, capsys
):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            return_value=_br(
                mod, processed=3, lease_lost=True, unrecorded_completions=3
            )
        ),
    )

    rc = mod.main(["--limit", "5"])

    out = capsys.readouterr().out
    assert rc == mod.EXIT_LEASE_LOST
    # "The checkpoint is intact" alone would leave an operator hunting for the
    # gap between "enriched 3" and a checkpoint that moved by none of them.
    assert "3 row(s) finished after the lease was lost" in out
    assert "NOT counted on the shared checkpoint" in out
    assert "The checkpoint is intact" in out  # still the successor's, and true


def test_a_lease_lost_with_nothing_draining_says_nothing_about_unrecorded_rows(
    monkeypatch, capsys
):
    """A pass that lost the lease before launching has no such rows to report."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=0, lease_lost=True))
    )

    assert mod.main(["--limit", "5"]) == mod.EXIT_LEASE_LOST

    assert "finished after the lease was lost" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Late stop / state on the way out
# ---------------------------------------------------------------------------


def test_a_stop_landing_after_the_last_row_is_still_reported(monkeypatch):
    """``result.stopped`` is only set when the loop breaks on the request."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)

    def _late_stop(*_a, **_k):
        redis.set("t:control:stop", "1")  # requested after the final launch
        return _br(mod, processed=3)

    monkeypatch.setattr(mod, "_run", MagicMock(side_effect=_late_stop))

    assert mod.main(["--limit", "3"]) == mod.EXIT_STOPPED


def test_a_quota_exhausted_pass_leaves_the_state_backing_off(monkeypatch):
    """The finally used to stamp ``idle`` over a deliberate ``backing-off``."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(return_value=_br(mod, processed=1, quota_exhausted=True)),
    )

    assert mod.main(["--limit", "3"]) == 0
    assert redis.get("t:state") == "backing-off"


def test_an_ordinary_pass_ends_idle(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))

    assert mod.main(["--limit", "3"]) == 0
    assert redis.get("t:state") == "idle"


def test_the_lease_is_released_when_start_up_raises(monkeypatch):
    """clear_requests/signal wiring lives inside the try that frees the lease."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod,
        "_install_stop_signals",
        MagicMock(side_effect=RuntimeError("signal wiring blew up")),
    )

    with pytest.raises(RuntimeError):
        mod.main(["--limit", "1"])

    assert redis.get("t:lease") is None  # not orphaned for the whole TTL


def test_control_is_threaded_into_run_backfill(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, n_rows=0)
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        captured.update(kwargs)
        from core.backfill_runner import BackfillResult

        return BackfillResult()

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)
    monkeypatch.setattr(mod, "_build_client", MagicMock(return_value=MagicMock()))

    mod.main(["--limit", "1"])

    assert captured["control"] is not None
    assert captured["pause_poll_seconds"] == 2.0


# ---------------------------------------------------------------------------
# Follow-up review pass (v0.13-s1.3): regressions for the review-driven fixes
# ---------------------------------------------------------------------------


def test_reset_quarantine_is_refused_while_a_run_holds_the_lease(monkeypatch):
    """The ledger is shared state a live run reads on every row.

    Clearing it under an active runner releases the rows that runner
    quarantined, which it then re-fetches and re-attempts — spending cloud quota
    on properties already proven unenrichable.
    """
    from core.backfill_runner import BackfillLease

    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=shared)
    other = BackfillLease(shared, prefix="t", ttl_seconds=900, owner="other-run")
    assert other.acquire()

    rc = mod.main(["--reset-quarantine"])

    assert rc == mod.EXIT_LEASE_HELD
    assert other.is_held_by_self()  # the ledger reset did not touch the lease


def test_reset_quarantine_still_works_with_no_run_active(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    ledger = MagicMock()
    ledger.quarantined_count.return_value = 4
    monkeypatch.setattr(mod, "_build_ledger", lambda *a, **k: ledger)

    rc = mod.main(["--reset-quarantine"])

    assert rc == 0
    ledger.reset_all.assert_called_once()


def test_continuous_refuses_a_budget_below_one_property(monkeypatch):
    """A cap under ``requests_per_property`` can never reserve anything.

    Every pass would end ``budget_exhausted`` with nothing processed, and the
    loop would sleep out a full 24h window forever without ever tripping the
    stall detector (which only fires when the budget is *not* exhausted).
    """
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--continuous", "--daily-budget", "2"])

    assert "requests_per_property" in str(exc.value)


def test_routing_is_refused_before_the_lease_is_taken(monkeypatch):
    """The refusal claimed to happen "before taking the lease" — now it does.

    Resolving routing inside ``_run`` meant a misconfigured start acquired the
    lease and ran ``clear_requests()``, silently discarding an operator's
    pending pause/stop, only to die on the refusal a moment later.
    """
    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", redis=shared)  # all-local routing
    control = mod._control_for(mod.get_config(), shared)
    control.request_stop()

    with pytest.raises(SystemExit):
        mod.main(["--limit", "1"])

    # The operator's request survived a start that was never going to run.
    assert control.should_stop() is True
    assert shared.get("t:lease") is None


def test_missing_key_is_diagnosed_as_a_missing_key(monkeypatch):
    """Cloud routing + no key degrades to local — do not blame the routing map.

    The all-local refusal told the operator to set keys they had already set.
    """
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--limit", "1"])

    msg = str(exc.value)
    assert "GEMINI_API_KEY is not set" in msg
    assert "Fix: export GEMINI_API_KEY." in msg


def test_exit_publishes_state_before_releasing_the_lease(monkeypatch):
    """Releasing first lets a new runner's ``running`` be stamped with ``idle``.

    Between ``release()`` and ``publish_state()`` a waiting runner can take the
    freed lease and publish ``running`` — which this exiting process then
    overwrote.
    """
    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=shared)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))
    order = []

    real_lease_for = mod._lease_for

    def tracking_lease_for(cfg, redis):
        lease = real_lease_for(cfg, redis)
        real_release = lease.release
        lease.release = lambda: (order.append("release"), real_release())[1]
        return lease

    monkeypatch.setattr(mod, "_lease_for", tracking_lease_for)

    real_control_for = mod._control_for

    def tracking_control_for(cfg, redis):
        control = real_control_for(cfg, redis)
        real_publish = control.publish_state
        control.publish_state = lambda s: (order.append(f"publish:{s.value}"),
                                           real_publish(s))[1]
        return control

    monkeypatch.setattr(mod, "_control_for", tracking_control_for)

    mod.main(["--limit", "1"])

    assert order[-2:] == ["publish:idle", "release"]


def test_a_lost_lease_publishes_no_state_on_the_way_out(monkeypatch):
    """The state key now describes the successor — do not stamp it.

    ``run_backfill`` deliberately publishes nothing on lease loss; ``main``'s
    ``finally`` used to undo that immediately.
    """
    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=shared)
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=1, lease_lost=True))
    )
    published = []

    real_control_for = mod._control_for

    def tracking_control_for(cfg, redis):
        control = real_control_for(cfg, redis)
        real_publish = control.publish_state
        control.publish_state = lambda s: (published.append(s), real_publish(s))[1]
        return control

    monkeypatch.setattr(mod, "_control_for", tracking_control_for)

    rc = mod.main(["--limit", "1"])

    assert rc == mod.EXIT_LEASE_LOST
    assert published == []


def test_a_served_stop_request_is_retired(monkeypatch):
    """A honored stop must not be re-reported as pending for the request TTL."""
    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=shared)
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=1, stopped=True))
    )
    control = mod._control_for(mod.get_config(), shared)

    rc = mod.main(["--limit", "1"])

    assert rc == mod.EXIT_STOPPED
    assert control.should_stop() is False


def test_sleep_for_reset_reports_a_pause_instead_of_backing_off(monkeypatch):
    """A pause during the budget wait was invisible for the whole window."""
    from core.backfill_runner import BackfillState

    mod = _load_module()
    cfg = MagicMock()
    cfg.backfill.control_poll_seconds = 1.0
    cfg.backfill.lease_ttl_seconds = 900
    control = MagicMock()
    control.should_stop.return_value = False
    control.is_paused.return_value = True
    monkeypatch.setattr(mod.time, "sleep", MagicMock())

    mod._sleep_for_reset(3.0, cfg=cfg, control=control)

    states = [c[0][0] for c in control.publish_state.call_args_list]
    assert BackfillState.PAUSED in states
    assert BackfillState.BACKING_OFF not in states


def test_sleep_for_reset_stops_waiting_once_the_lease_is_lost(monkeypatch):
    """Sleeping out hours on a lease someone else owns helps nobody."""
    mod = _load_module()
    cfg = MagicMock()
    cfg.backfill.control_poll_seconds = 1.0
    cfg.backfill.lease_ttl_seconds = 900
    lease = MagicMock()
    lease.renew.return_value = False
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    mod._sleep_for_reset(
        3600.0, cfg=cfg, control=None, liveness=mod.LivenessTicker(lease=lease)
    )

    sleep_spy.assert_not_called()  # bailed on the very first renew


# ---------------------------------------------------------------------------
# Follow-up review pass 3 (v0.13-s1.3)
# ---------------------------------------------------------------------------


def test_a_served_stop_is_retired_before_the_lease_is_released(monkeypatch):
    """Reading the stop after the release can discard a *successor's* request.

    Between ``lease.release()`` and the stop read, a waiting runner takes the
    freed lease; an operator stopping *that* run had their request reported as
    served by this one — and then cleared, so the live run never stopped.
    """
    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=shared)
    monkeypatch.setattr(
        mod, "_run", MagicMock(return_value=_br(mod, processed=1, stopped=True))
    )
    order = []

    real_lease_for = mod._lease_for

    def tracking_lease_for(cfg, redis):
        lease = real_lease_for(cfg, redis)
        real_release = lease.release
        lease.release = lambda: (order.append("release"), real_release())[1]
        return lease

    monkeypatch.setattr(mod, "_lease_for", tracking_lease_for)

    real_control_for = mod._control_for
    control_box = {}

    def tracking_control_for(cfg, redis):
        control = real_control_for(cfg, redis)
        real_clear = control.clear_stop
        control.clear_stop = lambda: (order.append("clear_stop"), real_clear())[1]
        control_box["control"] = control
        return control

    monkeypatch.setattr(mod, "_control_for", tracking_control_for)

    rc = mod.main(["--limit", "1"])

    assert rc == mod.EXIT_STOPPED
    assert order.index("clear_stop") < order.index("release")
    assert control_box["control"].should_stop() is False


def test_a_final_state_publish_failure_still_releases_the_lease(monkeypatch):
    """An unreleased lease locks the next run out for the whole TTL."""
    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=shared)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))

    real_control_for = mod._control_for

    def exploding_control_for(cfg, redis):
        control = real_control_for(cfg, redis)
        control.publish_state = MagicMock(side_effect=ConnectionError("redis down"))
        return control

    monkeypatch.setattr(mod, "_control_for", exploding_control_for)

    mod.main(["--limit", "1"])

    assert shared.get("t:lease") is None  # released despite the publish failure


def test_reset_quarantine_holds_the_lease_while_it_rewrites_the_ledger(monkeypatch):
    """Reading ``holder()`` is check-then-act: a run starting in the gap still
    gets its ledger wiped underneath it. The command takes the lease instead."""
    mod = _load_module()
    shared = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=shared)
    held = []

    class _Ledger:
        def quarantined_count(self):
            return 2

        def reset_all(self):
            held.append(shared.get("t:lease"))

    monkeypatch.setattr(mod, "_build_ledger", lambda *a, **k: _Ledger())

    rc = mod.main(["--reset-quarantine"])

    assert rc == 0
    assert held and held[0] is not None  # the lease was held during the rewrite
    assert shared.get("t:lease") is None  # and handed back afterwards


@pytest.mark.parametrize(
    "argv",
    [
        ["--stop", "--status"],
        ["--reset-quarantine", "--pause"],
        ["--status", "--reset-quarantine"],
    ],
)
def test_mutually_exclusive_commands_are_rejected_not_silently_dropped(
    monkeypatch, argv
):
    """Combining them ran the first and silently ignored the rest."""
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(argv)

    assert exc.value.code == 2


def test_a_negative_reset_margin_is_rejected(monkeypatch):
    """It can drive the post-budget wait to zero — a tight loop of empty passes."""
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--continuous", "--reset-margin", "-60"])

    assert exc.value.code == 2


def test_a_whitespace_only_key_is_diagnosed_as_a_missing_key(monkeypatch):
    """``cloud_available`` strips before testing, so this key routes local.

    Testing the raw value blamed the routing map for a blank key — and would
    have sent the blank bearer token to the provider.
    """
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="   ", routing=_CLOUD_ROUTING)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--limit", "1"])

    assert "GEMINI_API_KEY is not set" in str(exc.value)


def test_the_task_classes_help_matches_what_the_cli_accepts(capsys):
    """The help (and the module docstring) advertised a scope ``_stages_for``
    refuses outright: an operator following ``--help`` got a hard exit."""
    mod = _load_module()

    with pytest.raises(SystemExit):
        mod._stages_for(mod.parse_task_classes("visual,sentiment"))

    with pytest.raises(SystemExit):
        mod.main(["--help"])
    help_text = capsys.readouterr().out

    assert "'visual,sentiment,deal_verdict'" in help_text
    assert "or 'visual,sentiment'" not in help_text
    assert "or\n``visual,sentiment``" not in mod.__doc__
    assert "Only two scopes are supported" not in mod.__doc__


# ---------------------------------------------------------------------------
# v0.13-fu6 — mutual exclusion with migrate-primary.sh (DW-3 / DW-4)
# ---------------------------------------------------------------------------


class _RecordingRedis(_FakeRedis):
    """Fake that remembers call order — the whole fix is an ordering argument."""

    def __init__(self):
        super().__init__()
        self.ops: list[tuple[str, str]] = []

    def get(self, k):
        self.ops.append(("get", k))
        return super().get(k)

    def set(self, k, v, ex=None, nx=False):
        self.ops.append(("set", k))
        return super().set(k, v, ex=ex, nx=nx)


class _LateMigrationRedis(_RecordingRedis):
    """The migration lands *between* ``_run``'s early probe and the pass gate.

    ``_run`` now short-circuits a blocked pass before it queries the DB (its
    SELECTs would otherwise block on the upgrade's ACCESS EXCLUSIVE lock), so
    this race — key free at the probe, held at pass entry — is what the
    authoritative beat-then-check inside ``_go`` exists for, and the only way to
    observe that ordering.
    """

    def __init__(self):
        super().__init__()
        self._probed = False

    def get(self, k):
        value = super().get(k)
        if k == "t:migrating" and not self._probed:
            self._probed = True
            return None
        return value


def _run_args(**kw):
    """Namespace with the fields ``_run`` reads off ``args``."""
    base = dict(
        limit=None, dry_run=False, force=False, daily_budget=None, concurrency=None,
        tokens_per_property=None, tpm_limit=None, min_interval=None,
        max_attempts=None, task_classes=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_migration_in_progress_refuses_the_run_and_takes_no_lease(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    run_spy = MagicMock(side_effect=AssertionError("a blocked runner must not enrich"))
    monkeypatch.setattr(mod, "_run", run_spy)
    redis.set("t:migrating", "migrate-primary:host-a:9:1754500000")

    rc = mod.main(["--limit", "1"])

    assert rc == mod.EXIT_MIGRATION_ACTIVE == 8
    run_spy.assert_not_called()
    # Refused before taking anything: the lease is free and the operator's
    # pending pause/stop requests were never cleared.
    assert redis.get("t:lease") is None
    assert "migrate-primary:host-a:9" in capsys.readouterr().err


def test_pass_entry_beats_the_heartbeat_before_reading_the_migrating_key(
    monkeypatch, capsys
):
    """DW-4: the wake-up gate must beat ``:active`` *first*, then read the key.

    ``_go``'s ``finally`` clears the heartbeat, so a runner sleeping out an RPD
    window reads as idle to ``migrate-primary.sh`` and used to come back writing
    mid-migration. Beating before the read is what makes the two set-then-check
    sequences mutually exclusive — reversing them reopens the hole.
    """
    mod = _load_module()
    redis = _LateMigrationRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    monkeypatch.setattr(
        mod,
        "run_backfill",
        MagicMock(side_effect=AssertionError("a blocked pass must launch nothing")),
    )
    redis.set("t:migrating", "migrate-primary:host-b:7:1754500000")
    redis.ops.clear()

    result = mod._run(cfg, MagicMock(), redis, _run_args(limit=1))

    assert result.migration_blocked is True
    assert result.processed == 0
    beat = redis.ops.index(("set", "t:active"))
    gate_reads = [i for i, op in enumerate(redis.ops) if op == ("get", "t:migrating")]
    # The first read is the pre-DB optimization (it may run before the beat — it
    # can only refuse early, never wave a pass through). The one that decides
    # comes *after* the beat: that is what makes the two halves exclusive.
    assert gate_reads[-1] > beat
    assert redis.get("t:active") is None  # the pass still cleared its heartbeat
    assert "migrate-primary:host-b:7" in capsys.readouterr().err


def test_a_blocked_pass_never_touches_the_primary_db(monkeypatch, capsys):
    """The gate is read before the first SELECT, not after it.

    ``fetch_candidate_rows`` (and the census right behind it) can block on the
    ACCESS EXCLUSIVE lock an ``ALTER TABLE`` holds — for the whole upgrade, long
    enough for this runner's lease to lapse — on behalf of a pass that is going
    to be refused anyway.
    """
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod,
        "fetch_candidate_rows",
        MagicMock(side_effect=AssertionError("a blocked pass must not query the DB")),
    )
    monkeypatch.setattr(
        mod,
        "_build_client",
        MagicMock(side_effect=AssertionError("a blocked pass needs no client")),
    )
    redis.set("t:migrating", "migrate-primary:host-e:5:1754500000")

    result = mod._run(cfg, MagicMock(), redis, _run_args(limit=1))

    assert result.migration_blocked is True
    assert result.processed == 0
    assert "migrate-primary:host-e:5" in capsys.readouterr().err


def test_the_migration_predicate_is_wired_into_run_backfill(monkeypatch):
    """Re-read per launch, not once per pass: a migration can start mid-pass."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        captured.update(kwargs)
        from core.backfill_runner import BackfillResult

        return BackfillResult()

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)

    mod._run(cfg, MagicMock(), redis, _run_args(limit=1))

    assert captured["is_migrating"]() is False
    redis.set("t:migrating", "migrate-primary:host-c:1:1754500000")
    assert captured["is_migrating"]() is True


def test_a_dry_run_is_not_gated_by_a_migration(monkeypatch):
    """It writes nothing, so it takes no lease, no control keys and no gate."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    redis.set("t:migrating", "migrate-primary:host-d:2:1754500000")
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        captured.update(kwargs)
        from core.backfill_runner import BackfillResult

        return BackfillResult()

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)

    assert mod.main(["--dry-run", "--limit", "1"]) == 0
    assert captured["is_migrating"] is None


# ---------------------------------------------------------------------------
# Follow-up review pass 4 (v0.13-s1.3, DW-1)
# ---------------------------------------------------------------------------


def test_sleep_for_reset_reports_why_it_returned(monkeypatch):
    """A bare return could not tell "window elapsed" from "we lost the lease"."""
    mod = _load_module()
    cfg = MagicMock()
    cfg.backfill.control_poll_seconds = 1.0
    cfg.backfill.lease_ttl_seconds = 900
    monkeypatch.setattr(mod.time, "sleep", MagicMock())

    lost = MagicMock()
    lost.renew.return_value = False
    stopping = MagicMock()
    stopping.should_stop.return_value = True

    assert mod._sleep_for_reset(0.0, cfg=cfg) == "elapsed"
    assert (
        mod._sleep_for_reset(3600.0, cfg=cfg, liveness=mod.LivenessTicker(lease=lost))
        == "lease_lost"
    )
    assert mod._sleep_for_reset(3600.0, cfg=cfg, control=stopping) == "stopped"


def test_a_lease_lost_during_the_budget_sleep_exits_lease_lost(monkeypatch):
    """Resuming into a fresh pass hid the displacement as a clean completion.

    The successor drains the queue while this run sleeps out its window, so the
    pass that follows fetches nothing, reports ``complete`` and exits 0 — for a
    backfill somebody else finished.
    """
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    lease = MagicMock()
    lease.acquire.return_value = True
    lease.renew.return_value = False  # a successor holds it now
    monkeypatch.setattr(mod, "_lease_for", lambda cfg, r: lease)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            side_effect=[
                _br(mod, processed=1, budget_exhausted=True),
                AssertionError("a displaced runner must not start another pass"),
            ]
        ),
    )
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=1, candidates=5))
    )
    monkeypatch.setattr(mod.time, "sleep", MagicMock())

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_LEASE_LOST
    assert mod._run.call_count == 1


def test_a_state_publish_blip_during_the_budget_wait_never_kills_the_run(monkeypatch):
    """The state key is decoration; the checkpoint and the provider are fine."""
    mod = _load_module()
    cfg = MagicMock()
    cfg.backfill.control_poll_seconds = 1.0
    cfg.backfill.lease_ttl_seconds = 900
    control = MagicMock()
    control.should_stop.return_value = False
    control.is_paused.return_value = False
    control.publish_state.side_effect = ConnectionError("redis went away")
    monkeypatch.setattr(mod.time, "sleep", MagicMock())

    assert mod._sleep_for_reset(3.0, cfg=cfg, control=control) == "elapsed"
    assert control.publish_state.called


def test_a_failing_lease_release_does_not_replace_the_exit_code(monkeypatch):
    """A completed run must not read as an exit-1 crash to a supervisor."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    lease = MagicMock()
    lease.acquire.return_value = True
    lease.release.side_effect = ConnectionError("redis went away")
    monkeypatch.setattr(mod, "_lease_for", lambda cfg, r: lease)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=3)))

    assert mod.main(["--limit", "3"]) == 0
    lease.release.assert_called_once()


# ---------------------------------------------------------------------------
# --serve supervisor (v0.13-s1.5)
#
# The admin API can only *request* a start (no cloud key in the container, no
# runner spawned from a request thread), so this loop is the seam that makes
# the start endpoint real. Without it the dashboard's button queues into the
# void.
# ---------------------------------------------------------------------------


class _RecordingSetRedis(_FakeRedis):
    """Fake that remembers which keys were written, so a beat is observable."""

    def __init__(self):
        super().__init__()
        self.sets = []

    def set(self, k, v, ex=None, nx=False):
        written = super().set(k, v, ex=ex, nx=nx)
        if written:
            self.sets.append(k)
        return written


def _serve_args(**overrides):
    args = SimpleNamespace(
        reset_margin=120.0,
        daily_budget=None,
        concurrency=None,
        tokens_per_property=None,
        tpm_limit=None,
        min_interval=None,
        max_attempts=None,
        task_classes=None,
        force=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_serve_consumes_a_start_request_and_launches_a_continuous_run(monkeypatch, capsys):
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._control_for(cfg, redis).request_start("admin-api")
    launched = MagicMock(return_value=0)
    monkeypatch.setattr(mod, "main", launched)

    rc = mod._serve(
        cfg, redis, _serve_args(task_classes="visual"), sleep_fn=MagicMock(), max_cycles=1
    )

    assert rc == 0
    argv = launched.call_args[0][0]
    assert "--continuous" in argv
    # Scope carries over; the pacing knobs the status endpoint reports are
    # refused at parse time instead, so they can never diverge from config.
    assert argv[argv.index("--task-classes") + 1] == "visual"
    # Consumed exactly once — a second cycle must not re-launch the same request.
    assert mod._control_for(cfg, redis).start_request() is None
    # It beat its own supervisor key, never the runner's `:active` heartbeat
    # (which is what blocks migrate-primary.sh).
    assert "t:supervisor:active" in redis.sets
    assert "t:active" not in redis.sets
    # …and cleared it on the way out, so nothing claims to be listening.
    assert redis.get("t:supervisor:active") is None
    assert "launching a continuous run" in capsys.readouterr().out


def test_serve_idle_beats_and_waits_without_taking_a_lease(monkeypatch):
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod, "main", MagicMock(side_effect=AssertionError("nothing was requested"))
    )
    slept = []

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=slept.append, max_cycles=2)

    assert rc == 0
    assert slept == [cfg.backfill.control_poll_seconds] * 2
    assert "t:supervisor:active" in redis.sets
    assert redis.get("t:lease") is None


def test_serve_keeps_serving_after_a_run_is_refused(monkeypatch, capsys):
    """A second supervisor loses the lease race — that ends the run, not the loop."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._control_for(cfg, redis).request_start("admin-api")
    monkeypatch.setattr(mod, "main", MagicMock(return_value=mod.EXIT_LEASE_HELD))
    slept = []

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=slept.append, max_cycles=2)

    assert rc == 0
    assert slept == [cfg.backfill.control_poll_seconds]  # second cycle idled
    assert f"exit {mod.EXIT_LEASE_HELD}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["--serve", "--status"],
        ["--serve", "--pause"],
        ["--serve", "--reset-quarantine"],
        ["--serve", "--dry-run"],
        ["--serve", "--limit", "5"],
        # ``_continuous_argv`` carries --force into *every* API-requested run,
        # so each dashboard Start would re-enrich already-scored rows and burn
        # the whole daily cloud budget on work already paid for.
        ["--serve", "--force"],
        # Reads as "run now", which is exactly what --serve does not do until
        # the API asks; accepting it silently dropped that intent.
        ["--serve", "--continuous"],
        # The status endpoint reports the configured budget and pacing and
        # cannot see this argv, so an API-requested run carrying an override
        # would pace to figures the dashboard never shows.
        ["--serve", "--daily-budget", "5000"],
        ["--serve", "--concurrency", "4"],
        ["--serve", "--tpm-limit", "8000"],
        ["--serve", "--min-interval", "2"],
    ],
)
def test_serve_refuses_the_flag_combinations_it_cannot_honor(monkeypatch, argv):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    monkeypatch.setattr(
        mod, "_serve", MagicMock(side_effect=AssertionError("must not serve"))
    )

    with pytest.raises(SystemExit) as exc_info:
        mod.main(argv)

    assert exc_info.value.code == 2


def test_the_cli_pending_request_words_come_from_the_core_helper():
    """One derivation of the vocabulary: the CLI printing one set of words while
    the wire reports another is exactly the drift a shared helper prevents."""
    from core.backfill_runner import pending_control_requests

    mod = _load_module()
    redis = _FakeRedis()
    control = mod.BackfillControl(redis, prefix="t")
    control.request_pause()
    control.request_stop()

    # Behavioural, not a source grep: what must not drift is the words, and a
    # reworded delegation is fine as long as both sides still say the same two.
    assert mod._pending_requests(control) == pending_control_requests(control)
    assert mod._pending_requests(control) == ["pause", "stop"]
    assert mod.pending_control_requests is pending_control_requests


def test_serve_survives_a_run_that_exits_and_keeps_serving(monkeypatch, capsys):
    """``main()`` raises SystemExit for a refusal. The supervisor has already
    consumed the (destructive) start request by then, so dying here would leave
    the request gone, no run, and nothing recording the loss."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._control_for(cfg, redis).request_start("admin-api")
    monkeypatch.setattr(mod, "main", MagicMock(side_effect=SystemExit(2)))
    slept = []

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=slept.append, max_cycles=3)

    assert rc == 0
    # Cycles 2 and 3 kept polling — the loop outlived the failed run.
    assert slept == [cfg.backfill.control_poll_seconds] * 2
    out = capsys.readouterr()
    assert "exit 2" in out.out + out.err


def test_serve_survives_a_run_that_raises_and_keeps_serving(monkeypatch, capsys):
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._control_for(cfg, redis).request_start("admin-api")
    monkeypatch.setattr(mod, "main", MagicMock(side_effect=RuntimeError("boom")))
    slept = []

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=slept.append, max_cycles=3)

    assert rc == 0
    assert slept == [cfg.backfill.control_poll_seconds] * 2
    out = capsys.readouterr()
    assert "boom" in out.out + out.err
    # And the heartbeat is still cleared on the way out.
    assert redis.get("t:supervisor:active") is None


def test_serve_leaves_a_start_request_pending_while_the_lease_is_held(
    monkeypatch, capsys
):
    """``consume_start`` is destructive: consuming while another run holds the
    lease burns the request on a run that is refused a moment later."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    real_control = mod._control_for(cfg, redis)
    real_control.request_start("admin-api")
    spy = MagicMock(wraps=real_control)
    monkeypatch.setattr(mod, "_control_for", lambda *a, **k: spy)
    assert mod.BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    monkeypatch.setattr(
        mod, "main", MagicMock(side_effect=AssertionError("must not launch a run"))
    )
    slept = []

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=slept.append, max_cycles=3)

    assert rc == 0
    spy.consume_start.assert_not_called()
    assert real_control.start_request() is not None
    assert slept == [cfg.backfill.control_poll_seconds] * 3
    # Said once, not once per poll — this loop wakes every couple of seconds and
    # a live run holds the lease for days.
    assert capsys.readouterr().out.count("holds the run lease") == 1


def test_serve_refuses_a_scope_or_backend_it_cannot_run_before_it_looks_ready(
    monkeypatch,
):
    """A supervisor that beats a "ready" heartbeat while structurally unable to
    run tells the dashboard something is listening and then refuses every
    request it accepts."""
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="", routing=_CLOUD_ROUTING)  # no cloud key
    monkeypatch.setattr(
        mod, "_serve", MagicMock(side_effect=AssertionError("must not serve"))
    )

    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--serve"])

    assert "GEMINI_API_KEY" in str(exc_info.value)


def test_serve_refuses_an_unsupported_scope_before_it_looks_ready(monkeypatch):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    monkeypatch.setattr(
        mod, "_serve", MagicMock(side_effect=AssertionError("must not serve"))
    )

    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--serve", "--task-classes", "deal_verdict"])

    assert "--task-classes" in str(exc_info.value)


def test_serve_answers_sigterm_by_clearing_its_heartbeat(monkeypatch, capsys):
    """Under systemd / ``docker stop`` the supervisor is ended with SIGTERM,
    whose default disposition kills it outright — leaving the heartbeat set, so
    ``runner_present`` lies until the key's TTL expires."""
    import signal

    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod, "main", MagicMock(side_effect=AssertionError("nothing was requested"))
    )
    before = signal.getsignal(signal.SIGTERM)

    def _sigterm(_seconds):
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler), "SIGTERM left at SIG_DFL kills the supervisor"
        handler(signal.SIGTERM, None)

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=_sigterm, max_cycles=5)

    assert rc == 0
    assert redis.get("t:supervisor:active") is None
    assert "Supervisor stopped" in capsys.readouterr().out
    # The supervisor puts the disposition back; a test process must not inherit it.
    assert signal.getsignal(signal.SIGTERM) is before


def test_serve_rearms_its_sigterm_handler_after_every_supervised_run(monkeypatch):
    """A run hands SIGTERM back to SIG_DFL when it finishes
    (``_restore_default_signals``); without re-arming, a kill after the first
    run leaves the heartbeat behind again."""
    import signal

    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._control_for(cfg, redis).request_start("admin-api")

    def _run(_argv):
        # What a real run's ``finally`` does on the way out.
        mod._restore_default_signals()
        return 0

    monkeypatch.setattr(mod, "main", _run)
    seen = []

    rc = mod._serve(
        cfg,
        redis,
        _serve_args(),
        sleep_fn=lambda _s: seen.append(callable(signal.getsignal(signal.SIGTERM))),
        max_cycles=2,
    )

    assert rc == 0
    assert seen == [True]


def test_status_reports_the_pending_start_request_and_the_supervisor(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    monkeypatch.setattr(mod, "_observed_rate_per_day", lambda s: None)
    mod._control_for(cfg, redis).request_start("admin-api")
    mod._supervisor_heartbeat_for(cfg, redis).beat()

    mod._print_status(cfg, MagicMock(), redis)

    out = capsys.readouterr().out
    assert "start request        : from admin-api" in out
    assert "waiting for start requests" in out


# ---------------------------------------------------------------------------
# Supervisor resilience and honesty (v0.13-s1.5 follow-up review)
# ---------------------------------------------------------------------------


def test_serve_survives_a_redis_blip_and_serves_the_next_request(monkeypatch, capsys):
    """A supervisor that dies on a connection reset takes the Start button with
    it, and nothing restarts it — the same "request accepted, nothing happens"
    failure ``_run_supervised`` prevents one level down."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._control_for(cfg, redis).request_start("admin-api")
    blips = {"n": 0}
    real_beat = mod._supervisor_heartbeat_for(cfg, redis).beat

    def _flaky_heartbeat(*_a, **_k):
        heartbeat = MagicMock()

        def _beat():
            blips["n"] += 1
            if blips["n"] == 1:
                raise ConnectionError("Connection reset by peer")
            return real_beat()

        heartbeat.beat = _beat
        return heartbeat

    monkeypatch.setattr(mod, "_supervisor_heartbeat_for", _flaky_heartbeat)
    launched = MagicMock(return_value=0)
    monkeypatch.setattr(mod, "main", launched)

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=MagicMock(), max_cycles=2)

    assert rc == 0
    # The blip cost one poll, not the supervisor: the request is still served.
    launched.assert_called_once()
    assert "Poll failed" in capsys.readouterr().err


def test_serve_exits_when_a_signal_stopped_the_run_it_was_supervising(
    monkeypatch, capsys
):
    """``systemctl stop`` during a live run reaches the supervisor, whose signal
    dispositions the run had taken over. Returning to the poll loop is how a
    stop request turned into a SIGKILL after ``TimeoutStopSec``."""
    import signal

    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    control.request_start("admin-api")

    def _run_stopped_by_systemd(_argv):
        # Exactly what a live run does: it owns the dispositions for its
        # duration, and the signal arrives there rather than in the loop.
        mod._install_stop_signals(control)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return mod.EXIT_STOPPED

    monkeypatch.setattr(mod, "main", _run_stopped_by_systemd)
    slept = []

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=slept.append, max_cycles=9)

    assert rc == 0
    out = capsys.readouterr().out
    assert "stop requested, exiting" in out
    # It exited on the signal instead of polling out the remaining cycles.
    assert slept == []
    assert redis.get("t:supervisor:active") is None


def test_serve_leaves_a_start_request_pending_while_a_migration_holds_the_db(
    monkeypatch, capsys
):
    """The launched run would only wait the migration out (up to
    ``migration_wait_seconds``) or be refused — and ``consume_start`` is
    destructive, so the request would be spent on a run that never happened."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    real_control = mod._control_for(cfg, redis)
    real_control.request_start("admin-api")
    spy = MagicMock(wraps=real_control)
    monkeypatch.setattr(mod, "_control_for", lambda *a, **k: spy)
    # The key belongs to ``migrate-primary.sh``; the runner only ever reads it.
    redis.set(mod._migration_gate_for(cfg, redis).key, "migrate-primary:1234")
    monkeypatch.setattr(
        mod, "main", MagicMock(side_effect=AssertionError("must not launch a run"))
    )

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=MagicMock(), max_cycles=3)

    assert rc == 0
    spy.consume_start.assert_not_called()
    assert real_control.start_request() is not None
    out = capsys.readouterr().out
    assert "a primary migration holds the database" in out
    assert out.count("keeping the request") == 1


def test_serve_says_so_when_a_deferred_start_request_expires_unserved(
    monkeypatch, capsys
):
    """The loop promises to hold the request until the lease frees, but the
    level expires in an hour — so a request can vanish after that promise with
    nothing anywhere saying the run will not happen."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    control.request_start("admin-api")
    assert mod.BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    monkeypatch.setattr(
        mod, "main", MagicMock(side_effect=AssertionError("must not launch a run"))
    )

    def _expire_the_request(_seconds):
        control.clear_start()  # the 1h TTL lapsing, deterministically

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=_expire_the_request, max_cycles=3)

    assert rc == 0
    out = capsys.readouterr().out
    assert "keeping the request" in out
    # Named as gone, not as "expired": a pause cancels a pending start too, and
    # this loop cannot tell the two apart (see the cancellation test below).
    assert "The pending start request is gone" in out
    assert "nothing was launched for it" in out


def test_serve_does_not_blame_expiry_for_a_start_a_pause_cancelled(
    monkeypatch, capsys
):
    """``POST /admin/backfill/pause`` withdraws a pending start whenever no run
    holds the lease — so under a migration blocker the request disappears
    because the operator cancelled it. Telling them it expired and to "press
    Start again" prescribes undoing the command they just issued."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    control.request_start("admin-api")
    # A migration, not a lease: the blocker the API still cancels a start under.
    redis.set(mod._migration_gate_for(cfg, redis).key, "migrate-primary:1234")
    monkeypatch.setattr(
        mod, "main", MagicMock(side_effect=AssertionError("must not launch a run"))
    )

    def _pause_cancels_it(_seconds):
        control.clear_start()  # exactly what backfill_pause does

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=_pause_cancels_it, max_cycles=3)

    assert rc == 0
    out = capsys.readouterr().out
    assert "expired before it could be served" not in out
    assert "press Start again" not in out
    assert "expired, or was cancelled by a pause" in out


def test_serve_announces_a_deferred_request_that_vanishes_as_the_blocker_clears(
    monkeypatch, capsys
):
    """The blocker clearing and the request disappearing in the same poll fell
    between the two branches: the deferred announcement only fires while a
    blocker is still in place, and the consume path said nothing at all — so the
    promise to hold the request ended in silence."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    control.request_start("admin-api")
    lease = mod.BackfillLease(redis, prefix="t", owner="host:4711")
    assert lease.acquire()
    monkeypatch.setattr(
        mod, "main", MagicMock(side_effect=AssertionError("must not launch a run"))
    )

    def _free_the_lease_and_lose_the_request(_seconds):
        lease.release()
        control.clear_start()

    rc = mod._serve(
        cfg,
        redis,
        _serve_args(),
        sleep_fn=_free_the_lease_and_lose_the_request,
        max_cycles=3,
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "keeping the request" in out
    assert "The pending start request is gone" in out


# ---------------------------------------------------------------------------
# A tripped AI circuit breaker is terminal and names itself (v0.13-s3.2)
# ---------------------------------------------------------------------------


def test_a_one_shot_pass_that_tripped_the_breaker_exits_nine(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            return_value=_br(mod, processed=0, errors=3, ai_fallbacks=3,
                             ai_circuit_open=True)
        ),
    )

    rc = mod.main(["--limit", "10"])

    assert rc == mod.EXIT_AI_CIRCUIT_OPEN == 9
    out = capsys.readouterr().out
    assert "fabricated results" in out
    assert "revoked/expired API key" in out
    # Not the quota vocabulary: no provider refused on quota here.
    assert redis.get("t:state") == "idle"


def test_continuous_with_the_breaker_tripped_exits_nine_without_sleeping(
    monkeypatch, capsys
):
    """Not a 24h RPD sleep, not EXIT_STALLED, not exit 0."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            return_value=_br(mod, processed=0, errors=3, ai_fallbacks=3,
                             ai_circuit_open=True, budget_exhausted=True)
        ),
    )
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=2, candidates=8))
    )
    sleep_spy = MagicMock()
    monkeypatch.setattr(mod.time, "sleep", sleep_spy)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_AI_CIRCUIT_OPEN
    assert rc != mod.EXIT_STALLED
    sleep_spy.assert_not_called()  # a revoked key is not fixed by waiting
    assert "fabricated results" in capsys.readouterr().out


def test_a_tripped_breaker_is_never_reported_as_a_completed_backfill(
    monkeypatch, capsys
):
    """The census counts quarantined rows as no-longer-remaining, so a trip on
    the last candidates could otherwise print BACKFILL COMPLETE and exit 0 —
    the one sentence an unattended supervisor must never hear from a broken
    account."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            return_value=_br(mod, processed=0, errors=3, ai_fallbacks=3,
                             ai_circuit_open=True)
        ),
    )
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=10, candidates=0))
    )

    rc = mod.main(["--continuous"])

    out = capsys.readouterr().out
    assert rc == mod.EXIT_AI_CIRCUIT_OPEN
    assert rc not in (mod.EXIT_COMPLETE, mod.EXIT_COMPLETE_WITH_QUARANTINE)
    assert "BACKFILL COMPLETE" not in out
    assert "fabricated results" in out


def test_a_quota_refusal_still_wins_over_the_breaker_branch(monkeypatch):
    """The breaker branch must not swallow the story-1.3 quota back-off."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.quota_backoff_seconds = 900
    _open_budget_window(redis, consumed=30)

    rc, slept = _continuous_after_quota(mod, monkeypatch, redis)

    assert rc == mod.EXIT_COMPLETE
    assert slept == pytest.approx(900.0)


def test_the_breaker_threshold_comes_from_config_not_a_literal(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.max_consecutive_ai_failures = 7
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        captured.update(kwargs)
        from core.backfill_runner import BackfillResult

        return BackfillResult()

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)

    mod._run(cfg, MagicMock(), redis, _run_args(limit=1))

    assert captured["max_consecutive_ai_failures"] == 7


# ---------------------------------------------------------------------------
# Liveness ticker wiring (v0.14-s1.12)
# ---------------------------------------------------------------------------


def _liveness_threads():
    import threading

    return [t for t in threading.enumerate() if t.name == "backfill-liveness"]


def _spy_ticker(mod, monkeypatch, events, redis, *, lease_lost=None):
    """Replace ``LivenessTicker`` with a subclass that records start and stop."""
    real = mod.LivenessTicker

    class _Spy(real):
        def start(self):
            events.append(("start", "t:lease" in redis.kv))
            return super().start()

        def stop(self, timeout=5.0):
            events.append(("stop", "t:lease" in redis.kv, redis.kv.get("t:state")))
            super().stop(timeout)

    if lease_lost is not None:
        _Spy.lease_lost = property(lambda self: lease_lost())

    monkeypatch.setattr(mod, "LivenessTicker", _Spy)
    return _Spy


def test_the_ticker_runs_from_the_lease_acquire_to_just_before_the_release(monkeypatch):
    """One ticker for the whole run: started holding the lease, stopped before
    the final state is published and the lease is released."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    events = []
    spy = _spy_ticker(mod, monkeypatch, events, redis)
    during = {}

    def _pass(*_args, **kwargs):
        during["liveness"] = kwargs["liveness"]
        during["threads"] = len(_liveness_threads())
        return _br(mod, processed=1)

    monkeypatch.setattr(mod, "_run", _pass)

    assert mod.main(["--limit", "1"]) == 0

    # Started with the lease already held; stopped while it was still held and
    # before ``idle`` was published.
    assert events == [("start", True), ("stop", True, None)]
    assert isinstance(during["liveness"], spy)
    assert during["liveness"].lease is not None
    assert during["threads"] == 1
    assert _liveness_threads() == []
    assert redis.get("t:state") == "idle"
    assert redis.get("t:lease") is None


def test_a_dry_run_starts_no_ticker(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="")
    events = []
    _spy_ticker(mod, monkeypatch, events, redis)

    assert mod.main(["--dry-run", "--limit", "1"]) == 0

    assert events == []
    assert _liveness_threads() == []


def test_the_ticker_is_stopped_even_when_the_pass_raises(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    events = []
    _spy_ticker(mod, monkeypatch, events, redis)
    monkeypatch.setattr(mod, "_run", MagicMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        mod.main(["--limit", "1"])

    assert [e[0] for e in events] == ["start", "stop"]
    assert _liveness_threads() == []
    assert redis.get("t:lease") is None


def test_a_loss_only_the_ticker_found_is_a_lost_lease_at_exit(monkeypatch, capsys):
    """An outage as long as the lease TTL is found by the ticker, not by the
    pass: the exit must still say lease lost and leave the shared keys alone."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    lost = {"now": False}
    _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: lost["now"])

    def _pass(*_args, **_kwargs):
        # A successor owns the keys by the time the pass returns.
        redis.kv["t:lease"] = "successor"
        redis.kv["t:state"] = "running"
        lost["now"] = True
        return _br(mod, processed=1)  # the pass itself never noticed

    monkeypatch.setattr(mod, "_run", _pass)

    assert mod.main(["--limit", "1"]) == mod.EXIT_LEASE_LOST == 7

    assert redis.get("t:state") == "running"  # no ``idle`` over the successor
    assert redis.get("t:lease") == "successor"
    assert "LEASE LOST" in capsys.readouterr().out


def test_continuous_reports_a_loss_the_ticker_found_during_the_census(monkeypatch, capsys):
    """The census runs after the pass's last renew. A queue the successor
    drained must not be reported as this run's completion."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    lost = {"now": False}
    _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: lost["now"])
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))

    def _slow_census(*_args, **_kwargs):
        lost["now"] = True
        return _census()  # reads complete

    monkeypatch.setattr(mod, "_census", _slow_census)

    assert mod.main(["--continuous"]) == mod.EXIT_LEASE_LOST
    assert "LEASE LOST" in capsys.readouterr().out


def test_continuous_hands_one_ticker_to_the_pass_and_to_the_budget_sleep(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            side_effect=[
                _br(mod, processed=2, budget_exhausted=True, quota_exhausted=True),
                _br(mod, processed=3),
            ]
        ),
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=2, candidates=3), _census()]),
    )
    sleeps = []
    monkeypatch.setattr(
        mod, "_sleep_for_reset", lambda wait, **kw: sleeps.append(kw) or "elapsed"
    )

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    tickers = {id(call.kwargs["liveness"]) for call in mod._run.call_args_list}
    assert len(tickers) == 1
    assert isinstance(mod._run.call_args.kwargs["liveness"], mod.LivenessTicker)
    assert len(sleeps) == 1
    assert sleeps[0]["liveness"] is mod._run.call_args.kwargs["liveness"]
    assert "lease" not in sleeps[0]


def test_the_migration_wait_renews_through_the_ticker(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.lease_ttl_seconds = 3  # renew every 1s of wait
    cfg.backfill.control_poll_seconds = 1.0
    redis.set("t:migrating", "migrate-primary:host:1:1")
    lease = MagicMock()
    lease.renew.return_value = False
    monkeypatch.setattr(mod.time, "sleep", MagicMock())
    now = {"t": 0.0}

    def _monotonic():
        now["t"] += 2.0
        return now["t"]

    monkeypatch.setattr(mod.time, "monotonic", _monotonic)

    outcome = mod._wait_out_migration(
        cfg, redis, liveness=mod.LivenessTicker(lease=lease)
    )

    assert outcome == "lease_lost"
    assert lease.renew.call_count == 1


def test_a_pass_turns_writing_on_before_the_gate_read_and_off_after(monkeypatch):
    """The set-then-check order with ``migrate-primary.sh``, through the ticker."""
    mod = _load_module()
    trail = []

    class _GateRedis(_FakeRedis):
        def get(self, k):
            if k == "t:migrating":
                trail.append("gate-read")
            return super().get(k)

    redis = _GateRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())

    class _Ticker(mod.LivenessTicker):
        def set_writing(self, writing):
            super().set_writing(writing)
            trail.append(("writing", writing, redis.kv.get("t:active")))

    ticker = _Ticker(heartbeat=mod.Heartbeat(redis, prefix="t"))
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        trail.append("rows")
        captured.update(kwargs)
        captured["active_during"] = redis.kv.get("t:active")
        return _br(mod)

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)

    mod._run(cfg, MagicMock(), redis, _run_args(limit=1), liveness=ticker)

    assert trail == [
        "gate-read",  # the early probe, before any DB query
        ("writing", True, "1"),  # beaten on this thread...
        "gate-read",  # ...before the authoritative read
        "rows",
        ("writing", False, None),  # cleared: the census reads as idle
    ]
    assert captured["liveness"] is ticker
    assert captured["active_during"] == "1"


def test_a_pass_without_a_ticker_makes_the_same_synchronous_transitions(monkeypatch):
    mod = _load_module()
    redis = _RecordingRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        captured.update(kwargs)
        captured["active_during"] = redis.kv.get("t:active")
        return _br(mod)

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)

    mod._run(cfg, MagicMock(), redis, _run_args(limit=1))

    assert isinstance(captured["liveness"], mod.LivenessTicker)
    assert captured["active_during"] == "1"
    assert redis.kv.get("t:active") is None
    beat = redis.ops.index(("set", "t:active"))
    last_gate_read = max(
        i for i, op in enumerate(redis.ops) if op == ("get", "t:migrating")
    )
    assert beat < last_gate_read
    assert _liveness_threads() == []  # built, never started


def test_a_pass_reads_as_running_before_the_candidate_fetch(monkeypatch):
    """The fetch and the photo gating take minutes on a full queue (DW-21)."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    _stub_run_backfill(mod, monkeypatch)
    lease = mod._lease_for(cfg, redis)
    assert lease.acquire() is True
    seen = {}

    def _fetch(_session, _params):
        seen["state"] = redis.get("t:state")
        return []

    monkeypatch.setattr(mod, "fetch_candidate_rows", _fetch)

    mod._run(
        cfg, MagicMock(), redis, _run_args(limit=1),
        control=mod._control_for(cfg, redis), lease=lease,
    )

    assert seen["state"] == "running"


def test_a_displaced_pass_does_not_publish_running_over_its_successor(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    _stub_run_backfill(mod, monkeypatch)
    lease = mod._lease_for(cfg, redis)
    assert lease.acquire() is True
    redis.kv["t:lease"] = "successor"
    redis.kv["t:state"] = "paused"

    mod._run(
        cfg, MagicMock(), redis, _run_args(limit=1),
        control=mod._control_for(cfg, redis), lease=lease,
    )

    assert redis.get("t:state") == "paused"
    assert redis.get("t:active") is None  # and never beat `:active` either


def test_the_progress_hook_touches_no_redis_key(monkeypatch):
    """`:active` is the ticker's now; the hook only logs."""
    mod = _load_module()
    redis = _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    captured = {}

    async def fake_run_backfill(rows, **kwargs):
        captured["on_progress"] = kwargs["on_progress"]
        return _br(mod)

    monkeypatch.setattr(mod, "run_backfill", fake_run_backfill)
    mod._run(cfg, MagicMock(), redis, _run_args(limit=1))
    redis.sets.clear()

    captured["on_progress"](_br(mod, processed=25))

    assert redis.sets == []


def test_serve_keeps_the_supervisor_heartbeat_alive_while_it_drives_a_run(monkeypatch):
    """DW-34: the poll loop does not turn during a run, so the key expired and
    ``--status`` said the supervisor was not running for the whole run."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._control_for(cfg, redis).request_start("admin-api")
    clock = {"t": 0.0}
    made = []
    real = mod.LivenessTicker

    class _Clocked(real):
        def __init__(self, **kwargs):
            super().__init__(clock=lambda: clock["t"], **kwargs)
            made.append(self)

    monkeypatch.setattr(mod, "LivenessTicker", _Clocked)
    seen = {}

    def _driven_run(_argv):
        seen["thread_during"] = len(_liveness_threads())
        # The key's TTL runs out mid-run; the next due tick brings it back.
        redis.kv.pop("t:supervisor:active", None)
        clock["t"] += 60.0
        made[-1].tick()
        seen["heartbeat_during"] = redis.get("t:supervisor:active")
        seen["runner_active_during"] = redis.get("t:active")
        return 0

    monkeypatch.setattr(mod, "main", _driven_run)

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=MagicMock(), max_cycles=1)

    assert rc == 0
    assert seen == {
        "thread_during": 1,
        # Beaten by the ticker, with the identity ``--status`` reads back.
        "heartbeat_during": mod._process_id(),
        # Only its own key: a supervisor must never block a migration.
        "runner_active_during": None,
    }
    assert len(made) == 1
    assert _liveness_threads() == []


def _status_output(mod, monkeypatch, capsys, cfg, redis):
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    monkeypatch.setattr(mod, "_observed_rate_per_day", lambda s: None)
    mod._print_status(cfg, MagicMock(), redis)
    return capsys.readouterr().out


def test_status_says_the_supervisor_is_running_and_busy_while_a_run_holds_the_lease(
    monkeypatch, capsys
):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._supervisor_heartbeat_for(cfg, redis).beat()
    assert mod._lease_for(cfg, redis).acquire() is True

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)

    assert "supervisor           : running — busy, a run holds the lease" in out


def test_status_says_an_idle_supervisor_is_running_and_waiting(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._supervisor_heartbeat_for(cfg, redis).beat()

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)

    assert "supervisor           : running — waiting for start requests" in out


def test_status_says_no_supervisor_when_its_key_is_absent(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    # A run holding the lease does not make a supervisor appear.
    assert mod._lease_for(cfg, redis).acquire() is True

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)

    assert "supervisor           : not running (--serve)" in out


def test_status_tells_a_hand_started_run_from_the_one_the_supervisor_drives(
    monkeypatch, capsys
):
    """An idle supervisor beside a run started from another process is not busy.

    The supervisor beats its key with its own ``host:pid`` and the run it
    drives lives in that same process, so a lease owned by anyone else is a
    run it did not start.
    """
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._supervisor_heartbeat_for(cfg, redis).beat()
    monkeypatch.setattr(mod, "_process_id", lambda: "otherhost:4242")
    assert mod._lease_for(cfg, redis).acquire() is True

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)

    assert (
        "supervisor           : running — idle; a run in another process "
        "(otherhost:4242) holds the lease, so a start request waits"
    ) in out
    assert "busy" not in out.split("supervisor           :")[1].splitlines()[0]


def test_status_keeps_the_plain_busy_line_for_a_supervisor_key_without_identity(
    monkeypatch, capsys
):
    """A supervisor started before the key carried ``host:pid`` beats ``1``."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    redis.set("t:supervisor:active", "1", ex=30)
    monkeypatch.setattr(mod, "_process_id", lambda: "otherhost:4242")
    assert mod._lease_for(cfg, redis).acquire() is True

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)

    assert "supervisor           : running — busy, a run holds the lease" in out


def test_status_keeps_the_plain_busy_line_when_the_lease_owner_is_unknown(
    monkeypatch, capsys
):
    """No lease meta (its write is best effort): the owner cannot be compared."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod._supervisor_heartbeat_for(cfg, redis).beat()
    redis.set("t:lease", "some-token", ex=900)

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)

    assert "supervisor           : running — busy, a run holds the lease" in out


# ---------------------------------------------------------------------------
# Liveness ticker wiring — review follow-up (v0.14-s1.12)
# ---------------------------------------------------------------------------


class _OutageRedis(_FakeRedis):
    """Every command raises once ``down`` is set: Redis during an outage."""

    down = False


def _raise_when_down(name):
    real = getattr(_FakeRedis, name)

    def method(self, *args, **kwargs):
        if self.down:
            raise ConnectionError("redis is down")
        return real(self, *args, **kwargs)

    return method


for _name in (
    "get", "set", "delete", "incrby", "expire", "hgetall", "hget", "hset",
    "hincrby", "hdel",
):
    setattr(_OutageRedis, _name, _raise_when_down(_name))


def test_continuous_exits_lease_lost_when_redis_is_still_down_after_the_loss(
    monkeypatch, capsys
):
    """An outage as long as the lease TTL: the ticker latched the loss, the pass
    never noticed, and the census (which reads the ledger in Redis) raises."""
    mod = _load_module()
    redis = _OutageRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    lost = {"now": False}
    _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: lost["now"])

    def _pass(*_args, **_kwargs):
        redis.down = True
        lost["now"] = True
        return _br(mod, processed=1)

    monkeypatch.setattr(mod, "_run", _pass)
    monkeypatch.setattr(
        mod, "_census", lambda cfg, session, ledger: ledger.quarantined_ids()
    )

    assert mod.main(["--continuous"]) == mod.EXIT_LEASE_LOST == 7

    assert "LEASE LOST" in capsys.readouterr().out


def test_continuous_still_raises_a_census_failure_while_the_lease_is_held(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))
    monkeypatch.setattr(mod, "_census", MagicMock(side_effect=RuntimeError("db gone")))

    with pytest.raises(RuntimeError, match="db gone"):
        mod.main(["--continuous"])


def test_a_single_pass_exits_lease_lost_when_redis_is_still_down_after_the_loss(
    monkeypatch, capsys
):
    mod = _load_module()
    redis = _OutageRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)

    def _pass(*_args, **_kwargs):
        redis.down = True
        return _br(mod, processed=1, lease_lost=True)

    monkeypatch.setattr(mod, "_run", _pass)

    assert mod.main(["--limit", "1"]) == mod.EXIT_LEASE_LOST == 7

    assert "LEASE LOST" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--continuous"], ["--limit", "1"]])
def test_a_pass_that_dies_on_redis_after_the_loss_exits_lease_lost(
    monkeypatch, capsys, argv
):
    """The loss was latched during the candidate fetch and Redis is still down:
    the next Redis read of the pass (the ledger, the migration gate) raises
    before the launch loop is ever reached."""
    mod = _load_module()
    redis = _OutageRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    lost = {"now": False}
    _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: lost["now"])

    def _pass(*_args, **_kwargs):
        redis.down = True
        lost["now"] = True
        return redis.get("t:migrating")  # raises: Redis is down

    monkeypatch.setattr(mod, "_run", _pass)

    assert mod.main(argv) == mod.EXIT_LEASE_LOST == 7

    assert "LEASE LOST" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--continuous"], ["--limit", "1"]])
def test_a_pass_that_dies_on_redis_while_the_lease_is_held_still_raises(
    monkeypatch, argv
):
    mod = _load_module()
    redis = _OutageRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)

    def _pass(*_args, **_kwargs):
        raise ConnectionError("redis blip")

    monkeypatch.setattr(mod, "_run", _pass)

    with pytest.raises(ConnectionError, match="redis blip"):
        mod.main(argv)


def test_the_census_less_lease_lost_banner_keeps_the_totals_of_the_run(
    monkeypatch, capsys
):
    mod = _load_module()
    redis = _OutageRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    lost = {"now": False}
    _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: lost["now"])

    def _pass(*_args, **_kwargs):
        redis.down = True
        lost["now"] = True
        return _br(mod, processed=7, errors=2)

    monkeypatch.setattr(mod, "_run", _pass)
    monkeypatch.setattr(
        mod, "_census", lambda cfg, session, ledger: ledger.quarantined_ids()
    )

    assert mod.main(["--continuous"]) == mod.EXIT_LEASE_LOST

    out = capsys.readouterr().out
    assert "cycles 1" in out
    assert "enriched this run 7 · errors 2" in out


def test_a_dry_run_never_touches_the_active_key_of_a_live_run(monkeypatch):
    """A dry run writes no row. Beside a live pass it used to beat that pass's
    ``:active`` key and delete it on the way out, so ``migrate-primary.sh``
    read an idle guard until the live run's next beat."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    mod.Heartbeat(redis, prefix="t").beat()  # the live run
    monkeypatch.setattr(mod, "fetch_candidate_rows", lambda _session, _params: [])
    touched = []
    real_set, real_delete = redis.set, redis.delete
    redis.set = lambda k, *a, **kw: (touched.append(k), real_set(k, *a, **kw))[1]
    redis.delete = lambda k: (touched.append(k), real_delete(k))[1]

    mod._run(cfg, MagicMock(), redis, _run_args(limit=1, dry_run=True))

    assert redis.get("t:active") == "1"
    assert "t:active" not in touched


def test_a_pause_read_that_raises_at_pass_start_still_reaches_the_fetch(monkeypatch):
    """The pause read only chooses the word that is published: decoration."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    is_paused = control.is_paused
    calls = {"n": 0}

    def _first_read_fails():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("redis blip")
        return is_paused()

    control.is_paused = _first_read_fails
    lease = mod._lease_for(cfg, redis)
    assert lease.acquire() is True

    seen = _pass_start(mod, monkeypatch, redis, cfg, control=control, lease=lease)

    assert calls["n"] >= 1
    assert seen == ["running"]


def test_a_displaced_single_pass_does_not_claim_a_stop_aimed_at_its_successor(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)

    def _pass(*_args, **_kwargs):
        redis.kv["t:lease"] = "successor"
        control.request_stop()  # aimed at the successor
        return _br(mod, processed=1, lease_lost=True)

    monkeypatch.setattr(mod, "_run", _pass)

    assert mod.main(["--limit", "1"]) == mod.EXIT_LEASE_LOST

    assert control.should_stop() is True


def test_main_leaves_the_successors_keys_alone_when_the_pass_raises_on_a_lost_lease(
    monkeypatch,
):
    """Here the ticker's verdict in the exit ``finally`` is the only guard: the
    pass raised, so no result ever said the lease was lost."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    lost = {"now": False}
    _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: lost["now"])

    def _pass(*_args, **_kwargs):
        redis.kv["t:lease"] = "successor"
        redis.kv["t:state"] = "running"
        control.request_stop()  # aimed at the successor
        lost["now"] = True
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "_run", _pass)

    with pytest.raises(RuntimeError, match="boom"):
        mod.main(["--limit", "1"])

    assert redis.get("t:state") == "running"
    assert control.should_stop() is True
    assert redis.get("t:lease") == "successor"


def _wait_cfg():
    cfg = MagicMock()
    cfg.backfill.redis_prefix = "t"
    cfg.backfill.control_poll_seconds = 1.0
    cfg.backfill.lease_ttl_seconds = 900
    cfg.backfill.migration_wait_seconds = 1800
    return cfg


def _clocked_ticker(mod, **kwargs):
    clock = {"t": 0.0}
    return clock, mod.LivenessTicker(clock=lambda: clock["t"], **kwargs)


def test_the_budget_sleep_reads_a_lost_lease_before_a_pending_stop(monkeypatch):
    """The ticker found the loss; the loop's own renew is not due and would
    still succeed. A stop pending by then is aimed at the successor."""
    mod = _load_module()
    lease = MagicMock()
    lease.ttl_seconds = 900
    lease.renew.return_value = True
    clock, ticker = _clocked_ticker(mod, lease=lease)
    control = MagicMock()
    control.should_stop.return_value = False
    control.is_paused.return_value = False

    def _sleep(_seconds):
        clock["t"] += 1000.0  # a whole TTL with no successful renew
        control.should_stop.return_value = True

    monkeypatch.setattr(mod.time, "sleep", _sleep)

    outcome = mod._sleep_for_reset(3600.0, cfg=_wait_cfg(), control=control, liveness=ticker)

    assert outcome == "lease_lost"
    assert lease.renew.call_count == 1  # the one at the start of the wait


def test_the_migration_wait_reads_a_lost_lease_before_a_pending_stop(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    redis.set("t:migrating", "migrate-primary:host:1:1")
    lease = MagicMock()
    lease.ttl_seconds = 900
    lease.renew.return_value = True
    clock, ticker = _clocked_ticker(mod, lease=lease)
    control = mod.BackfillControl(redis, prefix="t")

    def _sleep(_seconds):
        clock["t"] += 1000.0
        control.request_stop()

    monkeypatch.setattr(mod.time, "sleep", _sleep)

    outcome = mod._wait_out_migration(_wait_cfg(), redis, control=control, liveness=ticker)

    assert outcome == "lease_lost"
    assert lease.renew.call_count == 0  # not due yet, and never reached
    assert control.should_stop() is True  # still there for the successor


def test_the_budget_sleep_publishes_through_the_ticker(monkeypatch):
    """Published past the ticker, ``backing-off`` would be overwritten by the
    ``running`` the timer still remembers."""
    mod = _load_module()
    redis = _FakeRedis()
    control = mod.BackfillControl(redis, prefix="t")
    clock, ticker = _clocked_ticker(mod, control=control)
    ticker.set_state(mod.BackfillState.RUNNING)
    monkeypatch.setattr(mod.time, "sleep", MagicMock())

    assert mod._sleep_for_reset(3.0, cfg=_wait_cfg(), control=control, liveness=ticker) == "elapsed"
    assert redis.get("t:state") == "backing-off"

    clock["t"] += 60.0  # past the 30s state period
    ticker.tick()
    assert redis.get("t:state") == "backing-off"


def test_the_migration_wait_publishes_through_the_ticker(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    redis.set("t:migrating", "migrate-primary:host:1:1")
    control = mod.BackfillControl(redis, prefix="t")
    clock, ticker = _clocked_ticker(mod, control=control)
    ticker.set_state(mod.BackfillState.RUNNING)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: redis.delete("t:migrating"))

    outcome = mod._wait_out_migration(_wait_cfg(), redis, control=control, liveness=ticker)

    assert outcome == "cleared"
    assert redis.get("t:state") == "blocked"

    clock["t"] += 60.0
    ticker.tick()
    assert redis.get("t:state") == "blocked"


def _pass_start(mod, monkeypatch, redis, cfg, *, control, lease, liveness=None):
    """Run one stubbed pass; return the state key as the candidate fetch saw it."""
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    _stub_run_backfill(mod, monkeypatch)
    seen = []

    def _fetch(_session, _params):
        seen.append(redis.get("t:state"))
        return []

    monkeypatch.setattr(mod, "fetch_candidate_rows", _fetch)
    mod._run(
        cfg, MagicMock(), redis, _run_args(limit=1),
        control=control, lease=lease, liveness=liveness,
    )
    return seen


def test_a_pass_that_starts_under_a_pending_pause_reads_as_paused(monkeypatch):
    """An acknowledged ``paused`` must not flip to ``running`` for the fetch."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    control.request_pause()
    lease = mod._lease_for(cfg, redis)
    assert lease.acquire() is True

    assert _pass_start(mod, monkeypatch, redis, cfg, control=control, lease=lease) == ["paused"]


def test_a_failed_publish_at_pass_start_is_retried_by_the_ticker(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    publish = control.publish_state
    calls = {"n": 0}

    def _first_publish_fails(state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("redis blip")
        publish(state)

    control.publish_state = _first_publish_fails
    lease = mod._lease_for(cfg, redis)
    assert lease.acquire() is True
    clock, ticker = _clocked_ticker(
        mod, lease=lease, control=control, heartbeat=mod.Heartbeat(redis, prefix="t")
    )

    seen = _pass_start(
        mod, monkeypatch, redis, cfg, control=control, lease=lease, liveness=ticker
    )

    assert seen == [None]  # the blip did not stop the pass reaching the fetch
    clock["t"] += 1.0
    ticker.tick()
    assert redis.get("t:state") == "running"


def test_a_renew_that_raises_at_pass_start_still_records_the_state(monkeypatch):
    """A Redis error says nothing about who holds the lease."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    lease = mod._lease_for(cfg, redis)
    assert lease.acquire() is True
    renew = lease.renew
    calls = {"n": 0}

    def _first_renew_fails():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("redis blip")
        return renew()

    lease.renew = _first_renew_fails

    seen = _pass_start(mod, monkeypatch, redis, cfg, control=control, lease=lease)

    assert seen == ["running"]


# ---------------------------------------------------------------------------
# Runner lifecycle ends honestly (v0.14-s1.13)
# ---------------------------------------------------------------------------
#
# One regression test per row of the story's I/O matrix, at the CLI seam:
# the provider that refuses for good (DW-19), the outcome of an API-requested
# run (DW-28), the pause held past its TTL (DW-23), the signal handler that
# only sets a flag (DW-22) and the main-thread watchdog (DW-81).


def _refused(mod):
    return _br(mod, processed=0, budget_exhausted=True, quota_exhausted=True)


def _refusing_provider(mod, monkeypatch, redis, *, passes=None):
    """``--continuous`` against a provider that refuses every pass."""
    # Finite on purpose: without the limit the loop never ends, and a test that
    # hangs says less than one that runs out of passes.
    run = MagicMock(side_effect=passes or [_refused(mod) for _ in range(40)])
    monkeypatch.setattr(mod, "_run", run)
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=0, candidates=5))
    )
    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))
    return run, slept


def test_provider_refuses_permanently_exits_ten_before_the_next_sleep(monkeypatch, capsys):
    """I/O matrix "Provider refuses permanently". Before the limit the run
    slept out a daily window after every refused pass, for ever."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.max_no_progress_cycles = 3
    _open_budget_window(redis, consumed=30)
    run, slept = _refusing_provider(mod, monkeypatch, redis)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_PROVIDER_REFUSED == 10
    assert run.call_count == 3
    # Two back-offs, between passes 1-2 and 2-3. None after the third pass:
    # the run ends before it would sleep again.
    assert sum(slept) == pytest.approx(2 * 900.0)
    out = capsys.readouterr().out
    assert "the provider refused 3 cycles in a row" in out
    # Not waiting for anything any more: ``idle``, not ``backing-off``.
    assert redis.get("t:state") == "idle"
    assert redis.get("t:lease") is None


def test_a_cycle_that_enriches_a_row_resets_the_refusal_count(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.max_no_progress_cycles = 3
    _open_budget_window(redis, consumed=30)
    throttled_but_moving = _br(
        mod, processed=1, budget_exhausted=True, quota_exhausted=True
    )
    run, _slept = _refusing_provider(
        mod,
        monkeypatch,
        redis,
        passes=[
            _refused(mod),
            _refused(mod),
            throttled_but_moving,  # a row got through: the count starts over
            _refused(mod),
            _refused(mod),
            _refused(mod),
        ],
    )

    assert mod.main(["--continuous"]) == mod.EXIT_PROVIDER_REFUSED
    assert run.call_count == 6  # not 3


def test_a_refusal_limit_of_zero_keeps_waiting_as_before(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.max_no_progress_cycles = 0
    _open_budget_window(redis, consumed=30)
    run, _slept = _refusing_provider(
        mod,
        monkeypatch,
        redis,
        passes=[_refused(mod)] * 12 + [_br(mod, processed=5)],
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=0, candidates=5)] * 12 + [_census()]),
    )

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE
    assert run.call_count == 13


def test_every_exit_code_has_an_outcome_word():
    mod = _load_module()
    codes = {
        name: value for name, value in vars(mod).items() if name.startswith("EXIT_")
    }

    assert set(codes.values()) == set(mod._EXIT_OUTCOMES)
    assert sorted(codes.values()) == list(range(12))  # 0..11, none reused
    # The numbers already in use keep their meaning.
    assert mod._EXIT_OUTCOMES[5] == "lease_held"
    assert mod._EXIT_OUTCOMES[6] == "stopped"
    assert mod._EXIT_OUTCOMES[7] == "lease_lost"
    assert mod._EXIT_OUTCOMES[10] == "provider_refused"
    assert mod._EXIT_OUTCOMES[11] == "hung"
    assert len(set(mod._EXIT_OUTCOMES.values())) == len(mod._EXIT_OUTCOMES)
    assert mod._outcome_for_exit(99) == "failed"


# -- the outcome of an API-requested run (DW-28) ----------------------------


def _served_run(mod, monkeypatch, main, *, redis=None, max_cycles=1):
    """Serve one start request with ``main`` replaced; return (redis, control)."""
    import json

    redis = redis if redis is not None else _RecordingSetRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    control.request_start("admin-api")
    monkeypatch.setattr(mod, "main", main)

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=MagicMock(), max_cycles=max_cycles)

    assert rc == 0
    raw = redis.get("t:last_run")
    return cfg, redis, control, (json.loads(raw) if raw else None)


@pytest.mark.parametrize(
    "exit_code,outcome",
    [
        (0, "complete"),
        (3, "stalled"),
        (4, "complete_with_quarantine"),
        (5, "lease_held"),
        (6, "stopped"),
        (7, "lease_lost"),
        (8, "migration_blocked"),
        (9, "ai_circuit_open"),
        (10, "provider_refused"),
        (11, "hung"),
    ],
)
def test_api_requested_run_ends_and_serve_records_the_outcome(
    monkeypatch, exit_code, outcome
):
    """I/O matrix "API-requested run ends": any exit code leaves a record."""
    mod = _load_module()
    seen = {}

    def _main(_argv):
        # While the run is going the record says so, with the supervisor's id.
        seen["during"] = mod._control_for(mod.get_config(), mod.get_redis()).last_run()
        return exit_code

    _cfg, _redis, control, record = _served_run(mod, monkeypatch, _main)

    assert seen["during"]["outcome"] == "started"
    assert seen["during"]["owner"] == mod._process_id()
    assert seen["during"]["source"] == "admin-api"
    assert record["outcome"] == outcome
    assert record["exit_code"] == exit_code
    assert record["source"] == "admin-api"
    assert record["started_at"] == seen["during"]["started_at"]
    assert record["finished_at"]
    assert control.last_run()["outcome"] == outcome


def test_api_requested_run_that_is_refused_records_the_runners_message(monkeypatch):
    mod = _load_module()
    refusal = "GEMINI_API_KEY is not set: export it in the supervisor's shell."

    _cfg, _redis, _control, record = _served_run(
        mod, monkeypatch, MagicMock(side_effect=SystemExit(refusal))
    )

    assert record["outcome"] == "refused"
    assert record["exit_code"] == 1
    assert record["reason"] == refusal


def test_api_requested_run_that_crashes_records_the_exception_type_only(monkeypatch):
    mod = _load_module()
    secret = "https://generativelanguage.googleapis.com/?key=AIza-not-for-the-wire"

    _cfg, redis, _control, record = _served_run(
        mod, monkeypatch, MagicMock(side_effect=RuntimeError(secret))
    )

    assert record["outcome"] == "crashed"
    assert record["exit_code"] == 1
    assert record["reason"] == "RuntimeError — see the supervisor log on the host"
    assert "AIza" not in redis.get("t:last_run")


def test_serve_records_provider_refused_and_says_it_will_not_relaunch(
    monkeypatch, capsys
):
    """AC 1: after exit 10 the supervisor records the outcome and waits for
    the next operator request; it never relaunches on its own."""
    mod = _load_module()
    launched = MagicMock(return_value=10)

    cfg, _redis, _control, record = _served_run(
        mod, monkeypatch, launched, max_cycles=4
    )

    launched.assert_called_once()  # three more polls, no second launch
    assert record["outcome"] == "provider_refused"
    assert "max_no_progress_cycles" in record["reason"]
    assert str(cfg.backfill.max_no_progress_cycles) in record["reason"]
    assert "will not relaunch it on its own" in capsys.readouterr().out


def test_serve_keeps_serving_when_the_outcome_record_cannot_be_written(monkeypatch):
    """Recording is guarded: a Redis error is logged and the supervisor goes on."""
    mod = _load_module()

    class _NoRecordRedis(_RecordingSetRedis):
        def set(self, k, v, ex=None, nx=False):
            if k == "t:last_run":
                raise ConnectionError("redis is down")
            return super().set(k, v, ex=ex, nx=nx)

    redis = _NoRecordRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)
    control.request_start("admin-api")
    launched = MagicMock(return_value=0)
    monkeypatch.setattr(mod, "main", launched)
    slept = []

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=slept.append, max_cycles=3)

    assert rc == 0
    launched.assert_called_once()
    assert slept == [cfg.backfill.control_poll_seconds] * 2  # it kept polling
    assert redis.get("t:last_run") is None


def test_a_run_ended_by_ctrl_c_reads_interrupted_once_the_supervisor_is_gone(monkeypatch):
    """I/O matrix "API-requested run killed outright", as far as a process
    that is still able to run code can show it: the record stays ``started``,
    the lease is free and the supervisor key is gone."""
    from core.backfill_runner import last_run_view

    mod = _load_module()

    cfg, redis, control, record = _served_run(
        mod, monkeypatch, MagicMock(side_effect=KeyboardInterrupt)
    )

    assert record["outcome"] == "started"  # nobody wrote an end
    view = last_run_view(
        control, mod._lease_for(cfg, redis).holder(), mod._supervisor_heartbeat_for(cfg, redis)
    )
    assert view["outcome"] == "interrupted"


def test_status_prints_the_last_run_and_since_when_it_is_paused(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    control = mod._control_for(cfg, redis)

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)
    assert "last run             : none recorded" in out
    assert "paused since         : not paused" in out

    control.record_run_start("admin-api", "host:1")
    control.record_run_end(
        "provider_refused", exit_code=10, reason="refused six cycles", owner="host:1"
    )
    control.request_pause()

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)
    assert "last run             : provider_refused (exit 10) at " in out
    assert "refused six cycles" in out
    assert f"paused since         : {control.paused_since().isoformat()}" in out
    assert "STALE" not in out


def test_status_says_a_pause_older_than_the_request_ttl_is_stale(monkeypatch, capsys):
    from datetime import datetime, timedelta, timezone

    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    long_ago = datetime.now(timezone.utc) - timedelta(days=8)
    redis.set("t:control:pause", long_ago.isoformat())

    out = _status_output(mod, monkeypatch, capsys, cfg, redis)

    assert "STALE" in out
    assert "still set" in out
    # Nothing checked for a run, so the line must not claim one holds it.
    assert "holding it" not in out


# -- the pause held past its TTL, in the wait loops (DW-23) -----------------


def test_the_budget_sleep_holds_a_pause_it_can_see(monkeypatch):
    """A run spends days in this loop: this is where a 7-day request TTL would
    run out. The hold is an EXPIRE, so it never creates a pause."""
    mod = _load_module()
    cfg = _wait_cfg()

    class _ExpireRedis(_FakeRedis):
        def __init__(self):
            super().__init__()
            self.expired = []

        def expire(self, k, ttl):
            self.expired.append((k, ttl))
            return super().expire(k, ttl)

    redis = _ExpireRedis()
    control = mod.BackfillControl(redis, prefix="t")
    control.request_pause()
    redis.expired.clear()
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    # A real wait: four steps of the loop, whose first state publish is where
    # the EXPIRE comes from.
    assert mod._sleep_for_reset(4.0, cfg=cfg, control=control) == "elapsed"

    assert redis.expired == [("t:control:pause", control.request_ttl_seconds)]
    assert redis.get("t:state") == "paused"

    # No pause: nothing is extended and nothing is created.
    control.request_resume()
    redis.expired.clear()
    mod._publish_wait_state(control, mod.LivenessTicker(control=control), mod.BackfillState.BACKING_OFF)
    assert redis.expired == []
    assert redis.get("t:control:pause") is None


def test_a_failed_pause_hold_never_ends_the_wait(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    control = mod.BackfillControl(redis, prefix="t")
    control.request_pause()

    def _down(_k, _ttl):
        raise ConnectionError("redis is down")

    redis.expire = _down

    # Must not raise.
    mod._publish_wait_state(control, mod.LivenessTicker(control=control), mod.BackfillState.BLOCKED)

    assert redis.get("t:state") == "paused"


# -- the signal handler only sets a flag (DW-22) -----------------------------


class _TouchRedis(_FakeRedis):
    """Counts every command, so "the handler made no Redis call" is checkable."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def get(self, k):
        self.calls += 1
        return super().get(k)

    def set(self, k, v, ex=None, nx=False):
        self.calls += 1
        return super().set(k, v, ex=ex, nx=nx)

    def delete(self, k):
        self.calls += 1
        return super().delete(k)

    def expire(self, k, ttl):
        self.calls += 1
        return super().expire(k, ttl)


def test_sigint_or_sigterm_handler_sets_a_flag_and_touches_nothing_else(
    monkeypatch, capsys
):
    """I/O matrix "SIGINT / SIGTERM during a run": no Redis call, no lock, no
    print from the handler; the run observes the flag at its next stop check."""
    import signal

    mod = _load_module()
    redis = _TouchRedis()
    control = mod.BackfillControl(redis, prefix="t")
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        mod._install_stop_signals(control)
        capsys.readouterr()
        calls_before = redis.calls

        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        assert redis.calls == calls_before  # the handler never touched Redis
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == ""  # and printed nothing
        assert mod._STOP_SIGNAL_RECEIVED is True
        # A second signal aborts hard: the default disposition is back.
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        assert redis.get("t:control:stop") is None  # nothing was written yet

        # The run's next stop check sees the flag, says so once, and mirrors
        # the stop to Redis for the status surface.
        assert control.should_stop() is True
        assert control.should_stop() is True
        err = capsys.readouterr().err
        assert err.count("Stop requested — draining in-flight properties") == 1
        assert redis.get("t:control:stop")
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


def test_a_signal_during_a_run_drains_and_exits_six(monkeypatch, capsys):
    """AC 4: the run still stops and exits 6, with the handler doing nothing
    but setting the flag."""
    import signal

    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    def _pass_that_gets_signalled(*_a, **_k):
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        return _br(mod, processed=2)  # the rows in flight drained

    monkeypatch.setattr(mod, "_run", MagicMock(side_effect=_pass_that_gets_signalled))
    try:
        rc = mod.main(["--limit", "3"])
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)

    assert rc == mod.EXIT_STOPPED == 6
    assert "Stop requested" in capsys.readouterr().err
    assert redis.get("t:control:stop") is None  # served, so retired
    assert redis.get("t:state") == "idle"
    assert redis.get("t:lease") is None


def test_a_signal_stops_a_run_whose_redis_is_unreachable(monkeypatch):
    """The reason the handler must not touch Redis: the signal can arrive
    while Redis is not answering, and the stop has to work anyway."""
    import signal

    mod = _load_module()
    redis = _FakeRedis()
    control = mod.BackfillControl(redis, prefix="t")
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    def _down(*_a, **_k):
        raise ConnectionError("redis is down")

    try:
        mod._install_stop_signals(control)
        redis.get = _down
        redis.set = _down

        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)  # must not raise

        assert control.should_stop() is True
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


# -- the main-thread watchdog (DW-81) ----------------------------------------


def test_main_builds_its_ticker_with_the_configured_stall_limit(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.main_thread_stall_seconds = 1800
    made = []
    real = mod.LivenessTicker

    class _Recorded(real):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            made.append((kwargs.get("stall_limit_seconds"), kwargs.get("on_stall")))

    monkeypatch.setattr(mod, "LivenessTicker", _Recorded)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=1)))

    assert mod.main(["--limit", "1"]) == 0

    limit, on_stall = made[0]
    assert limit == 1800.0
    assert callable(on_stall)


def test_main_thread_hang_silences_the_supervisor_key_and_records_hung(monkeypatch):
    """I/O matrix "Main thread hangs", across the two tickers of a supervised
    run: the run's watchdog stops the supervisor's keepalive and writes
    ``hung``; when the thread comes back the run exits 11."""
    import json

    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.main_thread_stall_seconds = 900
    mod._control_for(cfg, redis).request_start("admin-api")
    clock = {"t": 0.0}
    made = []
    real = mod.LivenessTicker

    class _Clocked(real):
        def __init__(self, **kwargs):
            super().__init__(clock=lambda: clock["t"], **kwargs)
            made.append(self)

    monkeypatch.setattr(mod, "LivenessTicker", _Clocked)
    seen = {}

    def _hung_pass(*_a, **_k):
        supervisor_ticker, run_ticker = made[0], made[1]
        clock["t"] += 900.0  # the main thread was stuck in a call this long
        run_ticker.tick()  # what the run's ticker thread did meanwhile
        seen["stalled"] = run_ticker.stalled
        seen["record_while_hung"] = json.loads(redis.get("t:last_run"))
        # The supervisor key is no longer beaten: let it lapse and tick.
        redis.kv.pop("t:supervisor:active", None)
        clock["t"] += 60.0
        supervisor_ticker.tick()
        seen["supervisor_key_while_hung"] = redis.get("t:supervisor:active")
        lease_renews = redis.hashes.get("t:lease:meta", {}).get("last_seen")
        clock["t"] += 600.0
        run_ticker.tick()
        seen["lease_renewed_after"] = (
            redis.hashes.get("t:lease:meta", {}).get("last_seen") != lease_renews
        )
        return _br(mod, processed=0)  # the thread came back

    monkeypatch.setattr(mod, "_run", MagicMock(side_effect=_hung_pass))
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=0, candidates=5))
    )
    printed = []
    monkeypatch.setattr(mod, "_print_banner", lambda title, lines: printed.append(title))

    rc = mod._serve(cfg, redis, _serve_args(), sleep_fn=MagicMock(), max_cycles=1)

    assert rc == 0
    assert seen["stalled"] is True
    assert seen["record_while_hung"]["outcome"] == "hung"
    assert seen["record_while_hung"]["exit_code"] is None
    assert seen["record_while_hung"]["source"] == "admin-api"
    assert seen["supervisor_key_while_hung"] is None
    assert seen["lease_renewed_after"] is False
    # The thread came back: nothing more was launched and the run exited 11.
    assert printed == [mod._MAIN_THREAD_STALLED_TITLE]
    final = json.loads(redis.get("t:last_run"))
    assert (final["outcome"], final["exit_code"]) == ("hung", 11)
    assert final["started_at"] == seen["record_while_hung"]["started_at"]
    assert _liveness_threads() == []


def test_a_stalled_single_pass_exits_eleven_not_seven(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _Spy = _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: True)
    _Spy.stalled = property(lambda self: True)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=0)))

    rc = mod.main(["--limit", "1"])

    assert rc == mod.EXIT_MAIN_THREAD_STALLED == 11
    out = capsys.readouterr().out
    assert "the main thread made no progress" in out
    assert "LEASE LOST" not in out


def test_a_takeover_still_exits_seven(monkeypatch, capsys):
    """The watchdog shares the lease-lost path; a plain takeover keeps its code."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: True)
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=0)))

    assert mod.main(["--limit", "1"]) == mod.EXIT_LEASE_LOST == 7
    assert "LEASE LOST" in capsys.readouterr().out


def test_the_wait_loops_stamp_progress_on_every_step(monkeypatch):
    mod = _load_module()
    cfg = _wait_cfg()
    stamps = {"n": 0}
    ticker = mod.LivenessTicker()
    real_note = ticker.note_progress

    def _note():
        stamps["n"] += 1
        real_note()

    ticker.note_progress = _note
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    assert mod._sleep_for_reset(5.0, cfg=cfg, liveness=ticker) == "elapsed"

    assert stamps["n"] >= 5  # one per control_poll_seconds step


def test_a_pass_stamps_progress_around_the_candidate_fetch(monkeypatch):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    order: list[str] = []
    ticker = mod.LivenessTicker(control=mod._control_for(cfg, redis))
    ticker.note_progress = lambda: order.append("stamp")
    monkeypatch.setattr(
        mod, "fetch_candidate_rows", lambda s, p: order.append("fetch") or []
    )
    monkeypatch.setattr(mod, "_build_client", MagicMock())
    _stub_run_backfill(mod, monkeypatch)

    mod._run(
        cfg, MagicMock(), redis, _run_args(limit=1),
        control=mod._control_for(cfg, redis), liveness=ticker,
    )

    assert order[0] == "stamp"
    assert order[order.index("fetch") + 1] == "stamp"
    assert order.count("stamp") == 3


# ---------------------------------------------------------------------------
# Review follow-ups (v0.14-s1.13)
# ---------------------------------------------------------------------------


def test_a_zero_progress_cycle_on_the_local_budget_does_not_reset_the_refusal_count(
    monkeypatch,
):
    """Only a cycle that enriches a row resets the count. One that ended on
    the local budget with nothing enriched says nothing about the provider."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.max_no_progress_cycles = 3
    _open_budget_window(redis, consumed=30)
    local_budget_only = _br(mod, processed=0, budget_exhausted=True)
    run, _slept = _refusing_provider(
        mod,
        monkeypatch,
        redis,
        passes=[
            _refused(mod),
            local_budget_only,  # neither counts nor clears
            _refused(mod),
            _refused(mod),
            _refused(mod),  # never reached
        ],
    )

    assert mod.main(["--continuous"]) == mod.EXIT_PROVIDER_REFUSED
    assert run.call_count == 4


def test_a_system_exit_with_an_int_code_is_recorded_as_that_codes_outcome(monkeypatch):
    """``SystemExit(2)`` is argparse rejecting the command line: ``usage``,
    not a refusal "before it started"."""
    mod = _load_module()

    _cfg, _redis, _control, record = _served_run(
        mod, monkeypatch, MagicMock(side_effect=SystemExit(2))
    )

    assert record["outcome"] == "usage"
    assert record["exit_code"] == 2
    assert record["reason"] == mod._exit_reason(2, _cfg)

    mod = _load_module()
    _cfg, _redis, _control, record = _served_run(
        mod, monkeypatch, MagicMock(side_effect=SystemExit(0))
    )
    assert (record["outcome"], record["exit_code"], record["reason"]) == (
        "complete", 0, None,
    )


def test_a_hand_started_run_that_stalls_records_hung_and_closes_it_with_eleven(
    monkeypatch,
):
    """No supervisor writes the end of a run started by hand: the callback
    records ``hung`` (source ``cli``) and the exit closes that record."""
    import json

    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.main_thread_stall_seconds = 900
    clock = {"t": 0.0}
    made = []
    real = mod.LivenessTicker

    class _Clocked(real):
        def __init__(self, **kwargs):
            super().__init__(clock=lambda: clock["t"], **kwargs)
            made.append(self)

    monkeypatch.setattr(mod, "LivenessTicker", _Clocked)
    seen = {}

    def _hung_pass(*_a, **_k):
        clock["t"] += 900.0
        made[0].tick()
        seen["while_hung"] = json.loads(redis.get("t:last_run"))
        return _br(mod, processed=0)

    monkeypatch.setattr(mod, "_run", MagicMock(side_effect=_hung_pass))
    monkeypatch.setattr(mod, "_print_banner", lambda title, lines: None)

    rc = mod.main(["--limit", "1"])

    assert rc == mod.EXIT_MAIN_THREAD_STALLED
    assert seen["while_hung"]["outcome"] == "hung"
    assert seen["while_hung"]["exit_code"] is None
    assert seen["while_hung"]["source"] == "cli"
    assert "If the process still exists" in seen["while_hung"]["reason"]
    assert "migrate-primary.sh" in seen["while_hung"]["reason"]
    final = json.loads(redis.get("t:last_run"))
    assert (final["outcome"], final["exit_code"]) == ("hung", 11)
    assert final["source"] == "cli"
    assert final["owner"] == mod._process_id()
    assert final["reason"] == mod._exit_reason(11, cfg)


def test_a_stop_message_that_cannot_be_printed_is_still_a_stop(monkeypatch):
    """A closed stream must not raise out of ``should_stop`` and abort the
    pass instead of draining it: the flag is the stop."""
    import signal

    mod = _load_module()
    control = mod.BackfillControl(_FakeRedis(), prefix="t")
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    class _Closed:
        def write(self, _text):
            raise ValueError("I/O operation on closed file")

        def flush(self):
            raise ValueError("I/O operation on closed file")

    try:
        mod._install_stop_signals(control)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        monkeypatch.setattr(mod.sys, "stderr", _Closed())

        assert control.should_stop() is True
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


def test_installing_the_stop_signals_always_arms_the_local_stop():
    """A control without ``watch_local_stop`` must fail loudly, not leave a
    handler that sets a flag nobody reads."""
    import signal

    mod = _load_module()
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    class _NoWatch:
        pass

    try:
        with pytest.raises(AttributeError):
            mod._install_stop_signals(_NoWatch())
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


def test_the_migration_wait_stamps_progress_on_every_step(monkeypatch):
    mod = _load_module()
    cfg = _wait_cfg()
    redis = _FakeRedis()
    redis.set(mod._migration_gate_for(cfg, redis).key, "migrate-primary:1234")
    stamps = {"n": 0}
    sleeps = {"n": 0}
    ticker = mod.LivenessTicker()
    real_note = ticker.note_progress

    def _note():
        stamps["n"] += 1
        real_note()

    ticker.note_progress = _note
    clock = {"t": 0.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])

    def _sleep(seconds):
        sleeps["n"] += 1
        clock["t"] += seconds

    monkeypatch.setattr(mod.time, "sleep", _sleep)

    outcome = mod._wait_out_migration(cfg, redis, liveness=ticker, budget_seconds=5.0)

    assert outcome == "timeout"
    assert sleeps["n"] >= 5  # one per control_poll_seconds step
    assert stamps["n"] >= sleeps["n"]  # at least one stamp per step


def test_every_outcome_word_has_a_label_in_both_catalogs():
    """The card labels ``last_run.outcome`` from ``operations.lastRun.<word>``.
    A word the runner can write with no label would be shown raw, in English,
    in the pt-BR UI."""
    import json

    mod = _load_module()
    words = set(mod._EXIT_OUTCOMES.values()) | {"refused", "crashed", "interrupted"}
    assert "started" not in words  # never rendered as an ending
    locales = _SCRIPT.parents[2] / "frontend" / "src" / "i18n" / "locales"

    for name in ("en.json", "pt-BR.json"):
        catalog = json.loads((locales / name).read_text(encoding="utf-8"))
        labels = catalog["operations"]["lastRun"]
        missing = sorted(word for word in words if not labels.get(word))
        assert missing == [], f"{name} has no operations.lastRun label for {missing}"


# ---------------------------------------------------------------------------
# Follow-up review (v0.14-s1.13)
# ---------------------------------------------------------------------------


def test_a_cycle_that_enriches_rows_with_budget_to_spare_resets_the_refusal_count(
    monkeypatch,
):
    """A pass that enriched rows and ended with budget left goes straight to
    the next pass. The reset used to sit on the way to the sleep only, so the
    refusals on either side of such a pass added up to a false exit 10."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.max_no_progress_cycles = 3
    _open_budget_window(redis, consumed=30)
    run, _slept = _refusing_provider(
        mod,
        monkeypatch,
        redis,
        passes=[
            _refused(mod),
            _refused(mod),
            _br(mod, processed=2),  # rows got through, budget to spare
            _refused(mod),
            _refused(mod),
            _refused(mod),
        ],
    )

    assert mod.main(["--continuous"]) == mod.EXIT_PROVIDER_REFUSED
    assert run.call_count == 6  # not 4


def test_the_fifth_and_sixth_refusal_are_a_daily_window_apart(monkeypatch):
    """Why the shipped limit of 6 cannot end a run on a healthy provider that
    merely ran out for the day: after the four short back-offs every refused
    pass is followed by a wait of a whole local window, because the pass
    reserved budget (and so opened a window) before it was refused."""
    from datetime import datetime, timedelta, timezone

    from core.backfill_runner import DailyBudget

    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    assert cfg.backfill.max_no_progress_cycles == 6
    # The run has been spending for 20 hours: 4h of its window are left.
    opened = datetime.now(timezone.utc) - timedelta(hours=20)
    redis.hashes["t:budget"] = {
        "count": "300",
        "start": opened.isoformat(),
        "start_epoch": str(opened.timestamp()),
    }

    def _refused_pass(*_a, **_k):
        # What a real refused pass does first: reserve one property.
        assert DailyBudget(redis, prefix="t", daily_limit=14000).try_consume(3)
        return _refused(mod)

    run = MagicMock(side_effect=_refused_pass)
    monkeypatch.setattr(mod, "_run", run)
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=0, candidates=5))
    )
    waits: list[float] = []

    def _wait(wait, **_k):
        waits.append(wait)
        # Time passes: the same as the window having opened that much earlier.
        window = redis.hashes.get("t:budget")
        if window:
            start = datetime.fromisoformat(window["start"]) - timedelta(seconds=wait)
            window["start"] = start.isoformat()
            window["start_epoch"] = str(start.timestamp())
        return "elapsed"

    monkeypatch.setattr(mod, "_sleep_for_reset", _wait)

    assert mod.main(["--continuous"]) == mod.EXIT_PROVIDER_REFUSED
    assert run.call_count == 6
    assert len(waits) == 5
    assert waits[:3] == [900.0, 900.0, 900.0]
    # The rest of the window that was open (4h, less the 45 minutes above).
    assert 3 * 3600 < waits[3] < 4 * 3600 + 300
    # The fifth pass opened a window of its own: a whole day before the sixth.
    assert waits[4] >= 24 * 3600
    assert sum(waits) > 24 * 3600


@pytest.mark.parametrize("where", ["budget-sleep", "migration-wait"])
def test_a_stall_found_in_a_continuous_wait_exits_eleven_not_seven(
    monkeypatch, capsys, where
):
    """The wait loops are where a run spends its days. A watchdog stall that
    surfaces there is ``hung`` (exit 11), not a takeover (exit 7)."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    lost = {"now": False}
    _Spy = _spy_ticker(mod, monkeypatch, [], redis, lease_lost=lambda: lost["now"])
    _Spy.stalled = property(lambda self: lost["now"])
    result = (
        _refused(mod) if where == "budget-sleep" else _br(mod, migration_blocked=True)
    )
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=result))
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=0, candidates=5))
    )

    def _wait(*_a, **_k):
        lost["now"] = True  # the watchdog gave up while this run was waiting
        return "lease_lost"

    monkeypatch.setattr(mod, "_sleep_for_reset", _wait)
    monkeypatch.setattr(mod, "_wait_out_migration", _wait)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_MAIN_THREAD_STALLED == 11
    out = capsys.readouterr().out
    assert "the main thread made no progress" in out
    assert "LEASE LOST" not in out


def test_a_hand_started_continuous_run_that_stalls_closes_its_own_record(monkeypatch):
    """``--continuous`` without a supervisor: nobody else writes the end, so
    the ``hung`` record its watchdog wrote is closed with exit code 11."""
    import json

    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.main_thread_stall_seconds = 900
    clock = {"t": 0.0}
    made = []
    real = mod.LivenessTicker

    class _Clocked(real):
        def __init__(self, **kwargs):
            super().__init__(clock=lambda: clock["t"], **kwargs)
            made.append(self)

    monkeypatch.setattr(mod, "LivenessTicker", _Clocked)
    seen = {}

    def _hung_pass(*_a, **_k):
        clock["t"] += 900.0
        made[0].tick()
        seen["while_hung"] = json.loads(redis.get("t:last_run"))
        return _br(mod, processed=0)

    monkeypatch.setattr(mod, "_run", MagicMock(side_effect=_hung_pass))
    monkeypatch.setattr(
        mod, "_census", MagicMock(return_value=_census(enriched=0, candidates=5))
    )
    monkeypatch.setattr(mod, "_print_banner", lambda title, lines: None)

    rc = mod.main(["--continuous"])

    assert rc == mod.EXIT_MAIN_THREAD_STALLED
    assert seen["while_hung"]["exit_code"] is None
    final = json.loads(redis.get("t:last_run"))
    assert (final["outcome"], final["exit_code"], final["source"]) == ("hung", 11, "cli")
    assert final["reason"] == mod._exit_reason(11, cfg)


# ---------------------------------------------------------------------------
# Transport-quota inference holds across a throttle (v0.14-s1.14)
# ---------------------------------------------------------------------------
#
# The CLI seam of the story: one licence per ``--continuous`` run reaches every
# cycle's client (DW-14), and every end-of-run banner states how many rows were
# classified by inference (DW-16). Every provider answer here is a fake.

_INFERRED_BANNER = "quota inferred from transport storms: "


def test_build_client_threads_the_hold_and_the_shared_licence(monkeypatch):
    mod = _load_module()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    from adapters.ai.client import GeminiClient, TransportQuotaLicence
    from core.enrichment import EnrichmentTaskClass

    scope = {EnrichmentTaskClass.DEAL_VERDICT}
    licence = TransportQuotaLicence()

    shared = mod._build_client(cfg, scope, quota_licence=licence)
    private = mod._build_client(cfg, scope)

    assert shared.quota_licence is licence
    assert private.quota_licence is not licence
    # Not the client default, so a dropped kwarg cannot satisfy this.
    assert shared.transport_quota_hold_seconds == 1800.0
    assert (
        shared.transport_quota_hold_seconds
        != GeminiClient._DEFAULT_TRANSPORT_QUOTA_HOLD_SECONDS
    )


def test_run_hands_its_licence_to_the_client_it_builds(monkeypatch):
    """``_run`` is the only caller of ``_build_client`` on the run path."""
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    build = MagicMock()
    monkeypatch.setattr(mod, "_build_client", build)

    async def _fake_run_backfill(rows, **kw):
        return _br(mod, processed=0)

    monkeypatch.setattr(mod, "run_backfill", _fake_run_backfill)

    mod.main(["--limit", "1"])

    # A single pass has no run-wide licence: the client makes a private one.
    assert build.call_args.kwargs["quota_licence"] is None


def test_continuous_shares_one_licence_with_every_cycle(monkeypatch):
    """DW-14: the evidence must outlive the per-cycle client."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    from adapters.ai.client import TransportQuotaLicence

    run, _slept = _refusing_provider(
        mod,
        monkeypatch,
        redis,
        passes=[_refused(mod), _refused(mod), _br(mod, processed=5)],
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=0, candidates=5)] * 2 + [_census()]),
    )

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    licences = [call.kwargs["quota_licence"] for call in run.call_args_list]
    assert len(licences) == 3
    assert isinstance(licences[0], TransportQuotaLicence)
    assert licences[1] is licences[0] and licences[2] is licences[0]

    # A second run in the same process starts with no evidence of the first.
    run.side_effect = [_br(mod, processed=5)]
    run.reset_mock()
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE
    assert run.call_args.kwargs["quota_licence"] is not licences[0]


@pytest.mark.parametrize(
    ("hold", "warns"),
    [
        (600.0, True),    # shorter than the 900 s back-off: the licence cannot cross
        (900.0, True),    # equal is not longer
        # Longer than the back-off, but the next cycle's first timeout lands
        # ``ai.timeout`` (120 s) after it: still past the hold.
        (1020.0, True),
        (1021.0, False),
        (1800.0, False),
        (0.0, False),     # the hold is off on purpose: nothing to order
    ],
)
def test_a_hold_not_longer_than_the_quota_backoff_is_announced(monkeypatch, hold, warns):
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.ai.gemini_transport_quota_hold_seconds = hold
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=5)))
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    warn_spy = MagicMock()
    monkeypatch.setattr(mod.logger, "warning", warn_spy)

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    events = [c for c in warn_spy.call_args_list if c[0] and c[0][0] == "backfill_quota_hold_not_longer_than_backoff"]
    assert bool(events) is warns
    if warns:
        assert events[0][1]["hold_seconds"] == hold
        assert events[0][1]["quota_backoff_seconds"] == 900.0


def _inferring(mod, rows, *, processed=1):
    """A cycle that got rows through and ended on an inferred refusal."""
    return _br(
        mod,
        processed=processed,
        budget_exhausted=True,
        quota_exhausted=True,
        quota_inferred_ids=[f"p{i}" for i in range(rows)],
    )


def _terminal_events(spy):
    return [c[1] for c in spy.call_args_list if c[0] and c[0][0] == "backfill_terminal"]


@pytest.mark.parametrize(
    ("ending", "final", "final_census", "exit_name", "total"),
    [
        ("complete", dict(processed=1), dict(), "EXIT_COMPLETE", 2),
        (
            "stalled",
            dict(processed=0, errors=1),
            dict(enriched=0, candidates=5),
            "EXIT_STALLED",
            2,
        ),
        (
            "stopped",
            dict(
                processed=0,
                stopped=True,
                budget_exhausted=True,
                quota_exhausted=True,
                quota_inferred_ids=["q0", "q1", "q2"],
            ),
            dict(enriched=0, candidates=5),
            "EXIT_STOPPED",
            5,
        ),
        (
            "breaker",
            dict(processed=0, ai_circuit_open=True, quota_inferred_ids=["q0", "q1", "q2"]),
            dict(enriched=0, candidates=5),
            "EXIT_AI_CIRCUIT_OPEN",
            5,
        ),
        (
            "lease_lost",
            dict(processed=0, lease_lost=True, quota_inferred_ids=["q0", "q1", "q2"]),
            dict(enriched=0, candidates=5),
            "EXIT_LEASE_LOST",
            5,
        ),
        (
            "provider_refused",
            dict(
                processed=0,
                budget_exhausted=True,
                quota_exhausted=True,
                quota_inferred_ids=["q0", "q1", "q2"],
            ),
            dict(enriched=0, candidates=5),
            "EXIT_PROVIDER_REFUSED",
            5,
        ),
    ],
)
def test_every_terminal_banner_states_the_rows_classified_by_inference(
    monkeypatch, capsys, ending, final, final_census, exit_name, total
):
    """DW-16: rows inferred in two different cycles, summed, on every ending."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.backfill.max_no_progress_cycles = 1
    _open_budget_window(redis, consumed=30)
    run, _slept = _refusing_provider(
        mod,
        monkeypatch,
        redis,
        # Cycle 1 enriched a row, so it is not a refusal cycle for exit 10.
        passes=[_inferring(mod, 2), _br(mod, **final)],
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(
            side_effect=[_census(enriched=0, candidates=5), _census(**final_census)]
        ),
    )
    info_spy, warn_spy = MagicMock(), MagicMock()
    monkeypatch.setattr(mod.logger, "info", info_spy)
    monkeypatch.setattr(mod.logger, "warning", warn_spy)

    rc = mod.main(["--continuous"])

    assert rc == getattr(mod, exit_name), ending
    assert run.call_count == 2
    out = capsys.readouterr().out
    assert f"{_INFERRED_BANNER}{total}" in out
    assert out.count(_INFERRED_BANNER) == 1
    # Per cycle on the cycle event, run-wide on the terminal one.
    cycles = [c[1] for c in info_spy.call_args_list if c[0] and c[0][0] == "backfill_cycle_done"]
    assert [c["quota_inferred_rows"] for c in cycles] == [2, total - 2]
    terminal = _terminal_events(info_spy) + _terminal_events(warn_spy)
    if ending in ("complete", "stalled", "breaker", "provider_refused"):
        assert [t["quota_inferred_rows"] for t in terminal] == [total]


def test_no_banner_line_when_nothing_was_inferred(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    _refusing_provider(
        mod, monkeypatch, redis, passes=[_refused(mod), _br(mod, processed=5)]
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=0, candidates=5), _census()]),
    )
    info_spy = MagicMock()
    monkeypatch.setattr(mod.logger, "info", info_spy)

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    out = capsys.readouterr().out
    assert "BACKFILL COMPLETE" in out
    assert "inferred" not in out
    assert _terminal_events(info_spy)[0]["quota_inferred_rows"] == 0


@pytest.mark.parametrize("rows", [0, 2])
def test_a_single_pass_prints_the_inferred_rows_on_their_own_line(monkeypatch, capsys, rows):
    mod = _load_module()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)
    monkeypatch.setattr(
        mod,
        "_run",
        MagicMock(
            return_value=_br(
                mod,
                processed=1,
                budget_exhausted=bool(rows),
                quota_exhausted=bool(rows),
                quota_inferred_ids=[f"p{i}" for i in range(rows)],
            )
        ),
    )

    mod.main(["--limit", "3"])

    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("Backfill pass done") for line in lines)
    inferred = [line for line in lines if _INFERRED_BANNER in line]
    if rows:
        assert len(inferred) == 1
        assert f"{_INFERRED_BANNER}{rows}" in inferred[0]
        assert not inferred[0].startswith("Backfill pass done")
    else:
        assert inferred == []


# -- end to end: real _run, run_backfill, ledger and GeminiClient -----------


class _ProviderScript:
    """A fake provider: every POST of every cycle's client pops one answer.

    An answer is an HTTP status (int) or an exception instance to raise from
    the POST. Nothing here opens a socket.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.posts = 0

    def post(self, *_args, **_kwargs):
        from unittest.mock import AsyncMock

        self.posts += 1
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        response = AsyncMock(status=answer)
        response.text.return_value = "rate limited" if answer == 429 else "upstream"
        response.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
        return AsyncMock(
            __aenter__=AsyncMock(return_value=response),
            __aexit__=AsyncMock(return_value=None),
        )


class _AdapterClock:
    """The adapter module's ``time`` name: only ``monotonic`` is fake."""

    def __init__(self):
        self.now = 10_000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        import time as real_time

        return getattr(real_time, name)


def _reset_error():
    import aiohttp

    return aiohttp.ClientConnectionError("Connection reset by peer")


def _real_continuous_run(mod, monkeypatch, redis, cfg, answers, censuses):
    """``--continuous`` with only the provider, the DB and the sleep faked.

    Real: ``_run_continuous``, ``_run``, ``_build_client``, ``run_backfill``,
    the attempt ledger and ``GeminiClient.chat_completions``. The row's
    enrichment is one chat call (``run_enrichment`` needs a database), and the
    candidate partition lets every row through.
    Returns (exit code, clients built, ledger attempts of the row seen while
    the run slept between cycles, seconds slept).
    """
    import adapters.ai.client as client_module

    cfg.backfill.tpm_limit = 16000
    clock = _AdapterClock()
    monkeypatch.setattr(client_module, "time", clock)
    script = _ProviderScript(answers)

    @asynccontextmanager
    async def _session_context(self):
        self.session = SimpleNamespace(post=script.post)
        try:
            yield self.session
        finally:
            self.session = None

    async def _no_backoff(self, _backoff):
        return 0.0

    monkeypatch.setattr(client_module.GeminiClient, "session_context", _session_context)
    monkeypatch.setattr(client_module.GeminiClient, "_sleep_backoff", _no_backoff)

    built = []
    real_build = mod._build_client

    def _build(*args, **kwargs):
        client = real_build(*args, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(mod, "_build_client", _build)

    async def _enrich(prop, *, client, cfg, stages):
        await client.chat_completions("m", [{"role": "user", "content": str(prop.id)}])

    monkeypatch.setattr(mod, "_enrich_one", _enrich)
    # The photo gate is not this story's subject, and the rows of ``_wire``
    # carry no gallery: every candidate is workable here.
    monkeypatch.setattr(mod, "partition_candidates", _all_workable)
    monkeypatch.setattr(mod, "_census", MagicMock(side_effect=censuses))

    attempts_at_sleep = []
    slept = []

    def _sleep(seconds):
        # The back-off between cycles moves the adapter's clock too. The wait
        # loop sleeps in poll-sized steps, so this runs many times per back-off.
        clock.now += seconds
        slept.append(seconds)
        attempts_at_sleep.append(mod._build_ledger(cfg, redis).attempts("p0"))

    monkeypatch.setattr(mod.time, "sleep", _sleep)

    rc = mod.main(["--continuous", "--min-interval", "0"])
    assert script.answers == [], "the run did not consume the whole script"
    return rc, built, attempts_at_sleep, slept


def _all_workable(rows, **_kw):
    return SimpleNamespace(
        workable=list(rows), blocked_no_photos=[], quarantined=[], blocked_total=0
    )


def test_a_storm_in_the_cycle_after_a_stated_refusal_charges_no_attempt(
    monkeypatch, capsys
):
    """I/O matrix "Cycle boundary (DW-14)" and "Banner (DW-16)", end to end.

    Cycle 1 ends on a stated 429. 900 s later cycle 2 builds a new client and
    meets a storm from its first call. Cycle 3 is answered.
    """
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis, n_rows=1)
    info_spy = MagicMock()
    monkeypatch.setattr(mod.logger, "info", info_spy)

    rc, built, attempts_at_sleep, slept = _real_continuous_run(
        mod,
        monkeypatch,
        redis,
        cfg,
        answers=[429] * 5 + [_reset_error() for _ in range(5)] + [200],
        censuses=[_census(enriched=0, candidates=1)] * 2 + [_census()],
    )

    assert rc == mod.EXIT_COMPLETE
    assert len(built) == 3
    assert built[1] is not built[0]
    assert built[0].quota_licence is built[1].quota_licence is built[2].quota_licence
    # The storm was read as quota on the new client, which never saw a 429.
    assert built[1].rate_limit_hits == 0
    assert built[1].transport_quota_inferences == 1
    # No attempt charged after the stated refusal, none after the storm.
    assert sum(slept) == pytest.approx(2 * 900.0)
    assert attempts_at_sleep and set(attempts_at_sleep) == {0}
    out = capsys.readouterr().out
    assert f"{_INFERRED_BANNER}1" in out
    cycles = [c[1] for c in info_spy.call_args_list if c[0] and c[0][0] == "backfill_cycle_done"]
    assert [c["quota_inferred_rows"] for c in cycles] == [0, 1, 0]
    assert _terminal_events(info_spy)[0]["quota_inferred_rows"] == 1


def test_a_storm_with_no_licence_charges_the_row_and_is_not_a_refusal_cycle(
    monkeypatch, capsys
):
    """The hold is off, so 900 s after the stated 429 nothing licenses the storm.

    The row is charged, the cycle is a stall (exit 3) and not a provider
    refusal: with a limit of two refusal cycles, counting it would end the run
    with exit 10.
    """
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis, n_rows=1)
    cfg.ai.gemini_transport_quota_hold_seconds = 0.0
    cfg.backfill.max_no_progress_cycles = 2

    rc, built, attempts_at_sleep, slept = _real_continuous_run(
        mod,
        monkeypatch,
        redis,
        cfg,
        answers=[429] * 5 + [_reset_error() for _ in range(5)],
        censuses=[_census(enriched=0, candidates=1)] * 2,
    )

    assert rc == mod.EXIT_STALLED
    assert len(built) == 2
    assert built[1].transport_quota_inferences == 0
    assert sum(slept) == pytest.approx(900.0)
    assert attempts_at_sleep and set(attempts_at_sleep) == {0}
    assert mod._build_ledger(cfg, redis).attempts("p0") == 1
    out = capsys.readouterr().out
    assert "BACKFILL STALLED" in out
    assert "inferred" not in out


@pytest.mark.parametrize(
    ("final", "wait_outcome", "exit_name"),
    [
        (dict(migration_blocked=True), "stopped", "EXIT_STOPPED"),
        (dict(migration_blocked=True), "timed_out", "EXIT_MIGRATION_ACTIVE"),
        (dict(migration_blocked=True), "lease_lost", "EXIT_LEASE_LOST"),
        (dict(migration_blocked=True, lease_lost=True), None, "EXIT_LEASE_LOST"),
    ],
)
def test_the_banners_of_a_migration_blocked_ending_state_the_inferred_rows_too(
    monkeypatch, capsys, final, wait_outcome, exit_name
):
    """These endings take no census, so they print no summary: the line is added."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    _refusing_provider(
        mod, monkeypatch, redis, passes=[_inferring(mod, 2), _br(mod, **final)]
    )
    wait = MagicMock(return_value=wait_outcome)
    monkeypatch.setattr(mod, "_wait_out_migration", wait)

    rc = mod.main(["--continuous"])

    assert rc == getattr(mod, exit_name)
    assert wait.call_count == (0 if wait_outcome is None else 1)
    out = capsys.readouterr().out
    assert out.count(f"{_INFERRED_BANNER}2") == 1


# -- review pass 1 (v0.14-s1.14) ---------------------------------------------


def test_a_row_inferred_in_two_cycles_is_one_row_on_the_banner(monkeypatch, capsys):
    """The banner counts rows. A rolled-back row is a candidate again, so the
    same property can be classified by inference in several cycles of one run:
    it is still one row."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    again = _br(
        mod,
        processed=1,
        budget_exhausted=True,
        quota_exhausted=True,
        quota_inferred_ids=["p1", "p7"],
    )
    _refusing_provider(
        mod, monkeypatch, redis, passes=[_inferring(mod, 2), again, _br(mod, processed=1)]
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=0, candidates=5)] * 2 + [_census()]),
    )
    info_spy = MagicMock()
    monkeypatch.setattr(mod.logger, "info", info_spy)

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    out = capsys.readouterr().out
    # p0, p1 in cycle 1; p1 again and p7 in cycle 2.
    assert out.count(f"{_INFERRED_BANNER}3 row(s)") == 1
    cycles = [c[1] for c in info_spy.call_args_list if c[0] and c[0][0] == "backfill_cycle_done"]
    assert [c["quota_inferred_rows"] for c in cycles] == [2, 2, 0]
    assert _terminal_events(info_spy)[0]["quota_inferred_rows"] == 3


def test_a_lease_lost_in_the_quota_backoff_states_the_inferred_rows(monkeypatch, capsys):
    """The wait a cycle enters right after an inferred refusal. A lease lost
    there printed the one banner of the run without the line."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    run, _slept = _refusing_provider(mod, monkeypatch, redis, passes=[_inferring(mod, 2)])
    monkeypatch.setattr(mod, "_sleep_for_reset", lambda wait, **kw: "lease_lost")

    assert mod.main(["--continuous"]) == mod.EXIT_LEASE_LOST

    assert run.call_count == 1
    assert capsys.readouterr().out.count(f"{_INFERRED_BANNER}2 row(s)") == 1


def test_a_lease_lost_ending_without_a_census_states_the_inferred_rows(monkeypatch, capsys):
    """Redis down for the lease TTL: no census, a banner built by hand."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    _refusing_provider(
        mod,
        monkeypatch,
        redis,
        passes=[_inferring(mod, 2), _br(mod, processed=0, lease_lost=True)],
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(
            side_effect=[_census(enriched=0, candidates=5), ConnectionError("redis is down")]
        ),
    )

    assert mod.main(["--continuous"]) == mod.EXIT_LEASE_LOST

    out = capsys.readouterr().out
    assert out.count(f"{_INFERRED_BANNER}2 row(s)") == 1
    assert "enrichable" not in out  # the summary a census would have printed


def test_the_hold_warning_is_silent_when_the_inference_is_off(monkeypatch):
    """A zero window turns every basis off: the hold is inert, nothing to order."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    cfg.ai.gemini_transport_quota_window_seconds = 0.0
    cfg.ai.gemini_transport_quota_hold_seconds = 600.0
    monkeypatch.setattr(mod, "_run", MagicMock(return_value=_br(mod, processed=5)))
    monkeypatch.setattr(mod, "_census", MagicMock(return_value=_census()))
    warn_spy = MagicMock()
    monkeypatch.setattr(mod.logger, "warning", warn_spy)

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    assert [
        c for c in warn_spy.call_args_list
        if c[0] and c[0][0] == "backfill_quota_hold_not_longer_than_backoff"
    ] == []


@pytest.mark.parametrize("inferred", [True, False])
def test_the_wait_line_says_when_the_refusal_was_inferred(monkeypatch, capsys, inferred):
    """"Provider refused on quota" is not what happened when the provider said
    nothing: the line an operator reads while the run sleeps says so."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    first = (
        _inferring(mod, 1)
        if inferred
        else _br(mod, processed=1, budget_exhausted=True, quota_exhausted=True)
    )
    _refusing_provider(mod, monkeypatch, redis, passes=[first, _br(mod, processed=1)])
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=0, candidates=5), _census()]),
    )
    monkeypatch.setattr(mod, "_sleep_for_reset", lambda wait, **kw: "elapsed")

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    waits = [line for line in capsys.readouterr().out.splitlines() if "sleeping" in line]
    assert len(waits) == 1
    assert ("inferred from transport failures" in waits[0]) is inferred
    assert "Provider refused on quota" in waits[0]


def test_the_long_wait_line_says_when_the_refusal_was_inferred(monkeypatch, capsys):
    """The fourth refused pass in a row is where a silent provider is parked
    for the daily window (follow-up review of v0.14-s1.14): that line is the
    one an operator reads for hours, and it has to say the refusals were
    inferred, on their last attempt (an ``in-call`` row did see a 429)."""
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    _open_budget_window(redis, consumed=30)
    passes = [_inferring(mod, 1, processed=0) for _ in range(mod._MAX_QUOTA_BACKOFF_CYCLES)]
    _refusing_provider(mod, monkeypatch, redis, passes=passes + [_br(mod, processed=1)])
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(
            side_effect=[_census(enriched=0, candidates=5)] * len(passes) + [_census()]
        ),
    )
    monkeypatch.setattr(mod, "_sleep_for_reset", lambda wait, **kw: "elapsed")

    assert mod.main(["--continuous"]) == mod.EXIT_COMPLETE

    waits = [line for line in capsys.readouterr().out.splitlines() if "sleeping" in line]
    assert len(waits) == len(passes)
    clause = "(inferred from transport failures on 1 row(s), no 429 on their last attempt)"
    assert all(clause in line for line in waits)
    assert "Provider has refused on quota" in waits[-1]
    assert "Waiting out the RPD window" in waits[-1]


def test_the_budget_spent_wait_line_says_when_the_refusal_was_inferred(monkeypatch, capsys):
    mod = _load_module()
    redis = _FakeRedis()
    _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis)
    # --daily-budget 30 with 30 already consumed: no headroom for another row.
    _open_budget_window(redis, consumed=30)
    _refusing_provider(
        mod, monkeypatch, redis, passes=[_inferring(mod, 2), _br(mod, processed=1)]
    )
    monkeypatch.setattr(
        mod,
        "_census",
        MagicMock(side_effect=[_census(enriched=0, candidates=5), _census()]),
    )
    monkeypatch.setattr(mod, "_sleep_for_reset", lambda wait, **kw: "elapsed")

    assert mod.main(["--continuous", "--daily-budget", "30"]) == mod.EXIT_COMPLETE

    waits = [line for line in capsys.readouterr().out.splitlines() if "sleeping" in line]
    assert len(waits) == 1
    assert "inferred from transport failures on 2 row(s)" in waits[0]
    assert "local daily budget is spent" in waits[0]


def test_the_exit_ten_reason_on_the_card_names_the_inferred_reading(monkeypatch):
    """Cycles refused by inference feed exit 10, and the status record carries
    no row count: its one sentence must not send the operator to the quota
    page alone when the evidence may be a route that died after a 429."""
    mod = _load_module()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING)

    reason = mod._exit_reason(mod.EXIT_PROVIDER_REFUSED, cfg)

    assert "inferred from transport failures" in reason
    assert "network route" in reason
    assert "max_no_progress_cycles" in reason
    # ``last_run`` truncates the reason; the sentence has to fit whole.
    from core.backfill_runner import _LAST_RUN_REASON_MAX_CHARS

    assert len(reason) <= _LAST_RUN_REASON_MAX_CHARS


def test_a_throttle_that_turns_silent_mid_call_charges_no_attempt(monkeypatch, capsys):
    """I/O matrix "Throttle turns silent mid-call (DW-12)", end to end: the
    adapter's own error reaches the real runner and the real ledger."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis, n_rows=1)

    rc, built, attempts_at_sleep, _slept = _real_continuous_run(
        mod,
        monkeypatch,
        redis,
        cfg,
        answers=[429] + [_reset_error() for _ in range(4)] + [200],
        censuses=[_census(enriched=0, candidates=1), _census()],
    )

    assert rc == mod.EXIT_COMPLETE
    assert built[0].rate_limit_hits == 1
    assert built[0].transport_quota_inferences == 1
    assert "in-call" in built[0].last_error
    assert attempts_at_sleep and set(attempts_at_sleep) == {0}
    assert f"{_INFERRED_BANNER}1 row(s)" in capsys.readouterr().out


def test_cycles_refused_by_inference_count_towards_the_no_progress_exit(
    monkeypatch, capsys
):
    """Story 1.13's rule, fed by a real inferred refusal: a stated refusal in
    cycle 1, a storm read as quota in cycle 2, limit of two, exit 10. The
    mirror of the hold-off test above, where the same storm is a stall."""
    mod = _load_module()
    redis = _FakeRedis()
    cfg = _wire(mod, monkeypatch, api_key="k", routing=_CLOUD_ROUTING, redis=redis, n_rows=1)
    cfg.backfill.max_no_progress_cycles = 2

    rc, built, attempts_at_sleep, slept = _real_continuous_run(
        mod,
        monkeypatch,
        redis,
        cfg,
        answers=[429] * 5 + [_reset_error() for _ in range(5)],
        censuses=[_census(enriched=0, candidates=1)] * 2,
    )

    assert rc == mod.EXIT_PROVIDER_REFUSED
    assert built[1].transport_quota_inferences == 1
    assert sum(slept) == pytest.approx(900.0)
    assert mod._build_ledger(cfg, redis).attempts("p0") == 0
    assert f"{_INFERRED_BANNER}1 row(s)" in capsys.readouterr().out
