import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

load_dotenv()

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return password_context.hash(password)


def verify_user_password(password: str, user: dict) -> bool:
    stored_hash = user.get("hashed_password") or user.get("password_hash")
    if not isinstance(stored_hash, str) or not stored_hash:
        return False
    try:
        return password_context.verify(password, stored_hash)
    except (TypeError, ValueError):
        return False


JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Auth centralizado en /auth/login: usuarios y perfiles viven solo en TinyDB.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "exp": expires_at}, JWT_SECRET, algorithm=JWT_ALGORITHM
    )


def _user_from_token(token: str) -> dict:
    from .services.users import get_user_by_id

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub", ""))
        if user_id < 1:
            raise credentials_error
    except (JWTError, TypeError, ValueError) as error:
        raise credentials_error from error

    user = get_user_by_id(user_id)
    if not user or not user.get("is_active", True):
        raise credentials_error
    return user


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    return _user_from_token(token)


# --------------------------------------------------------------------------- #
# Autorización por rol (D8): los roles son la frontera de confianza.
#   user            → cuenta externa (cliente B2C/B2B o registro público)
#   manager, admin  → personal de TrackFlow
# --------------------------------------------------------------------------- #
logger = logging.getLogger("api.security")

STAFF_ROLES = frozenset({"admin", "manager"})
STAFF_ONLY_DETAIL = "Esta operación es solo para el personal de TrackFlow."


def require_roles(*roles: str):
    """Dependencia: devuelve el usuario autenticado si su rol está en `roles`; si no, 403."""
    allowed = frozenset(roles)

    def dependency(user: Annotated[dict, Depends(get_current_user)]) -> dict:
        if user.get("role") not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STAFF_ONLY_DETAIL)
        return user

    return dependency


require_staff = require_roles(*STAFF_ROLES)


# --------------------------------------------------------------------------- #
# Identidad de servicio del servidor MCP (D9)
# --------------------------------------------------------------------------- #
SERVICE_KEY_ENV = "TRACKFLOW_SERVICE_KEY"
SERVICE_KEY_HEADER = "X-Service-Key"
SERVICE_KEY_MIN_LENGTH = 32
SERVICE_IDENTITY = {"id": 0, "role": "service", "service": "trackflow-mcp"}

oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
service_key_header = APIKeyHeader(name=SERVICE_KEY_HEADER, auto_error=False)


def configured_service_key() -> str | None:
    """La clave de servicio si está configurada y es lo bastante larga; si no, None (vía desactivada)."""
    key = os.getenv(SERVICE_KEY_ENV, "")
    return key if len(key) >= SERVICE_KEY_MIN_LENGTH else None


def warn_if_service_key_missing() -> None:
    if configured_service_key() is None:
        logger.warning(
            "%s ausente o con menos de %d caracteres: la vía de servicio del MCP está desactivada",
            SERVICE_KEY_ENV,
            SERVICE_KEY_MIN_LENGTH,
        )


def require_staff_or_service(
    token: Annotated[str | None, Depends(oauth2_optional)],
    service_key: Annotated[str | None, Depends(service_key_header)],
) -> dict:
    """JWT de staff o `X-Service-Key` válida (el servidor MCP). Una clave enviada y no válida → 401."""
    if service_key is not None:
        expected = configured_service_key()
        if expected is not None and hmac.compare_digest(service_key.encode(), expected.encode()):
            return dict(SERVICE_IDENTITY)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial de servicio no válida.",
        )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = _user_from_token(token)
    if user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STAFF_ONLY_DETAIL)
    return user


warn_if_service_key_missing()
