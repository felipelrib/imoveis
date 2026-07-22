import time

from infra.logging import get_logger

logger = get_logger(__name__)

RECORD_FAILURE_SCRIPT = """
local key = KEYS[1]
local threshold = tonumber(ARGV[1])
local cooldown = tonumber(ARGV[2])

-- If already open, no-op
if redis.call('EXISTS', key .. ':open') == 1 then
    return 0
end

local count = redis.call('INCR', key .. ':failures')
redis.call('EXPIRE', key .. ':failures', cooldown * 2)

if count >= threshold then
    redis.call('SET', key .. ':open', '1', 'EX', tonumber(cooldown))
    return 1  -- circuit just opened
end
return 0
"""


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
        from infra.redis_client import get_redis

        self.redis_client = get_redis()
        
        if self.redis_client:
            self._record_failure_script = self.redis_client.register_script(RECORD_FAILURE_SCRIPT)
        else:
            self._record_failure_script = None

    def is_open(self) -> bool:
        """Check if the circuit breaker is currently open."""
        if not self.redis_client:
            return False
        return self.redis_client.exists(f"circuit_breaker:{self.platform}:open") == 1

    def record_failure(self) -> bool:
        """Record a failure in the circuit breaker. Returns True if this failure opened the circuit."""
        if not self._record_failure_script:
            return False
            
        opened = self._record_failure_script(
            keys=[f"circuit_breaker:{self.platform}"],
            args=[self.failure_threshold, self.cooldown_seconds]
        )
        if opened:
            logger.warning("circuit_breaker_opened", platform=self.platform)
        return bool(opened)

    def record_success(self) -> None:
        """Record a success in the circuit breaker."""
        if not self.redis_client:
            return
        
        # Reset state on success
        self.redis_client.delete(
            f"circuit_breaker:{self.platform}:open",
            f"circuit_breaker:{self.platform}:failures"
        )
