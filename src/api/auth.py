import logging
import os

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

logger = logging.getLogger(__name__)

_api_key = os.getenv("API_KEY")
if not _api_key:
    logger.warning("API_KEY not set — admin endpoints will reject all requests")
    _api_key = ""  # empty string ensures no key will match

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def verify_api_key(key: str = Security(api_key_header)):
    if not _api_key or key != _api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate API Key")
