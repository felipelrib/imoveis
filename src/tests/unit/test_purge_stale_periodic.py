"""``scripts/ops/purge_stale_periodic.py`` (Story 1.18 operator tool).

Dry run reads and removes nothing; ``--apply`` removes only the four
allowlisted housekeeping task types; a wrong queue or task is refused with
exit 2 before any connection. Always against an in-memory Redis: the script is
never run against a real broker by a test.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.fake_queue_redis import FakeQueueRedis

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "purge_stale_periodic.py"


def _load():
    spec = importlib.util.spec_from_file_location("purge_stale_periodic", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


purge_mod = _load()

_PURGEABLE = (
    "tasks.snapshot_pipeline_metrics",
    "tasks.monitor_queues",
    "tasks.evaluate_watchlist_alerts",
    "tasks.match_saved_search_new_matches",
)
_KEPT = (
    "tasks.scrape_listings",
    "tasks.send_saved_search_new_match_alerts",
    "tasks.send_daily_digest",
    "tasks.send_top_deals_digest",
    "tasks.backfill_listing_costs",
    "tasks.recheck_listing_availability",
    "tasks.refresh_neighbourhood_amenities",
    "tasks.refresh_transit_proximity",
    "tasks.refresh_neighbourhood_access",
    "tasks.refresh_listing_claim_stats",
    "tasks.send_price_drop_alert",
    "tasks.ai_enrich",
    "tasks.embed_property",
)


def _message(task: str, index: int) -> bytes:
    """A Kombu Redis-transport message as Celery 5 publishes it."""
    return json.dumps(
        {
            "body": "W1tdLCB7fSwge31d",
            "content-encoding": "utf-8",
            "content-type": "application/json",
            "headers": {"lang": "py", "task": task, "id": f"id-{task}-{index}"},
            "properties": {"delivery_tag": f"tag-{task}-{index}"},
        }
    ).encode()


def _mixed_queue() -> tuple[FakeQueueRedis, list]:
    redis = FakeQueueRedis()
    items: list = []
    for index in range(7):
        items.append(_message("tasks.snapshot_pipeline_metrics", index))
    for index in range(4):
        items.append(_message("tasks.monitor_queues", index))
    for index in range(2):
        items.append(_message("tasks.evaluate_watchlist_alerts", index))
    items.append(_message("tasks.match_saved_search_new_matches", 0))
    for task in _KEPT:
        items.append(_message(task, 0))
    items.append(b"not json at all")
    items.append(json.dumps({"headers": {}}).encode())
    items.append(b"\xff\xfe broken bytes")
    # Interleave so removable and kept messages are not contiguous.
    items = items[::2] + items[1::2]
    redis.lists["scrapers"] = list(items)
    return redis, items


def test_the_allowlist_is_exactly_the_four_housekeeping_tasks():
    assert purge_mod.PURGEABLE_TASKS == _PURGEABLE
    assert purge_mod.ALLOWED_QUEUES == ("scrapers",)


def test_task_name_reads_the_kombu_header():
    assert purge_mod.task_name(_message("tasks.monitor_queues", 1)) == "tasks.monitor_queues"
    assert purge_mod.task_name(_message("tasks.monitor_queues", 1).decode()) == "tasks.monitor_queues"
    assert purge_mod.task_name(b"nope") is None
    assert purge_mod.task_name(b"[]") is None
    assert purge_mod.task_name(json.dumps({"headers": {"task": 7}})) is None
    assert purge_mod.task_name(None) is None


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_counts_by_task_type_and_removes_nothing(capsys):
    redis, items = _mixed_queue()

    code = purge_mod.main([], redis_factory=lambda url: redis)

    assert code == 0
    assert redis.lists["scrapers"] == items
    assert redis.writes == []
    out = capsys.readouterr().out
    assert f"queue scrapers: {len(items)} message(s)" in out
    assert "7  tasks.snapshot_pipeline_metrics  [removable]" in out
    assert "4  tasks.monitor_queues  [removable]" in out
    assert "2  tasks.evaluate_watchlist_alerts  [removable]" in out
    assert "1  tasks.match_saved_search_new_matches  [removable]" in out
    for task in _KEPT:
        assert f"1  {task}  [kept]" in out
    assert "3  unparseable  [kept]" in out
    assert "dry run: nothing removed. 14 message(s) would be removed with --apply." in out


def test_dry_run_reads_the_list_in_pages():
    redis, items = _mixed_queue()
    report = purge_mod.purge(redis, page_size=4)
    assert report["total"] == len(items)
    assert report["applied"] is False
    assert report["removed"] == {}
    assert sum(report["counts"].values()) == len(items)


def test_dry_run_marks_only_the_selected_tasks_removable(capsys):
    redis, _items = _mixed_queue()
    code = purge_mod.main(["--task", "tasks.monitor_queues"], redis_factory=lambda url: redis)
    assert code == 0
    out = capsys.readouterr().out
    assert "4  tasks.monitor_queues  [removable]" in out
    assert "7  tasks.snapshot_pipeline_metrics  [kept]" in out
    assert "4 message(s) would be removed" in out


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def test_apply_removes_only_the_four_allowlisted_task_types(capsys):
    redis, items = _mixed_queue()

    code = purge_mod.main(["--apply"], redis_factory=lambda url: redis)

    assert code == 0
    left = redis.lists["scrapers"]
    assert left == [item for item in items if purge_mod.task_name(item) not in _PURGEABLE]
    assert {purge_mod.task_name(item) for item in left} == set(_KEPT) | {None}
    assert len(left) == len(_KEPT) + 3  # every kept task and the three unparseable payloads
    assert {key for _cmd, key in redis.writes} == {"scrapers"}
    assert {cmd for cmd, _key in redis.writes} == {"lrem"}
    out = capsys.readouterr().out
    assert "removed 7 x tasks.snapshot_pipeline_metrics" in out
    assert "removed 4 x tasks.monitor_queues" in out
    assert "removed 2 x tasks.evaluate_watchlist_alerts" in out
    assert "removed 1 x tasks.match_saved_search_new_matches" in out
    assert "removed 14 message(s) in total" in out
    assert "3  unparseable  [kept]" in out
    assert "gone" not in out


def test_apply_with_one_task_leaves_the_other_housekeeping_types():
    redis, items = _mixed_queue()
    report = purge_mod.purge(redis, tasks=("tasks.monitor_queues",), apply=True)
    assert report["removed"] == {"tasks.monitor_queues": 4}
    assert len(redis.lists["scrapers"]) == len(items) - 4
    assert purge_mod.count_by_task(redis.lists["scrapers"])["tasks.snapshot_pipeline_metrics"] == 7


def test_a_payload_a_worker_consumed_first_counts_as_gone(capsys):
    redis, _items = _mixed_queue()
    consumed = _message("tasks.monitor_queues", 0)
    real_lrem = redis.lrem

    def lrem(key, count, value):
        if value == consumed:
            redis.lists[key].remove(value)  # the worker popped it between read and remove
            return 0
        return real_lrem(key, count, value)

    redis.lrem = lrem
    code = purge_mod.main(["--apply"], redis_factory=lambda url: redis)

    assert code == 0
    out = capsys.readouterr().out
    assert "removed 3 x tasks.monitor_queues" in out
    assert "removed 13 message(s) in total" in out
    assert "gone: 1 message(s) were consumed by a worker first" in out


def test_a_message_seen_on_two_pages_is_counted_and_removed_once():
    """A publish at the head while paging shifts the list by one."""
    redis, items = _mixed_queue()
    real_lrange = redis.lrange
    calls = {"n": 0}

    def lrange(key, start, stop):
        calls["n"] += 1
        if calls["n"] == 2:
            redis.lists[key].insert(0, _message("tasks.scrape_listings", 99))
        return real_lrange(key, start, stop)

    redis.lrange = lrange
    report = purge_mod.purge(redis, apply=True, page_size=5)
    assert report["gone"] == 0
    assert sum(report["removed"].values()) == 14
    assert _message("tasks.scrape_listings", 99) in redis.lists["scrapers"]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def _no_connection(_url):
    raise AssertionError("a refused request must not open a connection")


@pytest.mark.parametrize(
    "argv",
    [
        ["--queue", "ai"],
        ["--queue", "ai", "--apply"],
        ["--queue", "periodic", "--apply"],
        ["--queue", "celery"],
        ["--task", "tasks.scrape_listings"],
        ["--task", "tasks.scrape_listings", "--apply"],
        ["--task", "tasks.monitor_queues", "--task", "tasks.send_daily_digest", "--apply"],
        ["--task", "tasks.send_saved_search_new_match_alerts", "--apply"],
        ["--task", "tasks.backfill_listing_costs", "--apply"],
        ["--task", "tasks.ai_enrich", "--apply"],
    ],
)
def test_a_wrong_queue_or_task_is_refused_with_exit_2_before_reading(argv, capsys):
    assert purge_mod.main(argv, redis_factory=_no_connection) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused" in captured.err


@pytest.mark.parametrize("task", _KEPT)
def test_the_library_entry_point_refuses_the_same_requests(task):
    redis, items = _mixed_queue()
    with pytest.raises(ValueError, match="refused"):
        purge_mod.purge(redis, tasks=(task,), apply=True)
    with pytest.raises(ValueError, match="refused"):
        purge_mod.purge(redis, queue="ai", apply=True)
    assert redis.lists["scrapers"] == items
    assert redis.writes == []


def test_help_exits_zero_without_a_connection(capsys):
    with pytest.raises(SystemExit) as exit_info:
        purge_mod.main(["--help"], redis_factory=_no_connection)
    assert exit_info.value.code == 0
    assert "--apply" in capsys.readouterr().out


def test_an_unreachable_redis_is_exit_1(capsys):
    def factory(_url):
        raise ConnectionError("refused")

    assert purge_mod.main([], redis_factory=factory) == 1
    assert "ConnectionError" in capsys.readouterr().err


def test_nothing_else_in_the_repository_invokes_the_script():
    """It is an operator tool: no script, hook, task or compose file runs it."""
    root = _SCRIPT.parents[2]
    callers = []
    for folder in ("scripts", ".claude", "src/adapters", "src/api", "src/core", "src/infra"):
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path == _SCRIPT or path.suffix not in {".py", ".sh", ".json", ".toml", ".yml", ".yaml"}:
                continue
            if "purge_stale_periodic" in path.read_text(encoding="utf-8", errors="replace"):
                callers.append(path.relative_to(root).as_posix())
    for name in ("docker-compose.yml", "docker-compose.test.yml"):
        if "purge_stale_periodic" in (root / name).read_text(encoding="utf-8"):
            callers.append(name)
    assert callers == []


# ---------------------------------------------------------------------------
# Which Redis, and --dry-run
# ---------------------------------------------------------------------------


def test_redis_target_is_host_port_db_and_never_the_password():
    assert purge_mod.redis_target("redis://localhost:6379/0") == "localhost:6379/0"
    assert purge_mod.redis_target("redis://localhost") == "localhost:6379/0"
    assert purge_mod.redis_target("redis://:s3cret@redis-host:6390/3") == "redis-host:6390/3"
    assert purge_mod.redis_target("redis://user:s3cret@10.0.0.5:7000/15") == "10.0.0.5:7000/15"


@pytest.mark.parametrize("argv", [[], ["--dry-run"], ["--apply"]])
def test_the_first_output_line_names_the_redis_it_read(argv, capsys):
    redis, _items = _mixed_queue()
    code = purge_mod.main(
        ["--redis-url", "redis://:s3cret@primary-host:6380/0", *argv], redis_factory=lambda url: redis
    )
    assert code == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "redis primary-host:6380/0"
    assert "s3cret" not in out


def test_the_default_target_is_printed_too(capsys):
    redis, _items = _mixed_queue()
    purge_mod.main([], redis_factory=lambda url: redis)
    assert capsys.readouterr().out.splitlines()[0] == "redis localhost:6379/0"


def test_dry_run_flag_is_the_default_behaviour(capsys):
    redis, items = _mixed_queue()
    code = purge_mod.main(["--dry-run"], redis_factory=lambda url: redis)
    assert code == 0
    assert redis.lists["scrapers"] == items
    assert redis.writes == []
    assert "dry run: nothing removed." in capsys.readouterr().out


def test_dry_run_with_apply_is_refused_with_exit_2_before_connecting(capsys):
    assert purge_mod.main(["--dry-run", "--apply"], redis_factory=_no_connection) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused" in captured.err and "--dry-run" in captured.err


@pytest.mark.parametrize("argv", [[], ["--apply"]])
def test_the_target_is_printed_before_anything_is_read_or_removed(argv, capsys):
    """An --apply against the wrong Redis must show where it is aimed first."""
    redis, _items = _mixed_queue()
    printed_before_first_read = []
    real_lrange = redis.lrange

    def lrange(key, start, stop):
        if not printed_before_first_read:
            printed_before_first_read.append(capsys.readouterr().out)
        return real_lrange(key, start, stop)

    redis.lrange = lrange
    code = purge_mod.main(
        ["--redis-url", "redis://:s3cret@primary-host:6380/0", *argv], redis_factory=lambda url: redis
    )
    assert code == 0
    assert printed_before_first_read == ["redis primary-host:6380/0\n"]
    assert not capsys.readouterr().out.startswith("redis ")  # named once


def test_an_unreachable_redis_still_names_its_target(capsys):
    def factory(_url):
        raise ConnectionError("refused")

    assert purge_mod.main(["--redis-url", "redis://other-host:6390/2", "--apply"], redis_factory=factory) == 1
    captured = capsys.readouterr()
    assert captured.out == "redis other-host:6390/2\n"
    assert "ConnectionError" in captured.err


def test_apply_matches_the_task_name_in_the_header_not_a_substring_of_the_payload():
    """A kept message that merely mentions a purgeable task name is not removed."""
    redis = FakeQueueRedis()
    decoy = json.loads(_message("tasks.scrape_listings", 1))
    decoy["headers"]["argsrepr"] = "('tasks.monitor_queues',)"
    decoy["body"] = "tasks.monitor_queues tasks.snapshot_pipeline_metrics"
    decoy_payload = json.dumps(decoy).encode()
    real = _message("tasks.monitor_queues", 2)
    redis.lists["scrapers"] = [decoy_payload, real]

    report = purge_mod.purge(redis, apply=True)

    assert report["removed"] == {"tasks.monitor_queues": 1}
    assert redis.lists["scrapers"] == [decoy_payload]
