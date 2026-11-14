from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..models import UserCreate, UserListItem, UserPublic, UserRole, UserUpdate
from ..schemas import MessageResponse
from ..security import get_current_user
from ..services.users import (
    create_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)
router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate):
    if get_user_by_email(str(user_in.email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    create_user(user_in)
    return MessageResponse(message="Cuenta creada correctamente")


@router.get("", response_model=list[UserListItem])
def get_users(_: Annotated[dict, Depends(get_current_user)]):
    return [UserListItem.model_validate(user) for user in list_users()]


@router.get("/{user_id}", response_model=UserPublic)
def get_user(user_id: int, _: Annotated[dict, Depends(get_current_user)]):
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic.model_validate(user)


@router.put("/{user_id}", response_model=UserPublic)
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

    updated_user = update_user(user_id, user_in)
    if updated_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic.model_validate(updated_user)


@router.delete(
    "/{user_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_user(user_id: int, current_user: Annotated[dict, Depends(get_current_user)]):
    if current_user["id"] != user_id and current_user["role"] != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")