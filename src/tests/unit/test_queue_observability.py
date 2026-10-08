"""Every queue is reported (Story 1.18).

``GET /system/pipeline``, the metrics snapshot and the queue monitor name all
three routed queues, and ``GET /system/status`` says when one has no consumer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from adapters.metrics import pipeline_snapshots as snaps_mod
from api import system as system_mod
from api.main import app
from infra.config import get_config

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _anonymous_access(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_KEY", "")
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _redis_with_lengths(**lengths) -> MagicMock:
    redis = MagicMock()
    redis.llen.side_effect = lambda queue: lengths.get(queue, 0)
    redis.lrange.return_value = []
    redis.get.return_value = None
    redis.exists.return_value = 0
    return redis


# ---------------------------------------------------------------------------
# Queue lengths
# ---------------------------------------------------------------------------


def test_pipeline_queue_lengths_cover_the_three_routed_queues():
    redis = _redis_with_lengths(scrapers=3, ai=40, periodic=2)
    assert system_mod._pipeline_queue_lengths(redis) == {"scrapers": 3, "ai": 40, "periodic": 2}


def test_system_pipeline_reports_the_periodic_queue():
    redis = _redis_with_lengths(scrapers=1, ai=5, periodic=7)
    client = TestClient(app, raise_server_exceptions=False)
    with (
        patch("api.system.get_redis", return_value=redis),
        patch("api.system._pipeline_proxy_summary", return_value={"health": "direct"}),
    ):
        response = client.get("/system/pipeline")
    assert response.status_code == 200, response.text
    assert response.json()["queues"] == {"scrapers": 1, "ai": 5, "periodic": 7}


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_fields_carry_the_periodic_queue():
    redis = _redis_with_lengths(scrapers=4, ai=9, periodic=6)
    with (
        patch("infra.redis_client.get_redis", return_value=redis),
        patch("api.system._check_db_and_counts", return_value=({"status": "ok"}, 100, 60)),
    ):
        fields = snaps_mod.collect_snapshot_fields()
    assert fields["scraper_queue"] == 4
    assert fields["ai_queue"] == 9
    assert fields["periodic_queue"] == 6


def test_snapshot_result_and_log_include_periodic_queue_and_the_row_is_unchanged():
    fields = {
        "ts": datetime.now(timezone.utc),
        "total_properties": 100,
        "enriched_properties": 60,
        "scraper_queue": 4,
        "ai_queue": 9,
        "periodic_queue": 6,
        "throughput_per_min": 1.5,
    }
    session = MagicMock()
    with (
        patch.object(snaps_mod, "collect_snapshot_fields", return_value=fields),
        patch.object(snaps_mod, "prune_old_snapshots", return_value=2),
        patch.object(snaps_mod, "logger") as log,
    ):
        result = snaps_mod.snapshot_and_prune(session, retention_days=7)

    assert result == {
        "written": 1,
        "pruned": 2,
        "total_properties": 100,
        "enriched_properties": 60,
        "scraper_queue": 4,
        "ai_queue": 9,
        "throughput_per_min": 1.5,
        "periodic_queue": 6,
    }
    assert log.info.call_args.args[0] == "pipeline_metric_snapshot_written"
    assert log.info.call_args.kwargs["periodic_queue"] == 6
    assert log.info.call_args.kwargs["ai_queue"] == 9
    # The stored row has the same columns as before: no third queue column.
    row = session.add.call_args.args[0]
    assert not hasattr(row, "periodic_queue")
    assert (row.scraper_queue, row.ai_queue) == (4, 9)
    columns = {column.name for column in type(row).__table__.columns}
    assert columns == {
        "id", "ts", "total_properties", "enriched_properties",
        "scraper_queue", "ai_queue", "throughput_per_min",
    }


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


def _run_monitor(redis):
    from adapters.queue import tasks as tasks_mod

    with (
        patch("infra.redis_client.get_redis", return_value=redis),
        patch.object(tasks_mod, "logger") as log,
    ):
        tasks_mod.monitor_queues.run()
    return log


def _events(mock_method) -> list:
    return [call.args[0] for call in mock_method.call_args_list]


def test_monitor_logs_the_three_queue_lengths():
    log = _run_monitor(_redis_with_lengths(scrapers=3, ai=10, periodic=2))
    call = next(c for c in log.info.call_args_list if c.args[0] == "queue_monitor")
    assert call.kwargs == {"ai_queue": 10, "scrapers_queue": 3, "periodic_queue": 2}
    assert "queue_monitor_periodic_backlog" not in _events(log.warning)


def test_monitor_warns_on_a_periodic_backlog_above_100():
    log = _run_monitor(_redis_with_lengths(periodic=101))
    call = next(c for c in log.warning.call_args_list if c.args[0] == "queue_monitor_periodic_backlog")
    assert call.kwargs == {"periodic_queue": 101, "threshold": 100}


def test_monitor_does_not_warn_at_exactly_100():
    log = _run_monitor(_redis_with_lengths(periodic=100))
    assert "queue_monitor_periodic_backlog" not in _events(log.warning)


def test_monitor_pause_logic_still_follows_the_ai_queue_only():
    from adapters.queue.tasks import REDIS_KEY_SCRAPERS_PAUSED

    # A deep ai queue pauses scrapers; deep scrapers/periodic queues do not.
    redis = _redis_with_lengths(ai=51)
    _run_monitor(redis)
    redis.set.assert_called_once_with(REDIS_KEY_SCRAPERS_PAUSED, "1")

    redis = _redis_with_lengths(ai=50, scrapers=10_000, periodic=10_000)
    _run_monitor(redis)
    redis.set.assert_not_called()

    redis = _redis_with_lengths(ai=0, periodic=10_000)
    redis.exists.return_value = 1
    _run_monitor(redis)
    redis.delete.assert_called_once_with(REDIS_KEY_SCRAPERS_PAUSED)


# ---------------------------------------------------------------------------
# Unconsumed queue at runtime
# ---------------------------------------------------------------------------


def _check_workers_with(active_queues):
    celery_app = MagicMock()
    inspector = celery_app.control.inspect.return_value
    if isinstance(active_queues, list):
        inspector.active_queues.side_effect = active_queues
    else:
        inspector.active_queues.return_value = active_queues
    with patch("adapters.queue.celery_app.make_celery", return_value=celery_app):
        result = system_mod._check_workers()
    return result, inspector


def _node(*queues):
    return [{"name": queue, "routing_key": queue} for queue in queues]


def test_check_workers_is_ok_when_every_routed_queue_is_consumed():
    result, inspector = _check_workers_with(
        {
            "celery@scraper": _node("scrapers", "celery"),
            "celery@ai": _node("ai"),
            "celery@periodic": _node("periodic"),
        }
    )
    assert result == {
        "status": "ok",
        "nodes": ["celery@scraper", "celery@ai", "celery@periodic"],
        "unconsumed_queues": [],
    }
    # One round trip: the ping is gone, active_queues answers both questions.
    inspector.active_queues.assert_called_once_with()
    inspector.ping.assert_not_called()


def test_check_workers_names_a_routed_queue_nobody_consumes():
    """The pre-deploy state: the periodic worker does not exist yet."""
    result, _inspector = _check_workers_with(
        {"celery@scraper": _node("scrapers", "celery"), "celery@ai": _node("ai")}
    )
    assert result["status"] == "error"
    assert result["unconsumed_queues"] == ["periodic"]
    assert "periodic" in result["detail"]
    assert result["nodes"] == ["celery@scraper", "celery@ai"]
    assert _inspector.active_queues.call_count == 2  # asked once more before the error


def test_check_workers_lists_every_unconsumed_queue():
    result, _inspector = _check_workers_with({"celery@periodic": _node("periodic")})
    assert result["status"] == "error"
    assert result["unconsumed_queues"] == ["scrapers", "ai"]
    assert "scrapers" in result["detail"] and "ai" in result["detail"]


@pytest.mark.parametrize("reply", [None, {}])
def test_check_workers_keeps_the_no_workers_message(reply):
    result, _inspector = _check_workers_with(reply)
    assert result == {"status": "error", "detail": "No workers responding"}


def test_check_workers_tolerates_a_node_with_no_queue_list():
    result, _inspector = _check_workers_with(
        {"celery@odd": None, "celery@all": _node("scrapers", "ai", "periodic")}
    )
    assert result["status"] == "ok"


def test_check_workers_reports_an_inspect_failure():
    celery_app = MagicMock()
    celery_app.control.inspect.side_effect = ConnectionError("broker down")
    with patch("adapters.queue.celery_app.make_celery", return_value=celery_app):
        result = system_mod._check_workers()
    assert result == {"status": "error", "detail": "broker down"}


def test_system_status_serves_the_unconsumed_queues():
    client = TestClient(app, raise_server_exceptions=False)
    redis = MagicMock()
    redis.exists.return_value = 0
    celery_app = MagicMock()
    celery_app.control.inspect.return_value.active_queues.return_value = {
        "celery@scraper": _node("scrapers", "celery"),
        "celery@ai": _node("ai"),
    }
    with (
        patch("api.system.get_redis", return_value=redis),
        patch("api.system._check_db_and_counts", return_value=({"status": "ok"}, 1, 1)),
        patch("api.system._check_redis", return_value={"status": "ok"}),
        patch("api.system._check_ollama", new_callable=AsyncMock, return_value={"status": "ok", "models": []}),
        patch("adapters.queue.celery_app.make_celery", return_value=celery_app),
    ):
        response = client.get("/system/status")
    assert response.status_code == 200, response.text
    workers = response.json()["workers"]
    assert workers["status"] == "error"
    assert workers["unconsumed_queues"] == ["periodic"]
    assert "periodic" in workers["detail"]


def test_check_workers_asks_once_more_before_reporting_an_unconsumed_queue():
    """``active_queues`` waits one second: a late reply is not a missing consumer."""
    first = {"celery@scraper": _node("scrapers", "celery"), "celery@ai": _node("ai")}
    second = {"celery@periodic": _node("periodic"), "celery@ai": _node("ai")}
    result, inspector = _check_workers_with([first, second])
    assert result == {
        "status": "ok",
        "nodes": ["celery@scraper", "celery@ai", "celery@periodic"],
        "unconsumed_queues": [],
    }
    assert inspector.active_queues.call_count == 2


def test_check_workers_does_not_ask_again_when_nobody_answered():
    result, inspector = _check_workers_with([None, {"celery@all": _node("scrapers", "ai", "periodic")}])
    assert result == {"status": "error", "detail": "No workers responding"}
    assert inspector.active_queues.call_count == 1


def test_check_workers_survives_a_second_round_with_no_reply():
    first = {"celery@scraper": _node("scrapers", "celery")}
    result, _inspector = _check_workers_with([first, None])
    assert result["status"] == "error"
    assert result["unconsumed_queues"] == ["ai", "periodic"]


# ---------------------------------------------------------------------------
# Admin triggers publish to the periodic queue
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(monkeypatch: pytest.MonkeyPatch):
    from infra.config import AuthConfig

    auth = AuthConfig(
        api_key="test-valid-key",
        jwt_secret="test-jwt-secret",
        principal_id="default",
        admin_user="admin",
        admin_pass="admin",
    )
    cfg = MagicMock()
    cfg.auth = auth
    cfg.scraping.availability_recheck.enabled = True
    cfg.scraping.availability_recheck.batch_size = 50
    cfg.neighbourhood_access.enabled = True
    monkeypatch.setattr("api.auth.get_config", lambda: cfg)
    monkeypatch.setattr("infra.config.get_config", lambda: cfg)
    monkeypatch.setattr("api.admin.get_config", lambda: cfg)
    return TestClient(app, raise_server_exceptions=False), auth


def test_admin_availability_recheck_publishes_to_the_periodic_queue(admin_client):
    client, auth = admin_client
    with (
        patch(
            "adapters.queue.tasks.recheck_listing_availability.apply_async",
            return_value=MagicMock(id="task-recheck-1"),
        ) as mock_apply,
        patch("api.admin.log_audit_action"),
    ):
        response = client.post(
            "/admin/availability/recheck?batch_size=7", headers={"X-API-Key": auth.api_key}
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"queued": True, "task_id": "task-recheck-1", "batch_size": 7}
    mock_apply.assert_called_once_with(kwargs={"batch_size": 7}, queue="periodic")


def test_admin_neighbourhood_access_refresh_publishes_to_the_periodic_queue(admin_client):
    client, auth = admin_client
    with (
        patch(
            "adapters.queue.tasks.refresh_neighbourhood_access_task.apply_async",
            return_value=MagicMock(id="task-access-1"),
        ) as mock_apply,
        patch("api.admin.log_audit_action"),
    ):
        response = client.post(
            "/admin/neighbourhoods/access/refresh", headers={"X-API-Key": auth.api_key}
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"queued": True, "task_id": "task-access-1"}
    mock_apply.assert_called_once_with(queue="periodic")
