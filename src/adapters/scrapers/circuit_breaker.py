"""In-process circuit breaker with optional trip callback.

Thread-safety is out-of-scope for this skeleton; use
``RedisCircuitBreaker`` for multi-process deployments.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from infra.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CircuitBreakerState:
    failures: int = 0
    last_failure_ts: float = 0.0
    open_until: float = 0.0


class CircuitBreaker:
    """Simple in-process circuit breaker.

    Parameters
    ----------
    platform_name:
        Human-readable identifier for the platform this breaker guards.
    failure_threshold:
        Number of consecutive failures before the circuit opens.
    cooldown_seconds:
        How long the circuit stays open before allowing a retry.
    on_trip:
        Optional callback invoked with ``(platform_name, failure_count,
        cooldown_seconds)`` when the circuit opens.
    """

    def __init__(
        self,
        platform_name: str = "unknown",
        failure_threshold: int = 5,
        cooldown_seconds: int = 300,
        on_trip: Optional[Callable[[str, int, float], None]] = None,
    ) -> None:
        self.platform_name = platform_name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.on_trip = on_trip
        self.state = CircuitBreakerState()

    def record_failure(self) -> None:
        self.state.failures += 1
        self.state.last_failure_ts = time.time()
        if self.state.failures >= self.failure_threshold:
            self.state.open_until = time.time() + self.cooldown_seconds
            logger.warning(
                "circuit_breaker_tripped",
                platform=self.platform_name,
                failures=self.state.failures,
                cooldown_seconds=self.cooldown_seconds,
            )
            if self.on_trip is not None:
                self.on_trip(
                    self.platform_name,
                    self.state.failures,
                    float(self.cooldown_seconds),
                )

    def record_success(self) -> None:
        self.state = CircuitBreakerState()

    def is_open(self) -> bool:
        return time.time() < self.state.open_until

    def time_left(self) -> float:
        return max(0.0, self.state.open_until - time.time())
