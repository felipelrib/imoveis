import logging
from dataclasses import dataclass
from typing import Optional
import time

logger = logging.getLogger(__name__)

@dataclass
class CircuitBreakerState:
    """Represents the state of a circuit breaker."""
    failures: int = 0
    opened: bool = False
    last_failure: Optional[float] = None

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
        """Check if circuit is open."""
        try:
            return self._state.opened
        except Exception as e:
            logger.error(f"Error checking circuit breaker state for {self.platform_name}: {e}")
            # Fallback para considerar o circuito fechado em caso de falha
            return False

    def record_failure(self) -> None:
        """Record a failure."""
        try:
            self._state.failures += 1
            self._state.last_failure = time.time()
            
            if self._state.failures >= self.failure_threshold:
                self._state.opened = True
                
            logger.debug(f"Recorded failure for {self.platform_name}. Failures: {self._state.failures}")
        except Exception as e:
            logger.error(f"Error recording failure for circuit breaker {self.platform_name}: {e}")

    def record_success(self) -> None:
        """Record a success."""
        try:
            if self._state.opened:
                # Reset the circuit
                self._state.failures = 0
                self._state.opened = False
                self._state.last_failure = None
                logger.debug(f"Reset circuit breaker for {self.platform_name}")
        except Exception as e:
            logger.error(f"Error recording success for circuit breaker {self.platform_name}: {e}")

    def can_attempt(self) -> bool:
        """Check if we can attempt an operation."""
        try:
            if not self._state.opened:
                return True
                
            # Check if cooldown has passed
            if self._state.last_failure is not None:
                if time.time() - self._state.last_failure > self.cooldown_seconds:
                    # Reset the circuit after cooldown
                    self._state.failures = 0
                    self._state.opened = False
                    self._state.last_failure = None
                    logger.debug(f"Reset circuit breaker for {self.platform_name} after cooldown")
                    return True
                    
            return False
        except Exception as e:
            logger.error(f"Error checking if can attempt for circuit breaker {self.platform_name}: {e}")
            # Fallback para permitir tentativas em caso de falha
            return True
