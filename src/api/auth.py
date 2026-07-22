import os

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from src.infra.logging import get_logger

logger = get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def verify_api_key(key: str = Security(api_key_header)):
    _api_key = os.environ.get("API_KEY", "")
    if not _api_key:
        logger.warning("auth_failed", reason="api_key_not_set")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin API key not configured")
    
    if key != _api_key:
        logger.warning("auth_failed", reason="invalid_api_key")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate API Key")
        
    return key
