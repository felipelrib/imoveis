"""Unit tests for ``GET /admin/enrichment/coverage`` (v0.13-s1.6, FR-29).

Thin-glue tier: the arithmetic is covered in ``test_enrichment_coverage.py`` and
the SQL statements themselves are exercised by the integration/contract suites.
What is asserted here is the wiring — the adapter's measurements reach the
response, the *only* thing Redis is allowed to decide is ``backfill.active``,
and a database failure comes back as a generic 500 rather than a leaked
connection string.

The last class covers the one piece of real branching the adapter does *outside*
SQL: turning a snapshot pair into a rate. It lives here rather than in the core
tests because it is adapter code, and it matters because that is where "fewer
than two points is not a rate" is decided.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from adapters.db.enrichment_coverage_queries import CoverageInputs, _throughput_per_day
from core.backfill_runner import BackfillLease
from core.enrichment import EnrichmentTaskClass

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Unit runs have no slowapi Redis; the decorator then calls straight through."""
    from infra.limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


class FakeRedis:
    """Just enough Redis for the lease read the route makes."""

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

    def hdel(self, key, *fields):
        for f in fields:
            self.hashes.setdefault(key, {}).pop(f, None)


def _cfg():
    return SimpleNamespace(
        backfill=SimpleNamespace(
            redis_prefix="t",
            daily_request_budget=14000,
            requests_per_property=3,
            rpm_limit=30,
            concurrency=1,
            tpm_limit=16000,
            max_attempts=3,
            lease_ttl_seconds=900,
        )
    )


def _session_factory():
    """``SessionLocal()`` stand-in usable as a context manager."""
    session = MagicMock(name="session")
    factory = MagicMock(name="SessionLocal")
    factory.return_value.__enter__.return_value = session
    factory.return_value.__exit__.return_value = False
    return factory


def _inputs(**overrides) -> CoverageInputs:
    kwargs = {
        "total_properties": 2000,
        "enriched_by_task_class": {
            "visual": 1234,
            "sentiment": 1800,
            "deal_verdict": 1200,
            "valuation": 1900,
            "embedding": 1950,
        },
        "remaining": 766,
        "throughput_per_day": 4600.0,
    }
    kwargs.update(overrides)
    return CoverageInputs(**kwargs)


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_coverage_reports_every_signal_measured_from_the_database(
    _session, mock_inputs, mock_cfg, mock_redis
):
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()
    mock_inputs.return_value = _inputs()

    body = enrichment_coverage(request=None)

    assert [s.task_class for s in body.signals] == [tc.value for tc in EnrichmentTaskClass]
    by_class = {s.task_class: s for s in body.signals}
    assert by_class["visual"].enriched == 1234
    assert by_class["visual"].total == 2000
    assert by_class["visual"].fraction == pytest.approx(0.617)
    assert body.total_properties == 2000
    assert body.minimum_fraction == pytest.approx(0.6)
    assert body.backfill.remaining == 766
    # No lease held, so nothing forward-looking is stated.
    assert body.backfill.active is False
    assert body.backfill.throughput_per_day is None
    assert body.backfill.eta_days is None
    assert body.backfill.projected_completion_date is None


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_a_held_lease_is_the_only_thing_redis_decides(
    _session, mock_inputs, mock_cfg, mock_redis
):
    """FR-29: Redis answers "is a run live"; every number stays DB-derived."""
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    # A checkpoint claiming far more progress than the DB shows must not leak in.
    redis.kv["t:checkpoint"] = json.dumps({"processed_total": 999999})
    mock_inputs.return_value = _inputs()

    body = enrichment_coverage(request=None)

    assert body.backfill.active is True
    assert body.backfill.remaining == 766  # the DB's figure, not the checkpoint's
    assert body.backfill.throughput_per_day == pytest.approx(4600.0)
    assert body.backfill.eta_days == pytest.approx(0.17, abs=0.005)
    # Under a day of work left, so the projection lands after today. Compared
    # against *UTC* today, which is what the route projects from: a local
    # ``date.today()`` is a different day for most of the morning east of
    # Greenwich, and this assertion would flip with the runner's timezone.
    utc_today = datetime.now(timezone.utc).date()
    assert body.backfill.projected_completion_date > utc_today.isoformat()
    assert "999999" not in json.dumps(body.model_dump())


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_the_lease_acquisition_clamps_the_throughput_window(
    _session, mock_inputs, mock_cfg, mock_redis
):
    """The one number Redis may influence is *which snapshots* the rate reads.

    Without the clamp a run that started minutes ago is averaged over 24h of
    mostly-idle snapshots and the ETA reads wildly high.
    """
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    mock_inputs.return_value = _inputs()

    enrichment_coverage(request=None)

    acquired_at = redis.hashes["t:lease:meta"]["acquired_at"]
    assert mock_inputs.call_args.kwargs["run_started_at"] == datetime.fromisoformat(
        acquired_at
    )


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_no_run_leaves_the_throughput_window_unclamped(
    _session, mock_inputs, mock_cfg, mock_redis
):
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()
    mock_inputs.return_value = _inputs()

    enrichment_coverage(request=None)

    assert mock_inputs.call_args.kwargs["run_started_at"] is None


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_an_unparseable_acquisition_stamp_degrades_to_no_clamp(
    _session, mock_inputs, mock_cfg, mock_redis
):
    """The meta hash is advisory decoration on the lease — it may be junk.

    A bad stamp must cost the clamp, never the response: the run is still live
    and every other figure is still measurable.
    """
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    redis = FakeRedis()
    mock_redis.return_value = redis
    assert BackfillLease(redis, prefix="t", owner="host:4711").acquire()
    redis.hashes["t:lease:meta"]["acquired_at"] = "yesterday-ish"
    mock_inputs.return_value = _inputs()

    body = enrichment_coverage(request=None)

    assert body.backfill.active is True
    assert mock_inputs.call_args.kwargs["run_started_at"] is None


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_an_empty_database_reports_absence_not_zero(
    _session, mock_inputs, mock_cfg, mock_redis
):
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()
    mock_inputs.return_value = _inputs(
        total_properties=0, enriched_by_task_class={}, remaining=0, throughput_per_day=None
    )

    body = enrichment_coverage(request=None)

    assert all(s.fraction is None for s in body.signals)
    assert body.minimum_fraction is None
    assert body.total_properties == 0


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_a_database_failure_maps_to_a_generic_500(
    _session, mock_inputs, mock_cfg, mock_redis
):
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()
    mock_inputs.side_effect = RuntimeError(
        'relation "metrics_scoring" does not exist: postgresql://user:pw@host/db'
    )

    with pytest.raises(HTTPException) as exc_info:
        enrichment_coverage(request=None)

    assert exc_info.value.status_code == 500
    detail = str(exc_info.value.detail)
    assert "postgresql://" not in detail
    assert "metrics_scoring" not in detail


