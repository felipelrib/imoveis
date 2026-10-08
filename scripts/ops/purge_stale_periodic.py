#!/usr/bin/env python3
"""Count, and with ``--apply`` remove, stale housekeeping messages left on ``scrapers``.

    python scripts/ops/purge_stale_periodic.py                 # dry run: counts only
    python scripts/ops/purge_stale_periodic.py --dry-run       # the same, said explicitly
    python scripts/ops/purge_stale_periodic.py --apply         # remove the allowlisted types
    python scripts/ops/purge_stale_periodic.py --task tasks.monitor_queues --apply

Operator tool for the Story 1.18 deploy (docs/features/v0.14-s1.18-*.md). Before
that story every periodic task was published to ``scrapers``; the ones already
there are not moved to ``periodic`` and drain through ``worker_scraper``. This
script is the optional shortcut: it drops the four idempotent housekeeping task
types, whose next scheduled run does the same work, and nothing else.

Rules it never breaks:

- It only reads unless ``--apply`` is given. ``--dry-run`` with ``--apply`` is
  refused with exit 2.
- The first line it prints names the Redis it is aimed at (host:port/db, no
  password), before it reads or removes anything.
- It only accepts the queue ``scrapers`` and only removes task types from
  ``PURGEABLE_TASKS``; anything else is refused with exit 2 before a connection
  is opened. Scrapes, the alert sender, digests, the cost backfill, rechecks,
  refresh jobs, price-drop alerts and AI messages are never removed.
- A payload it cannot parse is counted as ``unparseable`` and kept.
- Nothing calls it: no script, hook, task or test runs it against a real broker.

Exit 0 = done, 2 = refused (bad queue or task), 1 = could not reach Redis.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any, Iterator, Optional, Sequence
from urllib.parse import urlparse

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
ALLOWED_QUEUES = ("scrapers",)
# Idempotent housekeeping: a later run covers a dropped one. Not a task more.
PURGEABLE_TASKS = (
    "tasks.snapshot_pipeline_metrics",
    "tasks.monitor_queues",
    "tasks.evaluate_watchlist_alerts",
    "tasks.match_saved_search_new_matches",
)
UNPARSEABLE = "unparseable"
PAGE_SIZE = 1000


def redis_target(url: str) -> str:
    """``host:port/db`` of a Redis URL. Never the user or the password."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        db = (parsed.path or "").lstrip("/").split("?", 1)[0] or "0"
    except ValueError:
        return "unparseable-url"
    return f"{host}:{port}/{db}"


def task_name(payload: Any) -> Optional[str]:
    """The Celery task name of one Kombu message (``headers.task``), or None."""
    try:
        if isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload).decode("utf-8")
        message = json.loads(payload)
        name = message["headers"]["task"]
    except (TypeError, ValueError, KeyError, UnicodeDecodeError):
        return None
    return name if isinstance(name, str) and name else None


def iter_payloads(redis: Any, queue: str, page_size: int = PAGE_SIZE) -> Iterator[Any]:
    """Every message on the list, each once, read with ``LRANGE`` a page at a time.

    Kombu pushes new messages at the head and workers pop from the tail, so a
    message published while this reads shifts the pages and can show a payload
    twice: payloads are unique per message (they carry the task id), so a
    repeat is dropped here.
    """
    seen: set = set()
    start = 0
    while True:
        page = redis.lrange(queue, start, start + page_size - 1)
        if not page:
            return
        for payload in page:
            if payload in seen:
                continue
            seen.add(payload)
            yield payload
        start += page_size


def count_by_task(payloads: Sequence[Any]) -> Counter:
    counts: Counter = Counter()
    for payload in payloads:
        counts[task_name(payload) or UNPARSEABLE] += 1
    return counts


def validate_request(queue: str, tasks: Sequence[str]) -> Optional[str]:
    """None when the request is allowed, else why it is refused."""
    if queue not in ALLOWED_QUEUES:
        return f"queue {queue!r} is refused: only {', '.join(ALLOWED_QUEUES)} can be purged"
    refused = [task for task in tasks if task not in PURGEABLE_TASKS]
    if refused:
        return (
            f"task(s) {', '.join(refused)} are refused: only "
            f"{', '.join(PURGEABLE_TASKS)} can be purged"
        )
    return None


