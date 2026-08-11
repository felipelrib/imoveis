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
    cfg.backfill.lease_ttl_seconds = 900
    cfg.backfill.control_poll_seconds = 2.0
    cfg.backfill.quota_backoff_seconds = 900
    cfg.backfill.migration_wait_seconds = 1800
    cfg.ai.gemini_api_key = api_key
    cfg.ai.backend = "ollama"
    cfg.ai.gemma_model = "gemma-4-31b-it"
    cfg.ai.gemini_model = "gemini-2.5-flash"
    # Real float: ``float(MagicMock())`` is ``1.0``, so leaving this a mock
    # would silently build every client with a 1-second DW-7 window instead of
    # raising — which is why the value is asserted, not just set. Deliberately
    # NOT the client's own 300.0 default, or a dropped kwarg would still assert.
    cfg.ai.gemini_transport_quota_window_seconds = 120.0
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
    monkeypatch.setattr(mod, "_build_client", lambda cfg, scope=None: client)
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
    monkeypatch.setattr(mod, "_build_client", lambda cfg, scope=None: client)
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

    mod._sleep_for_reset(3600.0, cfg=cfg, control=None, lease=lease)

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
    assert mod._sleep_for_reset(3600.0, cfg=cfg, lease=lost) == "lease_lost"
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
