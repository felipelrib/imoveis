"""Single-flight for ``tasks.scrape_listings`` per platform and scope (Story 1.18).

Two expiring leases, both :class:`core.backfill_runner.BackfillLease` (atomic
``SET NX EX``, owner-token renew and release), both with the task id as token:

- **queued** — taken by whoever publishes the message (beat, ``POST /scrape``)
  and handed over when the task starts. While it is held, nobody publishes a
  second scrape of the same platform and scope.
- **running** — taken by the task when it starts and renewed from its item
  loop. While it is held, a second delivery (a message from before this story,
  or a broker redelivery of the same id after the visibility timeout) returns
  ``skipped`` instead of scraping the same windows again.

Nothing here blocks scraping without a time limit: a publisher or a worker that
dies leaves a lease that expires by its TTL.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Callable, Iterable, Optional

from core.backfill_runner import BackfillLease

KEY_PREFIX = "scrape:single_flight"

# Longer than a queue wait behind two multi-hour scrapes.
QUEUED_TTL_SECONDS = 3 * 3600
# A run renews this every minute, so a killed run blocks its platform for at
# most this long.
RUNNING_TTL_SECONDS = 2 * 3600
RENEW_EVERY_SECONDS = 60

DEFAULT_SCOPE = "default"
# Running-lease owner when the worker node name is not known (``.run()``, eager).
DEFAULT_WORKER_OWNER = "scrape-worker"

QUEUED = "queued"
ALREADY_QUEUED = "already_queued"
ALREADY_RUNNING = "already_running"


def scrape_scope(checkpoint: Optional[dict]) -> str:
    """``default`` without a checkpoint override, else a stable digest of it.

    Beat scrapes pass no checkpoint. A manual trigger always carries one (at
    least ``scrape_type``), so it is its own scope and does not block, nor is
    blocked by, the scheduled scrape of the same platform.
    """
    if not checkpoint:
        return DEFAULT_SCOPE
    canonical = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _default_monotonic() -> float:
    return time.monotonic()


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


class ScrapeSingleFlight:
    """The queued reservation and the running lease of one scrape execution."""

    def __init__(
        self,
        redis: Any,
        *,
        platform: str,
        scope: str,
        task_id: str,
        owner: Optional[str] = None,
        monotonic: Optional[Callable[[], float]] = None,
    ) -> None:
        self._redis = redis
        self.platform = platform
        self.scope = scope
        self.task_id = task_id
        self._monotonic = monotonic or _default_monotonic
        base = f"{KEY_PREFIX}:{platform}:{scope}"
        self._queued = BackfillLease(
            redis,
            prefix=f"{base}:queued",
            ttl_seconds=QUEUED_TTL_SECONDS,
            token=task_id,
            owner="scrape-publisher",
        )
        self._running = BackfillLease(
            redis,
            prefix=f"{base}:running",
            ttl_seconds=RUNNING_TTL_SECONDS,
            token=task_id,
            # The worker node name: what ``release_running_leases_of`` matches
            # when that worker shuts down.
            owner=owner or DEFAULT_WORKER_OWNER,
        )
        # Set only by a successful ``begin`` on this object. A duplicate carries
        # the same token as the run it duplicates when the broker redelivers an
        # id, so "the token matches" is not proof that this execution owns the
        # running lease.
        self._owns_running = False
        self._last_renew: Optional[float] = None

    @property
    def queued_key(self) -> str:
        return self._queued.key

    @property
    def running_key(self) -> str:
        return self._running.key

    def holder(self) -> Optional[dict]:
        """``{"state": "running"|"queued", "task_id": ...}`` or None when free."""
        running = _text(self._redis.get(self._running.key))
        if running:
            return {"state": "running", "task_id": running}
        queued = _text(self._redis.get(self._queued.key))
        if queued:
            return {"state": "queued", "task_id": queued}
        return None

    # -- publisher side -----------------------------------------------------

    def reserve(self) -> tuple[str, str]:
        """Take the queued lease for this task id.

        Returns ``(status, task_id)``: ``queued`` with this object's id, or
        ``already_running`` / ``already_queued`` with the id of the holder.
        """
        running = _text(self._redis.get(self._running.key))
        if running:
            return ALREADY_RUNNING, running
        # Twice: the reservation can expire or be handed over between the
        # failed SET and the read of its holder.
        for _attempt in range(2):
            if self._queued.acquire():
                return self._confirm_reservation()
            queued = _text(self._redis.get(self._queued.key))
            if queued:
                return ALREADY_QUEUED, queued
        return ALREADY_QUEUED, _text(self._redis.get(self._queued.key)) or ""

    def _confirm_reservation(self) -> tuple[str, str]:
        """Look at the running lease again once the reservation is held.

        A task that begins between the first read and the ``SET`` takes the
        running lease and then drops its reservation, which is what let this
        one in: without the second look a message would be published behind a
        scrape that has just started.
        """
        running = _text(self._redis.get(self._running.key))
        if running:
            self._queued.release()
            return ALREADY_RUNNING, running
        return QUEUED, self.task_id

    def cancel_reservation(self) -> bool:
        """Drop the queued lease iff this task id holds it."""
        return self._queued.release()

    # -- worker side --------------------------------------------------------

    def begin(self) -> bool:
        """Take the running lease, then drop the own reservation.

        False means another execution is in flight: the caller must return
        without scraping and without calling :meth:`renew` or :meth:`finish`.

        The running lease is taken first so the platform is never seen free
        between the two steps. The reservation is dropped in both outcomes (a
        duplicate that will not run must not keep the platform reserved); the
        release is owner-token guarded, so it is a no-op without a reservation
        and never drops another task's.
        """
        acquired = self._running.acquire()
        if acquired:
            # Before the next Redis call: if that one raises, the caller still
            # holds a lease that :meth:`finish` releases.
            self._owns_running = True
            self._last_renew = self._monotonic()
        self._queued.release()
        return acquired

    def renew(self) -> Optional[bool]:
        """Extend the running lease, at most once per ``RENEW_EVERY_SECONDS``.

        None when nothing was due (or this execution holds no lease), True when
        renewed, False when the lease was lost — reported once, after which this
        execution no longer renews or releases it.
        """
        if not self._owns_running:
            return None
        now = self._monotonic()
        if self._last_renew is not None and now - self._last_renew < RENEW_EVERY_SECONDS:
            return None
        self._last_renew = now
        if self._running.renew():
            return True
        self._owns_running = False
        return False

    def finish(self) -> bool:
        """Release the running lease iff this execution took it."""
        if not self._owns_running:
            return False
        self._owns_running = False
        return self._running.release()


def release_running_leases_of(
    redis: Any, owner: str, task_ids: Optional[Iterable[str]] = None
) -> int:
    """Release the running leases taken by the worker node ``owner``.

    For a worker that is shutting down: its tasks are about to be killed and
    their ``finally`` will not run, so without this the platform would wait out
    the running TTL while the redelivered message returns ``skipped``.

    ``task_ids`` narrows it to the leases of those task ids (the scrapes the
    stopping worker is executing). A node name alone is not an identity: workers
    started by hand without ``-n`` all call themselves ``celery@<host>``, and
    one of them stopping must not free the lease of a scrape another is running.
    With an empty ``task_ids`` nothing is read or released.

    Each release is the lease's owner-token compare-and-swap with the token
    recorded in its provenance hash, never a bare delete. A lease whose hash is
    missing or names another owner is left to its TTL. Queued leases are never
    touched. Returns the number released.
    """
    if not owner:
        return 0
    wanted = None if task_ids is None else {str(task_id) for task_id in task_ids}
    if wanted is not None and not wanted:
        return 0
    suffix = ":lease:meta"
    released = 0
    for raw_key in redis.scan_iter(match=f"{KEY_PREFIX}:*:running{suffix}"):
        key = _text(raw_key) or ""
        if not key.endswith(f":running{suffix}"):
            continue
        meta = {_text(k): _text(v) for k, v in (redis.hgetall(key) or {}).items()}
        token = meta.get("token")
        if meta.get("owner") != owner or not token:
            continue
        if wanted is not None and token not in wanted:
            continue
        lease = BackfillLease(
            redis,
            prefix=key[: -len(suffix)],
            ttl_seconds=RUNNING_TTL_SECONDS,
            token=token,
            owner=owner,
        )
        if lease.release():
            released += 1
    return released


def enqueue_scrape(
    task: Any,
    platform: str,
    checkpoint: Optional[dict],
    redis: Any,
) -> tuple[str, str]:
    """Publish one scrape unless the same platform and scope is queued or running.

    Returns ``(task_id, status)``. For ``already_queued`` / ``already_running``
    nothing is published and the id is the holder's.
    """
    task_id = str(uuid.uuid4())
    flight = ScrapeSingleFlight(
        redis, platform=platform, scope=scrape_scope(checkpoint), task_id=task_id
    )
    status, holder_id = flight.reserve()
    if status != QUEUED:
        return holder_id, status
    args = [platform] if checkpoint is None else [platform, checkpoint]
    try:
        task.apply_async(args=args, task_id=task_id)
    except Exception:
        flight.cancel_reservation()
        raise
    return task_id, QUEUED
