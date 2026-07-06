"""Redis-backed circuit breaker for multi-process safety.

Keys per platform: ``cb:<platform>``
Stored value: JSON ``{failures, last_failure_ts, open_until}``
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Optional

import redis

from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)


class RedisCircuitBreaker:
    """Circuit breaker whose state lives in Redis.

    Parameters
    ----------
    platform:
        Platform identifier (used as Redis key suffix and in logs).
    failure_threshold:
        Number of consecutive failures before the circuit opens.
    cooldown_seconds:
        How long the circuit stays open.
    redis_client:
        Optional pre-built ``redis.Redis`` instance.  Defaults to the
        centralized client returned by ``get_redis()``.
    on_trip:
        Optional callback invoked with ``(platform, failure_count,
        cooldown_seconds)`` when the circuit opens.
    """

    def __init__(
        self,
        platform: str = "default",
        failure_threshold: int = 5,
        cooldown_seconds: int = 300,
        redis_client: Optional[redis.Redis] = None,
        on_trip: Optional[Callable[[str, int, float], None]] = None,
    ) -> None:
        self.r: redis.Redis = redis_client or get_redis()
        self.platform_name: str = platform
        self.key: str = f"cb:{platform}"
        self.failure_threshold: int = int(failure_threshold)
        self.cooldown_seconds: int = int(cooldown_seconds)
        self.on_trip = on_trip
        # Ensure key exists
        if not self.r.exists(self.key):
            self._set(self._empty_state())

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _empty_state() -> Dict[str, Any]:
        return {"failures": 0, "last_failure_ts": 0, "open_until": 0}

    def _get(self) -> Dict[str, Any]:
        raw = self.r.get(self.key)
        if not raw:
            return self._empty_state()
        return json.loads(raw)  # type: ignore[arg-type]

    def _set(self, data: Dict[str, Any]) -> None:
        self.r.set(self.key, json.dumps(data))

    # -- Public API ---------------------------------------------------------

    def record_failure(self) -> None:
        data = self._get()
        data["failures"] = data.get("failures", 0) + 1
        data["last_failure_ts"] = time.time()
        if data["failures"] >= self.failure_threshold:
            data["open_until"] = time.time() + self.cooldown_seconds
            logger.warning(
                "circuit_breaker_tripped",
                platform=self.platform_name,
                failures=data["failures"],
                cooldown_seconds=self.cooldown_seconds,
            )
            if self.on_trip is not None:
                self.on_trip(
                    self.platform_name,
                    data["failures"],
                    float(self.cooldown_seconds),
                )
        self._set(data)

    def record_success(self) -> None:
        self._set(self._empty_state())

    def is_open(self) -> bool:
        data = self._get()
        return time.time() < data.get("open_until", 0)

    def time_left(self) -> float:
        data = self._get()
        return max(0.0, data.get("open_until", 0) - time.time())
