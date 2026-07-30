
from infra.logging import get_logger

logger = get_logger(__name__)

RECORD_FAILURE_SCRIPT = """
local key = KEYS[1]
local open_key = KEYS[2]
local threshold = tonumber(ARGV[1])
local cooldown = tonumber(ARGV[2])

-- If already open, no-op
if redis.call('EXISTS', open_key) == 1 then
    return 0
end

local count = redis.call('INCR', key .. ':failures')
redis.call('EXPIRE', key .. ':failures', cooldown * 2)

if count >= threshold then
    redis.call('SET', open_key, '1', 'EX', tonumber(cooldown))
    return 1  -- circuit just opened
end
return 0
"""

_DEFAULT_REASON = "default"


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
        self._known_reasons: set[str] = set()
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

    def record_failure(
        self,
        reason: str = _DEFAULT_REASON,
        threshold: int | None = None,
        cooldown: int | None = None,
    ) -> bool:
        """Record a failure in the circuit breaker.

        ``reason`` buckets the failure into its own consecutive-failure
        counter — e.g. sustained Cloudflare 403 blocks (``reason=
        "cloudflare_403"``) accumulate separately from 5xx/429 failures
        (the ``"default"`` reason), optionally with their own
        ``threshold``/``cooldown`` for different open/close timing. Any
        reason tripping its threshold opens the SAME shared ``:open`` flag
        for the platform, so ``is_open()`` still gates every request
        regardless of which failure mode caused the trip.

        Returns True if this call opened the circuit.
        """
        if not self._record_failure_script:
            return False

        self._known_reasons.add(reason)
        effective_threshold = threshold if threshold is not None else self.failure_threshold
        effective_cooldown = cooldown if cooldown is not None else self.cooldown_seconds
        counter_key = (
            f"circuit_breaker:{self.platform}"
            if reason == _DEFAULT_REASON
            else f"circuit_breaker:{self.platform}:{reason}"
        )

        opened = self._record_failure_script(
            keys=[counter_key, f"circuit_breaker:{self.platform}:open"],
            args=[effective_threshold, effective_cooldown]
        )
        if opened:
            logger.warning("circuit_breaker_opened", platform=self.platform, reason=reason)
        return bool(opened)

    def record_success(self) -> None:
        """Record a success in the circuit breaker."""
        if not self.redis_client:
            return

        # Reset state on success — clear the shared open flag, the default
        # failure counter, and any reason-specific counters used so far.
        keys = [
            f"circuit_breaker:{self.platform}:open",
            f"circuit_breaker:{self.platform}:failures",
        ]
        keys.extend(
            f"circuit_breaker:{self.platform}:{reason}:failures"
            for reason in self._known_reasons
            if reason != _DEFAULT_REASON
        )
        self.redis_client.delete(*keys)
