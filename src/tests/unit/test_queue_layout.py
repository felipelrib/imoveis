"""The three-queue Celery layout (Story 1.18).

``scrapers`` carries scrapes (and the operator-triggered cost backfill), ``ai``
carries GPU work, ``periodic`` carries everything else on its own worker. These
tests fail when a periodic task is routed to the queue of ``scrape_listings``
again, when a routed queue has no consumer in ``docker-compose.yml``, or when
the expiry rule of a beat entry changes.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from adapters.queue.celery_app import (
    QUEUE_AI,
    QUEUE_PERIODIC,
    QUEUE_SCRAPERS,
    ROUTED_QUEUES,
    SCRAPE_TASK_NAME,
    build_beat_schedule,
    make_celery,
)

pytestmark = pytest.mark.unit

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"

_SCRAPERS_TASKS = {SCRAPE_TASK_NAME, "tasks.backfill_listing_costs"}
_AI_TASKS = {"tasks.ai_enrich", "tasks.embed_property"}

# Idempotent: the next run covers a discarded one.
_EXPIRING_ENTRIES = {
    "monitor-queues",
    "snapshot-pipeline-metrics",
    "evaluate-watchlist-alerts",
    "match-saved-search-new-matches",
    "recheck-listing-availability",
    "refresh-neighbourhood-amenities",
    "refresh-transit-proximity",
    "refresh-neighbourhood-access",
    "refresh-listing-claim-stats",
}
# Must not be lost: a worker behind by more than the interval would discard every run.
_NEVER_EXPIRING_ENTRIES = {
    "send-saved-search-new-match-alerts",
    "send-daily-digest",
    "send-top-deals-digest",
}


def _maximal_config() -> MagicMock:
    """Every optional beat branch enabled."""
    cfg = MagicMock()
    cfg.redis.url = "redis://broker:6379/9"
    cfg.alerts.digest_mode = True
    cfg.alerts.top_deals = SimpleNamespace(
        enabled=True, crontab_hour=9, crontab_minute=15, crontab_day_of_week="1"
    )
    cfg.alerts.new_match = SimpleNamespace(enabled=True, match_interval_minutes=15)
    cfg.scraping.platforms = {
        "quintoandar": SimpleNamespace(enabled=True, scrape_interval=60),
        "olx": SimpleNamespace(enabled=True, scrape_interval=30),
        "zapimoveis": SimpleNamespace(enabled=True, scrape_interval=45),
    }
    cfg.pipeline_metrics.snapshot_interval_sec = 30
    cfg.scraping.availability_recheck = SimpleNamespace(enabled=True, interval_minutes=360)
    cfg.neighbourhood_access = SimpleNamespace(enabled=True, interval_minutes=1440)
    cfg.neighbourhood_quality.osm_amenities = SimpleNamespace(enabled=True, interval_hours=168)
    cfg.neighbourhood_quality.transit = SimpleNamespace(enabled=True, interval_hours=168)
    cfg.neighbourhood_quality.listing_claim_stats = SimpleNamespace(enabled=True, interval_hours=24)
    return cfg


@pytest.fixture
def conf():
    redis = MagicMock()
    redis.get.return_value = None
    with (
        patch("adapters.queue.celery_app.get_config", return_value=_maximal_config()),
        patch("adapters.queue.celery_app.get_redis", return_value=redis),
    ):
        yield make_celery().conf


@pytest.fixture
def schedule():
    redis = MagicMock()
    redis.get.return_value = None
    with (
        patch("adapters.queue.celery_app.get_config", return_value=_maximal_config()),
        patch("adapters.queue.celery_app.get_redis", return_value=redis),
    ):
        yield build_beat_schedule()


def _worker_queues() -> dict[str, set[str]]:
    """``{service: {queue, ...}}`` for every Celery worker in docker-compose.yml."""
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    workers: dict[str, set[str]] = {}
    for name, service in compose["services"].items():
        command = service.get("command")
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        if not isinstance(command, str) or not re.search(r"\bcelery\b.*\bworker\b", command):
            continue
        match = re.search(r"--queues[= ]([\w,\-]+)", command)
        assert match, f"{name}: a worker without --queues consumes the default queue only"
        workers[name] = set(match.group(1).split(","))
    return workers


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------


def test_the_queue_names_are_defined_once():
    assert (QUEUE_SCRAPERS, QUEUE_AI, QUEUE_PERIODIC) == ("scrapers", "ai", "periodic")
    assert ROUTED_QUEUES == (QUEUE_SCRAPERS, QUEUE_AI, QUEUE_PERIODIC)


def test_route_table(conf):
    routes = conf.task_routes
    for task in _SCRAPERS_TASKS:
        assert routes[task] == {"queue": "scrapers"}, task
    for task in _AI_TASKS:
        assert routes[task] == {"queue": "ai"}, task
    others = set(routes) - _SCRAPERS_TASKS - _AI_TASKS
    assert "tasks.send_price_drop_alert" in others
    assert len(others) >= 12
    for task in others:
        assert routes[task] == {"queue": "periodic"}, task


def test_every_registered_task_has_a_route(conf):
    """A task without a route lands on the default ``celery`` queue."""
    from adapters.queue import tasks as tasks_mod

    registered = {name for name in tasks_mod.celery.tasks if name.startswith("tasks.")}
    assert registered, "no project task registered"
    assert registered <= set(conf.task_routes), sorted(registered - set(conf.task_routes))
    assert set(conf.task_routes) <= registered, "a route names a task that does not exist"


def test_no_gpu_task_is_routed_to_periodic(conf):
    """No task off the ``ai`` queue takes the GPU semaphore in its own body.

    A source check of the task function only: a helper that took the semaphore
    on the task's behalf would not be seen here.
    """
    import inspect

    from adapters.queue import tasks as tasks_mod

    for name, route in conf.task_routes.items():
        if route["queue"] == QUEUE_AI:
            continue
        task = tasks_mod.celery.tasks[name]
        source = inspect.getsource(task.run)
        assert "GPUSemaphore" not in source, f"{name} takes the GPU semaphore off the ai queue"


def test_every_schedulable_task_has_a_route(conf):
    scheduled = {entry["task"] for entry in conf.beat_schedule.values()}
    assert len(scheduled) >= 12, "the maximal config no longer enables every beat branch"
    assert scheduled <= set(conf.task_routes)


def test_no_scheduled_task_shares_the_queue_of_scrape_listings(conf):
    scrape_queue = conf.task_routes[SCRAPE_TASK_NAME]["queue"]
    for name, entry in conf.beat_schedule.items():
        if entry["task"] == SCRAPE_TASK_NAME:
            continue
        assert conf.task_routes[entry["task"]]["queue"] != scrape_queue, (
            f"{name} ({entry['task']}) would wait for a scrape slot"
        )


def test_scheduled_tasks_other_than_scrapes_run_on_periodic(conf):
    for name, entry in conf.beat_schedule.items():
        expected = QUEUE_SCRAPERS if entry["task"] == SCRAPE_TASK_NAME else QUEUE_PERIODIC
        assert conf.task_routes[entry["task"]]["queue"] == expected, name


# ---------------------------------------------------------------------------
# docker-compose.yml: every queue has exactly the right consumer
# ---------------------------------------------------------------------------


def test_every_routed_queue_is_consumed_by_a_worker(conf):
    workers = _worker_queues()
    consumed = set().union(*workers.values())
    routed = {route["queue"] for route in conf.task_routes.values()}
    assert routed == set(ROUTED_QUEUES)
    assert routed <= consumed, f"no worker consumes {sorted(routed - consumed)}"


def test_periodic_and_scrapers_are_never_on_the_same_worker():
    for name, queues in _worker_queues().items():
        assert not {QUEUE_PERIODIC, QUEUE_SCRAPERS} <= queues, name


def test_each_queue_has_its_own_worker_service():
    workers = _worker_queues()
    assert workers["worker_periodic"] == {"periodic"}
    # ``celery`` stays: messages published with no route before BIN-76 drain here.
    assert workers["worker_scraper"] == {"scrapers", "celery"}
    assert workers["worker_ai"] == {"ai"}
    assert [name for name, queues in workers.items() if QUEUE_AI in queues] == ["worker_ai"]


def test_worker_periodic_matches_worker_scraper_except_for_its_queue():
    services = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]
    periodic, scraper = services["worker_periodic"], services["worker_scraper"]
    for key in ("build", "environment", "volumes", "depends_on", "restart"):
        assert periodic[key] == scraper[key], key
    assert periodic["build"]["dockerfile"] == "Dockerfile.worker"
    assert periodic["restart"] == "unless-stopped"
    assert "--concurrency=2" in periodic["command"]
    assert periodic["command"].replace("--queues=periodic", "") == scraper["command"].replace(
        "--queues=scrapers,celery", ""
    )


# ---------------------------------------------------------------------------
# Beat entry expiry
# ---------------------------------------------------------------------------


def test_the_maximal_config_schedules_every_entry_under_test(schedule):
    assert _EXPIRING_ENTRIES | _NEVER_EXPIRING_ENTRIES <= set(schedule)
    assert {"scrape-quintoandar", "scrape-olx", "scrape-zapimoveis"} <= set(schedule)


@pytest.mark.parametrize("name", sorted(_EXPIRING_ENTRIES))
def test_idempotent_entries_expire_after_one_interval(schedule, name):
    entry = schedule[name]
    interval = entry["schedule"]
    assert isinstance(interval, (int, float)), "an interval entry, not a crontab"
    assert entry["options"] == {"expires": float(interval)}
    assert entry["options"]["expires"] > 0


def test_the_expiry_values_are_the_configured_intervals(schedule):
    expires = {name: schedule[name]["options"]["expires"] for name in _EXPIRING_ENTRIES}
    assert expires == {
        "monitor-queues": 60.0,
        "snapshot-pipeline-metrics": 30.0,
        "evaluate-watchlist-alerts": 300.0,
        "match-saved-search-new-matches": 15 * 60.0,
        "recheck-listing-availability": 360 * 60.0,
        "refresh-neighbourhood-amenities": 168 * 3600.0,
        "refresh-transit-proximity": 168 * 3600.0,
        "refresh-neighbourhood-access": 1440 * 60.0,
        "refresh-listing-claim-stats": 24 * 3600.0,
    }


def test_entries_that_must_not_be_lost_carry_no_expires(schedule):
    must_not_lose = _NEVER_EXPIRING_ENTRIES | {n for n in schedule if n.startswith("scrape-")}
    assert len(must_not_lose) == 6
    for name in must_not_lose:
        assert "expires" not in (schedule[name].get("options") or {}), name
        assert "expires" not in schedule[name], name


def test_only_the_nine_idempotent_entries_expire(schedule):
    expiring = {name for name, entry in schedule.items() if (entry.get("options") or {}).get("expires")}
    assert expiring == _EXPIRING_ENTRIES


# ---------------------------------------------------------------------------
# Explicit queues in code: an explicit ``queue=`` overrides task_routes
# ---------------------------------------------------------------------------


def test_no_publisher_names_the_scrapers_queue_explicitly():
    """``apply_async(queue="scrapers")`` would put a periodic task back behind scrapes."""
    src = Path(__file__).resolve().parents[2]
    offenders = []
    for folder in ("api", "adapters", "core", "infra"):
        for path in (src / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"queue\s*=\s*[\"']scrapers[\"']", text) or "queue=QUEUE_SCRAPERS" in text:
                offenders.append(path.relative_to(src).as_posix())
    assert offenders == []


def test_the_admin_triggers_publish_to_the_periodic_queue():
    admin = (Path(__file__).resolve().parents[2] / "api" / "admin.py").read_text(encoding="utf-8")
    assert admin.count("queue=QUEUE_PERIODIC") == 3
    for task in (
        "recheck_listing_availability.apply_async(",
        "refresh_neighbourhood_access_task.apply_async(queue=QUEUE_PERIODIC)",
        "refresh_listing_claim_stats_task.apply_async(queue=QUEUE_PERIODIC)",
    ):
        assert task in admin, task


def test_no_publisher_passes_a_queue_name_as_a_string_literal():
    """The queue names are defined once, in celery_app.py."""
    src = Path(__file__).resolve().parents[2]
    offenders = []
    for folder in ("api", "adapters"):
        for path in (src / folder).rglob("*.py"):
            if path.name == "celery_app.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bqueue\s*=\s*f?[\"']", line):
                    offenders.append(f"{path.relative_to(src).as_posix()}:{number}")
    assert offenders == []


def test_beat_runs_the_scheduler_that_makes_scheduled_scrapes_single_flight():
    """The beat-side single-flight lives in ``RedisAwareScheduler.apply_async`` only.

    Without the ``--scheduler`` flag beat falls back to Celery's default
    scheduler and publishes a scrape on every tick, with no reservation.
    """
    from adapters.queue.redis_scheduler import RedisAwareScheduler

    services = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"]
    command = services["beat"]["command"]
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    match = re.search(r"--scheduler[= ](\S+)", command)
    assert match, "beat has no --scheduler: scheduled scrapes would not be single-flight"
    module_name, _, class_name = match.group(1).rpartition(".")
    assert (module_name, class_name) == (RedisAwareScheduler.__module__, RedisAwareScheduler.__name__)
