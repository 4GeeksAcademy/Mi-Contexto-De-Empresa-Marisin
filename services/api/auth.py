import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import users_table

PASSWORD_ITERATIONS = 600_000
SESSION_TTL_SECONDS = 8 * 60 * 60
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
  salt = secrets.token_bytes(16)
  digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
  return "$".join([
      "pbkdf2_sha256",
      str(PASSWORD_ITERATIONS),
      base64.urlsafe_b64encode(salt).decode(),
      base64.urlsafe_b64encode(digest).decode(),
  ])


def verify_password(password: str, encoded_password: str) -> bool:
  try:
    algorithm, iterations, encoded_salt, encoded_digest = encoded_password.split("$")
    if algorithm != "pbkdf2_sha256":
      return False
    salt = base64.urlsafe_b64decode(encoded_salt.encode())
    expected = base64.urlsafe_b64decode(encoded_digest.encode())
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
    return hmac.compare_digest(actual, expected)
  except (ValueError, TypeError):
    return False


def _signing_secret() -> bytes:
  secret = os.getenv("AUTH_SECRET")
  if not secret:
    raise RuntimeError("AUTH_SECRET must be configured")
  return secret.encode()


def create_access_token(user_id: int) -> str:
  payload = {"sub": str(user_id), "exp": int(time.time()) + SESSION_TTL_SECONDS}
  encoded_payload = base64.urlsafe_b64encode(
      json.dumps(payload, separators=(",", ":")).encode()
  ).rstrip(b"=")
  signature = hmac.new(_signing_secret(), encoded_payload, hashlib.sha256).digest()
  encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
  return f"{encoded_payload.decode()}.{encoded_signature.decode()}"


def _decode_part(value: str) -> bytes:
  return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Dict[str, Any]:
  unauthorized = HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="Invalid or missing authentication token",
      headers={"WWW-Authenticate": "Bearer"},
  )
  if credentials is None or credentials.scheme.lower() != "bearer":
    raise unauthorized
  try:
    encoded_payload, encoded_signature = credentials.credentials.split(".")
    expected_signature = hmac.new(_signing_secret(), encoded_payload.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected_signature, _decode_part(encoded_signature)):
      raise unauthorized
    payload = json.loads(_decode_part(encoded_payload))
    if int(payload["exp"]) <= int(time.time()):
      raise unauthorized
    user = users_table.get(doc_id=int(payload["sub"]))
  except (ValueError, KeyError, TypeError, json.JSONDecodeError, RuntimeError):
    raise unauthorized
  if not user or not user.get("is_active", True):
    raise unauthorized
  return {**user, "id": int(payload["sub"])}