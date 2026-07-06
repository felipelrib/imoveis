import redis
import json
from typing import Dict, Any
from dataclasses import dataclass
import time

@dataclass
class RedisCircuitBreakerState:
    """Represents the state of a Redis circuit breaker."""
    is_open: bool = False
    failure_count: int = 0
    last_failure_time: float = 0.0
    cooldown_end_time: float = 0.0

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
    """

    def __init__(self, platform: str, failure_threshold: int = 5, cooldown_seconds: int = 60):
        self.platform = platform
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.redis_client = None

    def _get_state(self) -> RedisCircuitBreakerState:
        """Get the current state from Redis."""
        if not self.redis_client:
            return RedisCircuitBreakerState()
            
        try:
            key = f"circuit_breaker:{self.platform}"
            data = self.redis_client.get(key)
            if data:
                parsed = json.loads(data)
                return RedisCircuitBreakerState(**parsed)
        except Exception as e:
            # If we can't read from Redis, return default state
            print(f"Error reading circuit breaker state for {self.platform}: {e}")
            
        return RedisCircuitBreakerState()

    def _set_state(self, state: RedisCircuitBreakerState) -> None:
        """Set the current state in Redis."""
        if not self.redis_client:
            return
            
        try:
            key = f"circuit_breaker:{self.platform}"
            data = json.dumps(state.__dict__)
            # Set with expiration to prevent indefinite storage
            self.redis_client.setex(key, self.cooldown_seconds * 2, data)
        except Exception as e:
            print(f"Error writing circuit breaker state for {self.platform}: {e}")

    def is_open(self) -> bool:
        """Check if the circuit breaker is currently open."""
        state = self._get_state()
        
        if not state.is_open:
            return False
            
        # If we're in cooldown, check if it's time to retry
        if state.cooldown_end_time and time.time() < state.cooldown_end_time:
            return True
            
        # Cooldown expired, reset state
        new_state = RedisCircuitBreakerState()
        self._set_state(new_state)
        return False

    def record_failure(self) -> None:
        """Record a failure in the circuit breaker."""
        if self.is_open():
            return
            
        state = self._get_state()
        state.failure_count += 1
        state.last_failure_time = time.time()
        
        if state.failure_count >= self.failure_threshold:
            state.is_open = True
            state.cooldown_end_time = time.time() + self.cooldown_seconds
        else:
            # Reset failure count to avoid false positives
            state.failure_count = 0
            
        self._set_state(state)

    def record_success(self) -> None:
        """Record a success in the circuit breaker."""
        # Reset state on success
        new_state = RedisCircuitBreakerState()
        self._set_state(new_state)
