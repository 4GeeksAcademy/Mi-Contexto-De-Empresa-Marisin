import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from ..models import LoginRequest, Token, UserResponse, UserRole, UserUpdate
from ..security import password_context
from ..services.users import (
    create_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)
from ..models import UserCreate

router = APIRouter(prefix="/users", tags=["Users"])

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-development-secret")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")


def _public_user(user: dict) -> dict:
    return {key: value for key, value in user.items() if key != "hashed_password"}


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
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


@router.post("/login", response_model=Token)
def login(credentials: LoginRequest):
    user = get_user_by_email(str(credentials.email))
    if not user or not password_context.verify(credentials.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Inactive user")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = jwt.encode(
        {"sub": str(user["id"]), "exp": expires_at}, JWT_SECRET, algorithm=JWT_ALGORITHM
    )
    return Token(access_token=access_token)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate):
    if get_user_by_email(str(user_in.email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    return _public_user(create_user(user_in))


@router.get("", response_model=list[UserResponse])
def get_users(_: Annotated[dict, Depends(get_current_user)]):
    return [_public_user(user) for user in list_users()]


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, _: Annotated[dict, Depends(get_current_user)]):
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _public_user(user)


@router.put("/{user_id}", response_model=UserResponse)
def put_user(
    user_id: int,
    user_in: UserUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if current_user["id"] != user_id and current_user["role"] != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if user_in.role is not None and current_user["role"] != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only administrators can change roles")
    if user_in.email and user_in.email != target_user["email"]:
        if get_user_by_email(str(user_in.email)):
            raise HTTPException(status_code=409, detail="Email already registered")

    return _public_user(update_user(user_id, user_in))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(user_id: int, current_user: Annotated[dict, Depends(get_current_user)]):
    if current_user["id"] != user_id and current_user["role"] != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")