@patch(
    "api.admin.EnrichmentCoverageResponse.model_validate",
    side_effect=RuntimeError("1 validation error: signals.0.fraction le=1.0"),
)
@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_a_response_model_mismatch_is_guarded_like_any_other_failure(
    _session, mock_inputs, mock_cfg, mock_redis, _validate
):
    """BIN-56's failure class: serialisation raises *after* the queries.

    Left outside the guard it escapes as an unlogged 500 carrying the field
    path, instead of the generic, server-logged error every other failure on
    this route produces.
    """
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()
    mock_inputs.return_value = _inputs()

    with pytest.raises(HTTPException) as exc_info:
        enrichment_coverage(request=None)

    assert exc_info.value.status_code == 500
    assert "validation error" not in str(exc_info.value.detail)


@patch("api.admin.get_redis", side_effect=RuntimeError("redis://user:pw@host down"))
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_a_redis_failure_maps_to_a_generic_500(
    _session, mock_inputs, mock_cfg, _redis
):
    """Liveness is unknowable, so the route refuses rather than claiming idle."""
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    mock_inputs.return_value = _inputs()

    with pytest.raises(HTTPException) as exc_info:
        enrichment_coverage(request=None)

    assert exc_info.value.status_code == 500
    assert "redis://" not in str(exc_info.value.detail)


@patch("api.admin.get_redis")
@patch("api.admin.get_config")
@patch("api.admin.fetch_coverage_inputs")
@patch("api.admin.SessionLocal", new_callable=_session_factory)
def test_the_session_is_opened_and_closed_around_the_queries(
    session_factory, mock_inputs, mock_cfg, mock_redis
):
    from api.admin import enrichment_coverage

    mock_cfg.return_value = _cfg()
    mock_redis.return_value = FakeRedis()
    mock_inputs.return_value = _inputs()

    enrichment_coverage(request=None)

    session_factory.assert_called_once_with()
    session_factory.return_value.__exit__.assert_called_once()
    assert mock_inputs.call_args[0][0] is session_factory.return_value.__enter__.return_value


# ---------------------------------------------------------------------------
# adapters.db.enrichment_coverage_queries._throughput_per_day
#
# The snapshot pair -> properties-per-day conversion. Every branch here exists
# to refuse a rate rather than invent one, so each refusal gets a test.
# ---------------------------------------------------------------------------


def _snapshot_window(**values):
    """A session whose single query returns one aggregate row of the window."""
    row = SimpleNamespace(_mapping=values)
    session = MagicMock(name="session")
    session.execute.return_value.one.return_value = row
    return session


