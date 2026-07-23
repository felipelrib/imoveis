import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from src.infra.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

JWT_SECRET = os.environ.get("JWT_SECRET", "super-secret-key-for-dev")
JWT_ALGORITHM = "HS256"
CREDENTIALS_INVALID = "Could not validate credentials"

_AUTH_UNAUTHORIZED = {status.HTTP_401_UNAUTHORIZED: {"description": CREDENTIALS_INVALID}}
_AUTH_FORBIDDEN = {status.HTTP_403_FORBIDDEN: {"description": "Not authorized"}}


class Token(BaseModel):
    access_token: str
    token_type: str


def verify_api_key(key: Annotated[str, Security(api_key_header)]):
    _api_key = os.environ.get("API_KEY", "")
    if not _api_key:
        logger.warning("auth_failed", reason="api_key_not_set")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin API key not configured")

    if key != _api_key:
        logger.warning("auth_failed", reason="invalid_api_key")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate API Key")

    return key


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_jwt(token: Annotated[str, Depends(oauth2_scheme)]):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENTIALS_INVALID)
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENTIALS_INVALID)


def verify_admin_jwt(token: Annotated[str, Depends(oauth2_scheme)]):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None or role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as admin")
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENTIALS_INVALID)


@router.post("/token", response_model=Token)
def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """Issue a JWT for a regular user (mock authentication)."""
    user_id = form_data.username
    access_token_expires = timedelta(days=30)
    access_token = create_access_token(
        data={"sub": user_id, "role": "user"}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post(
    "/admin/login",
    response_model=Token,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Incorrect admin credentials"},
        **_AUTH_FORBIDDEN,
    },
)
def login_for_admin_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """Issue a short-lived JWT for admin access."""
    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_pass = os.environ.get("ADMIN_PASS", "admin")

    if form_data.username != admin_user or form_data.password != admin_pass:
        raise HTTPException(status_code=401, detail="Incorrect admin credentials")

    access_token_expires = timedelta(minutes=15)
    access_token = create_access_token(
        data={"sub": admin_user, "role": "admin"}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
