import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..database import auth_db_lock, password_reset_tokens_table, users_table
from ..email import send_password_reset_email
from ..models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ResetPasswordRequest,
)
from ..security import create_access_token, get_current_user, hash_password, password_context, verify_password
from ..services.profiles import get_profile_by_user_id
from ..services.users import get_user_by_email

router = APIRouter(prefix="/auth", tags=["Auth"])

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/login", response_model=LoginResponse)
def login(credentials: LoginRequest):
    user = get_user_by_email(str(credentials.email))
    if not user or not password_context.verify(credentials.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return LoginResponse(access_token=create_access_token(user["id"]))


@router.get("/me", response_model=MeResponse)
def read_me(current_user: Annotated[dict, Depends(get_current_user)]):
    profile = get_profile_by_user_id(current_user["id"])
    return MeResponse(email=current_user["email"], role=current_user["role"], profile=profile)


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(payload: ForgotPasswordRequest):
    email = payload.email.strip().lower()
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
    return {"message": "Si esa dirección está registrada, recibirás un correo con instrucciones."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
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
        
        new_hashed = password_context.hash(payload.new_password)
        users_table.update({"hashed_password": new_hashed}, doc_ids=[user.doc_id])
        password_reset_tokens_table.update({"used_at": _now().isoformat()}, doc_ids=[token_record.doc_id])
    return {"message": "Password reset successfully"}


@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password(payload: ChangePasswordRequest, current_user: Annotated[dict, Depends(get_current_user)]):
    if not password_context.verify(payload.current_password, current_user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    
    new_hashed = password_context.hash(payload.new_password)
    users_table.update(
        {"hashed_password": new_hashed},
        doc_ids=[current_user["id"]],
    )
    return {"message": "Password changed successfully"}
