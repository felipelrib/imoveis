import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class CircuitBreakerState:
    """Represents the state of a circuit breaker."""

    is_open: bool = False
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    cooldown_end_time: Optional[float] = None


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
    """

    def __init__(self, platform_name: str, failure_threshold: int = 5, cooldown_seconds: int = 60):
        self.platform_name = platform_name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitBreakerState()

    def is_open(self) -> bool:
        """Check if the circuit breaker is currently open."""
        if not self._state.is_open:
            return False

        # If we're in cooldown, check if it's time to retry
        if self._state.cooldown_end_time and time.time() < self._state.cooldown_end_time:
            return True

        # Cooldown expired, reset state
        self._state = CircuitBreakerState()
        return False

    def record_failure(self) -> None:
        """Record a failure in the circuit breaker."""
        if self.is_open():
            return

        self._state.failure_count += 1
        self._state.last_failure_time = time.time()

        if self._state.failure_count >= self.failure_threshold:
            self._state.is_open = True
            self._state.cooldown_end_time = time.time() + self.cooldown_seconds

    def record_success(self) -> None:
        """Record a success in the circuit breaker."""
        # Reset state on success
        self._state = CircuitBreakerState()
