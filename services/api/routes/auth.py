import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..database import auth_db_lock, password_reset_tokens_table, users_table
from ..email import send_password_reset_email
from ..models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ResetPasswordRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

logger = logging.getLogger(__name__)


def _now() -> datetime:
  return datetime.now(timezone.utc)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
  email = payload.email.strip().lower()
  user = next((item for item in users_table.all() if item["email"] == email), None)
  if not user or not user.get("is_active", True) or not verify_password(payload.password, user["password_hash"]):
    raise HTTPException(status_code=401, detail="Invalid email or password")
  return {"access_token": create_access_token(user.doc_id)}


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(payload: ForgotPasswordRequest):
  email = payload.email.strip().lower()
  user = next((item for item in users_table.all() if item["email"] == email), None)
  if user:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = _now() + timedelta(minutes=30)
    with auth_db_lock:
      password_reset_tokens_table.insert({
          "token_hash": token_hash,
          "user_id": user.doc_id,
          "expires_at": expires_at.isoformat(),
          "used_at": None,
      })
    try:
      send_password_reset_email(email, raw_token)
    except Exception:
      # La respuesta debe ser genérica para no revelar si el correo existe; el fallo solo se registra.
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
    users_table.update({"password_hash": hash_password(payload.new_password)}, doc_ids=[user.doc_id])
    password_reset_tokens_table.update({"used_at": _now().isoformat()}, doc_ids=[token_record.doc_id])
  return {"message": "Password reset successfully"}


@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password(payload: ChangePasswordRequest, current_user=Depends(get_current_user)):
  if not verify_password(payload.current_password, current_user["password_hash"]):
    raise HTTPException(status_code=400, detail="Current password is incorrect")
  if payload.current_password == payload.new_password:
    raise HTTPException(status_code=400, detail="New password must be different")
  users_table.update(
      {"password_hash": hash_password(payload.new_password)},
      doc_ids=[current_user["id"]],
  )
  return {"message": "Password changed successfully"}