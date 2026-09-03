from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..models import LoginRequest, MeResponse, Token
from ..security import create_access_token, get_current_user, password_context
from ..services.profiles import get_profile_by_user_id
from ..services.users import get_user_by_email

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=Token)
def login(credentials: LoginRequest):
    user = get_user_by_email(str(credentials.email))
    if not user or not password_context.verify(credentials.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return Token(access_token=create_access_token(user["id"]))


@router.get("/me", response_model=MeResponse)
def read_me(current_user: Annotated[dict, Depends(get_current_user)]):
    profile = get_profile_by_user_id(current_user["id"])
    return MeResponse(email=current_user["email"], role=current_user["role"], profile=profile)
