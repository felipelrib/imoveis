"""Redis-backed GPU semaphore for controlling concurrent GPU-bound tasks.

Changes from original:
- Imports Redis from centralized infra.redis_client (no more hardcoded URL)
- Reads defaults from centralized config
- Added scale(new_limit) for graceful concurrency adjustment
- Added structured logging
"""
from __future__ import annotations

import time
from typing import Optional

import redis as redis_lib

from infra.config import get_config
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)


class GPUSemaphore:
    """A Redis-backed counting semaphore to control concurrent GPU jobs.

    Keys:
        semaphore:<name>  — integer counter (current available slots)

    Usage::

        sem = GPUSemaphore()
        if sem.acquire(timeout=30):
            try:
                run_gpu_task()
            finally:
                sem.release()
    """

    def __init__(
        self,
        name: Optional[str] = None,
        limit: Optional[int] = None,
        redis_client: Optional[redis_lib.Redis] = None,
    ) -> None:
        cfg = get_config().gpu
        self.r = redis_client or get_redis()
        self.name = name or cfg.semaphore_name
        self.limit = limit if limit is not None else cfg.semaphore_limit
        self.key = f"semaphore:{self.name}"
        # Initialise key only if it does not exist yet
        self.r.setnx(self.key, self.limit)

    def acquire(self, timeout: int = 60) -> bool:
        """Block until a slot is available or *timeout* seconds elapse.

        Returns:
            True if slot acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.r.pipeline() as pipe:
                try:
                    pipe.watch(self.key)
                    val = int(pipe.get(self.key) or 0)
                    if val > 0:
                        pipe.multi()
                        pipe.decr(self.key)
                        pipe.execute()
                        logger.debug("gpu_semaphore_acquired", name=self.name, remaining=val - 1)
                        return True
                    pipe.unwatch()
                except redis_lib.WatchError:
                    continue  # retry on concurrent modification
            time.sleep(0.1)
        logger.warning("gpu_semaphore_timeout", name=self.name, timeout=timeout)
        return False

    def release(self) -> None:
        """Return a slot to the semaphore."""
        self.r.incr(self.key)
        logger.debug("gpu_semaphore_released", name=self.name)

    def scale(self, new_limit: int) -> None:
        """Adjust the semaphore limit.

        This does NOT interrupt in-flight tasks.  Existing holders will release
        normally.  The new limit takes effect for future acquire() calls.
        """
        self.r.set(self.key, new_limit)
        self.limit = new_limit
        logger.info("gpu_semaphore_scaled", name=self.name, new_limit=new_limit)

    @property
    def available(self) -> int:
        """Current number of available slots."""
        return int(self.r.get(self.key) or 0)
