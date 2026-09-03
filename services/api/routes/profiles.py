from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..models import Profile, ProfileCreate, UserRole
from ..security import get_current_user
from ..services.profiles import get_profile_by_id, get_profile_by_user_id, update_profile

router = APIRouter(prefix="/profiles", tags=["Profiles"])


@router.get("/me", response_model=Profile)
def read_my_profile(current_user: Annotated[dict, Depends(get_current_user)]):
    profile = get_profile_by_user_id(current_user["id"])
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


@router.put("/me", response_model=Profile)
def update_my_profile(
    profile_in: ProfileCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    profile = get_profile_by_user_id(current_user["id"])
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return update_profile(profile["id"], profile_in)


@router.get("/{profile_id}", response_model=Profile)
def read_profile(profile_id: int, current_user: Annotated[dict, Depends(get_current_user)]):
    profile = get_profile_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    if current_user["id"] != profile["user_id"] and current_user["role"] != UserRole.admin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return profile
