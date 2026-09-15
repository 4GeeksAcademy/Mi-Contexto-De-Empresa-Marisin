import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

load_dotenv()

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
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
    if not user or not user["is_active"]:
        raise credentials_error
    return user