def _window(*, points, hours_apart, first, last):
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    return {
        "points": points,
        "first_ts": now - timedelta(hours=hours_apart),
        "first_enriched": first,
        "last_ts": now,
        "last_enriched": last,
    }


class TestThroughputPerDay:
    def test_a_full_day_of_progress_is_the_delta_itself(self):
        session = _snapshot_window(
            **_window(points=48, hours_apart=24, first=1000, last=5600)
        )
        assert _throughput_per_day(session) == pytest.approx(4600.0)

    def test_a_partial_window_is_extrapolated_to_a_daily_rate(self):
        session = _snapshot_window(
            **_window(points=12, hours_apart=6, first=1000, last=2150)
        )
        assert _throughput_per_day(session) == pytest.approx(4600.0)

    def test_a_single_point_is_not_a_rate(self):
        session = _snapshot_window(
            **_window(points=1, hours_apart=0, first=1000, last=1000)
        )
        assert _throughput_per_day(session) is None

    def test_an_empty_window_is_not_a_rate(self):
        session = _snapshot_window(
            points=0,
            first_ts=None,
            first_enriched=None,
            last_ts=None,
            last_enriched=None,
        )
        assert _throughput_per_day(session) is None

    @pytest.mark.parametrize("last", [1000, 400])
    def test_a_flat_or_shrinking_count_is_not_a_rate(self, last):
        """A re-scored corpus can shrink; 0 or negative progress is not a rate."""
        session = _snapshot_window(
            **_window(points=48, hours_apart=24, first=1000, last=last)
        )
        assert _throughput_per_day(session) is None

    def test_two_points_sharing_a_timestamp_are_not_a_rate(self):
        """A zero-length window would divide by zero and read as infinite speed."""
        session = _snapshot_window(
            **_window(points=2, hours_apart=0, first=1000, last=1200)
        )
        assert _throughput_per_day(session) is None

    def _bound_params(self, session):
        statement = session.execute.call_args[0][0]
        return statement.compile().params

    def test_without_a_run_the_window_is_the_plain_lookback(self):
        session = _snapshot_window(
            **_window(points=48, hours_apart=24, first=1000, last=5600)
        )

        _throughput_per_day(session)

        params = self._bound_params(session)
        assert params["hours"] == 24
        # NULL, so ``GREATEST`` leaves ``now() - 24h`` as the window start.
        assert params["since"] is None

    def test_a_live_run_clamps_the_window_to_its_lease_acquisition(self):
        """Snapshots are written every 30s whether or not a backfill runs.

        A run that started 30 minutes ago has its progress divided across 23.5
        idle hours unless the window start is clamped, which understates the
        rate roughly fiftyfold and overstates the ETA by the same factor.
        """
        since = datetime(2026, 8, 11, 11, 30, tzinfo=timezone.utc)
        session = _snapshot_window(
            **_window(points=60, hours_apart=0.5, first=1000, last=1100)
        )

        rate = _throughput_per_day(session, since)

        assert self._bound_params(session)["since"] == since
        # 100 rows in half an hour is 4800/day — not 100/day.
        assert rate == pytest.approx(4800.0)

    def test_a_clamped_window_with_one_point_still_refuses_a_rate(self):
        """The clamp narrows the window; it never lowers the two-point bar."""
        since = datetime(2026, 8, 11, 11, 55, tzinfo=timezone.utc)
        session = _snapshot_window(
            **_window(points=1, hours_apart=0, first=1000, last=1000)
        )

        assert _throughput_per_day(session, since) is None


class TestSignalAliasCoverage:
    """The SQL's column aliases *are* the ``EnrichmentTaskClass`` vocabulary.

    ``_count_enriched_by_task_class`` looks every enum member up in the result
    mapping by name, so a member added to the enum without a matching aggregate
    is a ``KeyError`` on a live request. Defaulting the lookup to ``0`` would be
    worse than the crash — it would report the new signal as 0% covered and, via
    ``minimum_fraction``, pin the Painel's headline figure to zero — so the gap
    is caught here instead.
    """

    def test_every_task_class_has_a_column_in_the_signal_query(self):
        import re

        from adapters.db.enrichment_coverage_queries import _SIGNAL_COUNTS_SQL

        aliases = set(re.findall(r"\bAS\s+([a-z_]+)", _SIGNAL_COUNTS_SQL))
        assert aliases == {tc.value for tc in EnrichmentTaskClass}

    def test_the_mapping_reads_every_task_class_out_of_the_row(self):
        from adapters.db.enrichment_coverage_queries import (
            _count_enriched_by_task_class,
        )

        row = SimpleNamespace(
            _mapping={tc.value: 7 for tc in EnrichmentTaskClass}
        )
        session = MagicMock(name="session")
        session.execute.return_value.one.return_value = row

        counts = _count_enriched_by_task_class(session)

        assert counts == {tc.value: 7 for tc in EnrichmentTaskClass}
