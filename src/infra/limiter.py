from slowapi import Limiter
from slowapi.util import get_remote_address
from infra.config import get_config

cfg = get_config()
limiter = Limiter(key_func=get_remote_address, storage_uri=cfg.redis.url)
