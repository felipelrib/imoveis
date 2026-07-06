import logging
from typing import Optional
import redis
from src.infra.redis_client import get_redis

logger = logging.getLogger(__name__)

class GPUSemaphore:
    """A Redis-backed counting semaphore to control concurrent GPU jobs.

    Keys:
        semaphore:<name>  — integer counter (current available slots)

    Usage::

        sem = GPUSemaphore()
        if sem.acquire(timeout=30):
            try:
                # Do work
                pass
            finally:
                sem.release()
    """

    def __init__(self, name: str, max_concurrent: int = 1):
        self.name = name
        self.max_concurrent = max_concurrent
        self.redis_client = get_redis()

    @property
    def available(self) -> int:
        """Get number of available slots."""
        try:
            value = self.redis_client.get(f"semaphore:{self.name}")
            return int(value) if value is not None else self.max_concurrent
        except Exception as e:
            logger.error(f"Error getting semaphore value for {self.name}: {e}")
            # Fallback para valor padrão em caso de falha
            return self.max_concurrent

    def acquire(self, timeout: Optional[int] = None) -> bool:
        """Acquire a semaphore slot."""
        try:
            # Usar transação Redis para garantir atomicidade
            pipe = self.redis_client.pipeline()
            pipe.watch(f"semaphore:{self.name}")
            
            current_value = self.redis_client.get(f"semaphore:{self.name}")
            if current_value is None:
                current_value = self.max_concurrent
            else:
                current_value = int(current_value)
                
            if current_value > 0:
                # Reduzir o contador
                pipe.multi()
                pipe.setex(f"semaphore:{self.name}", timeout or 3600, current_value - 1)
                pipe.execute()
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"Error acquiring semaphore for {self.name}: {e}")
            # Fallback para permitir a operação em caso de falha Redis
            return True

    def release(self) -> None:
        """Release a semaphore slot."""
        try:
            # Usar transação Redis para garantir atomicidade
            pipe = self.redis_client.pipeline()
            pipe.watch(f"semaphore:{self.name}")
            
            current_value = self.redis_client.get(f"semaphore:{self.name}")
            if current_value is None:
                current_value = 0
            else:
                current_value = int(current_value)
                
            # Aumentar o contador, mas não ultrapassar o máximo
            new_value = min(current_value + 1, self.max_concurrent)
            
            pipe.multi()
            pipe.setex(f"semaphore:{self.name}", 3600, new_value)
            pipe.execute()
            
        except Exception as e:
            logger.error(f"Error releasing semaphore for {self.name}: {e}")
