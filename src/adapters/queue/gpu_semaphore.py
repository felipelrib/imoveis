from typing import Optional

import redis

from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)

# Fallback TTL (seconds) for the "held slot" Redis key when a caller does not
# pass an explicit `slot_ttl`. Matches the pre-BIN-147 default so callers that
# don't opt in keep their prior (already generous) behavior.
DEFAULT_SLOT_TTL_SECONDS = 3600


class GPUSemaphore:
    """A Redis-backed counting semaphore to control concurrent GPU jobs.

    Keys:
        semaphore:<name>  — integer counter (current available slots)

    Usage::

        sem = GPUSemaphore()
        if sem.acquire(slot_ttl=TASK_HARD_TIME_LIMIT_SECONDS + margin):
            try:
                # Do work
                pass
            finally:
                sem.release()
    """

    def __init__(self, name: str = "gpu", max_concurrent: int = 1):
        self.name = name
        self._default_limit = max_concurrent
        self.redis_client = get_redis()

    @property
    def max_concurrent(self) -> int:
        val = self.redis_client.get(f"semaphore:limit:{self.name}")
        return int(val) if val is not None else self._default_limit

    @property
    def available(self) -> int:
        """Get number of available slots."""
        try:
            value = self.redis_client.get(f"semaphore:{self.name}")
            return int(value) if value is not None else self.max_concurrent
        except Exception:
            logger.exception("gpu_semaphore_get_value_error", semaphore=self.name)
            # Fallback para valor padrão em caso de falha
            return self._default_limit

    def acquire(self, timeout: Optional[int] = None, *, slot_ttl: Optional[int] = None) -> bool:
        """Acquire a semaphore slot.

        Args:
            timeout: caller's wait-intent in seconds, e.g. the countdown a
                Celery task plans to `self.retry()` with. NOTE: ``acquire()``
                is a one-shot check-and-decrement with no retry/wait loop —
                this value is accepted for call-site documentation / backward
                compatibility only and is **not** used as the Redis key TTL.
                Using it that way was BIN-147: a 30s wait-intent expired the
                "held slot" marker mid-task (VLM+sentiment analysis routinely
                runs longer), silently reporting the slot free again and
                oversubscribing the GPU. Use ``slot_ttl`` instead.
            slot_ttl: seconds the "held slot" Redis key should live once
                acquired. Callers should pass a value that exceeds the actual
                caller task's hard time limit (e.g. Celery ``time_limit``) so
                the slot marker cannot expire before the task finishes or is
                force-killed. Defaults to ``DEFAULT_SLOT_TTL_SECONDS`` when
                not given.
        """
        ttl = slot_ttl if slot_ttl is not None else DEFAULT_SLOT_TTL_SECONDS
        try:
            # Usar transação Redis para garantir atomicidade
            pipe = self.redis_client.pipeline()
            while True:
                try:
                    pipe.watch(f"semaphore:{self.name}")

                    current_value = pipe.get(f"semaphore:{self.name}")
                    if current_value is None:
                        current_value = self.max_concurrent
                    else:
                        current_value = int(current_value)

                    if current_value > 0:
                        # Reduzir o contador
                        pipe.multi()
                        pipe.setex(f"semaphore:{self.name}", ttl, current_value - 1)
                        pipe.execute()
                        return True
                    else:
                        pipe.unwatch()
                        return False
                except redis.WatchError:
                    continue

        except Exception:
            logger.exception("gpu_semaphore_acquire_error", semaphore=self.name)
            # Intentional fail-open (BIN-143): a flaky/unreachable Redis must not
            # halt AI enrichment entirely. Worst case is transient GPU
            # oversubscription (bounded by process concurrency elsewhere), which is
            # preferable to blocking the whole enrichment pipeline on Redis health.
            # If GPU oversubscription becomes an actual incident, make this
            # configurable (fail-open vs fail-closed) rather than flipping it here —
            # see BIN-147 (semaphore TTL/timeout conflation) for related hardening.
            return True

    def release(self) -> None:
        """Release a semaphore slot."""
        try:
            # Usar transação Redis para garantir atomicidade
            pipe = self.redis_client.pipeline()
            while True:
                try:
                    pipe.watch(f"semaphore:{self.name}")

                    current_value = pipe.get(f"semaphore:{self.name}")
                    if current_value is None:
                        current_value = 0
                    else:
                        current_value = int(current_value)

                    # Aumentar o contador, mas não ultrapassar o máximo
                    new_value = min(current_value + 1, self.max_concurrent)

                    pipe.multi()
                    pipe.setex(f"semaphore:{self.name}", 3600, new_value)
                    pipe.execute()
                    break
                except redis.WatchError:
                    continue

        except Exception:
            logger.exception("gpu_semaphore_release_error", semaphore=self.name)

    def scale(self, new_limit: int) -> None:
        """Update the maximum concurrent slots for this semaphore.

        Sets the semaphore counter to the new limit so that future acquire/release
        operations respect it.  Called by the admin GPU scale endpoint.
        """
        try:
            self.redis_client.set(f"semaphore:limit:{self.name}", new_limit)
            logger.info("gpu_semaphore_scaled", semaphore=self.name, new_limit=new_limit)
        except Exception:
            logger.exception("gpu_semaphore_scale_error", semaphore=self.name)
