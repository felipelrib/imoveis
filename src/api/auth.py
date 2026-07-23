from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)
api_key_header_optional = APIKeyHeader(name="X-API-Key", auto_error=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

JWT_ALGORITHM = "HS256"
CREDENTIALS_INVALID = "Could not validate credentials"

_AUTH_UNAUTHORIZED = {status.HTTP_401_UNAUTHORIZED: {"description": CREDENTIALS_INVALID}}
_AUTH_FORBIDDEN = {status.HTTP_403_FORBIDDEN: {"description": "Not authorized"}}


class Token(BaseModel):
    access_token: str
    token_type: str


class Principal(BaseModel, frozen=True):
    """Stable single-tenant principal exposed to downstream handlers (AD-11)."""

    id: str
    method: str  # "api_key" | "admin_jwt"


def _auth_cfg():
    return get_config().auth


def _jwt_secret() -> str:
    secret = _auth_cfg().jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="JWT secret not configured",
        )
    return secret


def verify_api_key(key: Annotated[str, Security(api_key_header)]) -> Principal:
    """Validate ``X-API-Key`` against AppConfig and return a stable principal."""
    cfg = _auth_cfg()
    if not cfg.api_key:
        logger.warning("auth_failed", reason="api_key_not_set")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key not configured",
        )

    if key != cfg.api_key:
        logger.warning("auth_failed", reason="invalid_api_key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate API Key",
        )

    return Principal(id=cfg.principal_id, method="api_key")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_jwt(token: Annotated[str, Depends(oauth2_scheme)]):
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENTIALS_INVALID)
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENTIALS_INVALID)


def verify_admin_jwt(token: Annotated[str, Depends(oauth2_scheme)]):
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None or role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as admin")
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENTIALS_INVALID)


def _principal_from_admin_jwt(token: str) -> Principal:
    """Decode an admin JWT and map to the configured stable principal."""
    cfg = _auth_cfg()
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENTIALS_INVALID)
    user_id: str = payload.get("sub")
    role: str = payload.get("role")
    if user_id is None or role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as admin")
    return Principal(id=cfg.principal_id, method="admin_jwt")


def verify_admin_access(
    api_key: Annotated[Optional[str], Security(api_key_header_optional)] = None,
    token: Annotated[Optional[str], Depends(oauth2_scheme_optional)] = None,
) -> Principal:
    """Edge guard for ``/admin``: valid AppConfig API key or admin JWT.

    Both paths resolve to the same ``auth.principal_id`` (AD-11). API key is the
    canonical credential; admin JWT remains until the Story 2.2 SPA gate.
    """
    cfg = _auth_cfg()

    if api_key is not None:
        if not cfg.api_key:
            logger.warning("auth_failed", reason="api_key_not_set")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin API key not configured",
            )
        if api_key != cfg.api_key:
            logger.warning("auth_failed", reason="invalid_api_key")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate API Key",
            )
        return Principal(id=cfg.principal_id, method="api_key")

    if token:
        return _principal_from_admin_jwt(token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=CREDENTIALS_INVALID,
        headers={"WWW-Authenticate": "Bearer"},
    )


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
    cfg = _auth_cfg()

    if form_data.username != cfg.admin_user or form_data.password != cfg.admin_pass:
        raise HTTPException(status_code=401, detail="Incorrect admin credentials")

    access_token_expires = timedelta(minutes=15)
    access_token = create_access_token(
        data={"sub": cfg.admin_user, "role": "admin"}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
