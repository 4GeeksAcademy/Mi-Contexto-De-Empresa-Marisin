import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..database import auth_db_lock, password_reset_tokens_table, users_table
from .. import rate_limit
from ..email import send_password_reset_email
from ..schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    MeResponse,
    ProfilePublic,
    ResetPasswordRequest,
)
from ..security import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_user_password,
)
from ..services.profiles import get_profile_by_user_id
from ..services.users import get_user_by_email

router = APIRouter(prefix="/auth", tags=["Auth"])

logger = logging.getLogger(__name__)
# Eventos de seguridad (D14): email resumido e IP; nunca el email en claro ni la contraseña.
security_logger = logging.getLogger("api.security")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _too_many_attempts(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=rate_limit.TOO_MANY_ATTEMPTS_DETAIL,
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login", response_model=LoginResponse)
def login(credentials: LoginRequest, request: Request):
    ip = rate_limit.client_ip(request)
    email = rate_limit.normalize_email(str(credentials.email))
    pair = (ip, email)
    retry_after = max(
        rate_limit.login_pair_limiter.retry_after(pair) or 0,
        rate_limit.login_ip_limiter.retry_after(ip) or 0,
    )
    if retry_after:
        security_logger.warning("login_rate_limited email_hash=%s ip=%s retry_after=%s",
                                rate_limit.email_hash(email), ip, retry_after)
        raise _too_many_attempts(retry_after)

    user = get_user_by_email(str(credentials.email))
    if not user or not verify_user_password(credentials.password, user):
        rate_limit.login_pair_limiter.hit(pair)
        rate_limit.login_ip_limiter.hit(ip)
        security_logger.warning("login_failed email_hash=%s ip=%s", rate_limit.email_hash(email), ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    rate_limit.login_pair_limiter.reset(pair)
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return LoginResponse(access_token=create_access_token(user["id"]))


@router.get("/me", response_model=MeResponse)
def read_me(current_user: Annotated[dict, Depends(get_current_user)]):
    profile = get_profile_by_user_id(current_user["id"])
    return MeResponse(
        email=current_user["email"],
        profile=ProfilePublic.model_validate(profile) if profile else None,
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
def forgot_password(payload: ForgotPasswordRequest, request: Request):
    email = payload.email.strip().lower()
    ip = rate_limit.client_ip(request)
    pair = (ip, email)
    retry_after = rate_limit.forgot_password_limiter.retry_after(pair)
    if retry_after:
        security_logger.warning("password_reset_rate_limited email_hash=%s ip=%s retry_after=%s",
                                rate_limit.email_hash(email), ip, retry_after)
        raise _too_many_attempts(retry_after)
    rate_limit.forgot_password_limiter.hit(pair)
    security_logger.info("password_reset_requested email_hash=%s ip=%s", rate_limit.email_hash(email), ip)
    user = get_user_by_email(email)
    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = _now() + timedelta(minutes=30)
        with auth_db_lock:
            password_reset_tokens_table.insert({
                "token_hash": token_hash,
                "user_id": user["id"],
                "expires_at": expires_at.isoformat(),
                "used_at": None,
            })
        try:
            send_password_reset_email(email, raw_token)
        except Exception:
            logger.exception("No se pudo enviar el correo de recuperación")
    return MessageResponse(
        message="Si esa dirección está registrada, recibirás un correo con instrucciones."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
def reset_password(payload: ResetPasswordRequest):
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    with auth_db_lock:
        token_record = next(
            (item for item in password_reset_tokens_table.all() if item["token_hash"] == token_hash),
            None,
        )
        if not token_record:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        expires_at = datetime.fromisoformat(token_record["expires_at"])
        if token_record.get("used_at") or expires_at <= _now():
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        
        user = users_table.get(doc_id=token_record["user_id"])
        if not user:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        
        new_hashed = get_password_hash(payload.new_password)
        users_table.update({"hashed_password": new_hashed}, doc_ids=[user.doc_id])
        password_reset_tokens_table.update({"used_at": _now().isoformat()}, doc_ids=[token_record.doc_id])
    return MessageResponse(message="Password reset successfully")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
def change_password(payload: ChangePasswordRequest, current_user: Annotated[dict, Depends(get_current_user)]):
    if not verify_user_password(payload.current_password, current_user):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    
    new_hashed = get_password_hash(payload.new_password)
    users_table.update(
        {"hashed_password": new_hashed},
        doc_ids=[current_user["id"]],
    )
    return MessageResponse(message="Password changed successfully")