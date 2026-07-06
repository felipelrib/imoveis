import logging
from typing import Optional
import redis
import time
from src.infra.redis_client import get_redis

logger = logging.getLogger(__name__)

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
        self.redis_client = get_redis()
        self._key = f"circuit:{platform}"

    def _get_state(self) -> dict:
        """Get current circuit breaker state from Redis."""
        try:
            data = self.redis_client.get(self._key)
            if data is None:
                return {"failures": 0, "opened": False, "last_failure": None}
            else:
                # Supondo que os dados estejam em formato JSON
                import json
                return json.loads(data)
        except Exception as e:
            logger.error(f"Error getting circuit breaker state for {self.platform}: {e}")
            # Fallback para estado padrão em caso de falha Redis
            return {"failures": 0, "opened": False, "last_failure": None}

    def _set_state(self, state: dict) -> None:
        """Set circuit breaker state in Redis."""
        try:
            import json
            self.redis_client.setex(self._key, self.cooldown_seconds, json.dumps(state))
        except Exception as e:
            logger.error(f"Error setting circuit breaker state for {self.platform}: {e}")
            # Não falhar a operação em caso de falha Redis

    def is_open(self) -> bool:
        """Check if circuit is open."""
        try:
            state = self._get_state()
            return state["opened"]
        except Exception as e:
            logger.error(f"Error checking circuit breaker state for {self.platform}: {e}")
            # Fallback para considerar o circuito fechado em caso de falha
            return False

    def record_failure(self) -> None:
        """Record a failure."""
        try:
            state = self._get_state()
            state["failures"] += 1
            state["last_failure"] = int(time.time())
            
            if state["failures"] >= self.failure_threshold:
                state["opened"] = True
                
            self._set_state(state)
        except Exception as e:
            logger.error(f"Error recording failure for circuit breaker {self.platform}: {e}")

    def record_success(self) -> None:
        """Record a success."""
        try:
            state = self._get_state()
            if state["opened"]:
                # Reset the circuit
                state["failures"] = 0
                state["opened"] = False
                state["last_failure"] = None
                self._set_state(state)
        except Exception as e:
            logger.error(f"Error recording success for circuit breaker {self.platform}: {e}")

    def can_attempt(self) -> bool:
        """Check if we can attempt an operation."""
        try:
            state = self._get_state()
            
            if not state["opened"]:
                return True
                
            # Check if cooldown has passed
            if state["last_failure"] is not None:
                import time
                if time.time() - state["last_failure"] > self.cooldown_seconds:
                    # Reset the circuit after cooldown
                    state["failures"] = 0
                    state["opened"] = False
                    state["last_failure"] = None
                    self._set_state(state)
                    return True
                    
            return False
        except Exception as e:
            logger.error(f"Error checking if can attempt for circuit breaker {self.platform}: {e}")
            # Fallback para permitir tentativas em caso de falha Redis
            return True