def purge(
    redis: Any,
    *,
    queue: str = "scrapers",
    tasks: Sequence[str] = PURGEABLE_TASKS,
    apply: bool = False,
    page_size: int = PAGE_SIZE,
) -> dict:
    """Count the list by task type and, with ``apply``, remove the selected types.

    Returns ``{"total", "counts", "removable", "removed", "gone", "applied"}``.
    ``gone`` counts messages a worker consumed between the read and the remove.
    """
    refusal = validate_request(queue, tasks)
    if refusal:
        raise ValueError(refusal)
    selected = set(tasks)
    payloads = list(iter_payloads(redis, queue, page_size))
    counts = count_by_task(payloads)
    removable = {name: counts[name] for name in sorted(selected) if counts.get(name)}
    removed: Counter = Counter()
    gone = 0
    if apply:
        for payload in payloads:
            name = task_name(payload)
            if name is None or name not in selected:
                continue
            if int(redis.lrem(queue, 1, payload) or 0) > 0:
                removed[name] += 1
            else:
                gone += 1
    return {
        "total": len(payloads),
        "counts": dict(counts),
        "removable": removable,
        "removed": dict(removed),
        "gone": gone,
        "applied": bool(apply),
    }


def format_report(report: dict, *, queue: str, tasks: Sequence[str], target: str = "") -> str:
    selected = set(tasks)
    lines = [f"redis {target}"] if target else []
    lines.append(f"queue {queue}: {report['total']} message(s)")
    for name, count in sorted(report["counts"].items(), key=lambda item: (-item[1], item[0])):
        mark = "removable" if name in selected else "kept"
        lines.append(f"  {count:>8}  {name}  [{mark}]")
    removable_total = sum(report["removable"].values())
    if not report["applied"]:
        lines.append(
            f"dry run: nothing removed. {removable_total} message(s) would be removed with --apply."
        )
        return "\n".join(lines) + "\n"
    for name, count in sorted(report["removed"].items()):
        lines.append(f"removed {count} x {name}")
    lines.append(f"removed {sum(report['removed'].values())} message(s) in total")
    if report["gone"]:
        lines.append(f"gone: {report['gone']} message(s) were consumed by a worker first")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Count the messages on the scrapers queue by task type and, with --apply, "
            "remove the stale housekeeping ones (Story 1.18 deploy). Dry run by default."
        )
    )
    parser.add_argument("--redis-url", default=DEFAULT_REDIS_URL, help=f"default: {DEFAULT_REDIS_URL}")
    parser.add_argument("--queue", default="scrapers", help="only 'scrapers' is accepted")
    parser.add_argument(
        "--task",
        action="append",
        dest="tasks",
        metavar="TASK",
        help="task type to remove (repeatable); default: all of " + ", ".join(PURGEABLE_TASKS),
    )
    parser.add_argument("--apply", action="store_true", help="remove; without it nothing is written")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count only, remove nothing (the default; refused together with --apply)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None, *, redis_factory: Any = None) -> int:
    args = build_parser().parse_args(argv)
    tasks = tuple(args.tasks) if args.tasks else PURGEABLE_TASKS
    refusal = validate_request(args.queue, tasks)
    if refusal is None and args.dry_run and args.apply:
        refusal = "--dry-run and --apply contradict each other: pass one"
    if refusal:
        sys.stderr.write(f"refused: {refusal}\n")
        return 2
    # Named before anything is read or removed, so an --apply against the wrong
    # Redis shows its target first and an error still says where it was aimed.
    sys.stdout.write(f"redis {redis_target(args.redis_url)}\n")
    sys.stdout.flush()
    try:
        if redis_factory is None:
            import redis as redis_lib

            redis_factory = redis_lib.Redis.from_url
        client = redis_factory(args.redis_url)
        report = purge(client, queue=args.queue, tasks=tasks, apply=args.apply)
    except Exception as exc:  # noqa: BLE001 - an operator tool reports and exits
        sys.stderr.write(f"error: {type(exc).__name__}: {exc}\n")
        return 1
    sys.stdout.write(format_report(report, queue=args.queue, tasks=tasks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
