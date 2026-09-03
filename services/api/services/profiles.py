from typing import Optional

from tinydb import Query

from ..database import profiles_table
from ..models import ProfileCreate


def create_profile(user_id: int, profile_in: ProfileCreate) -> dict:
    profile_id = profiles_table.insert({"user_id": user_id, **profile_in.model_dump()})
    profiles_table.update({"id": profile_id}, doc_ids=[profile_id])
    return profiles_table.get(doc_id=profile_id)


def get_profile_by_id(profile_id: int) -> Optional[dict]:
    return profiles_table.get(doc_id=profile_id)


def get_profile_by_user_id(user_id: int) -> Optional[dict]:
    return profiles_table.get(Query().user_id == user_id)


def update_profile(profile_id: int, profile_in: ProfileCreate) -> Optional[dict]:
    changes = profile_in.model_dump(exclude_unset=True, exclude_none=True)
    if changes:
        profiles_table.update(changes, doc_ids=[profile_id])
    return get_profile_by_id(profile_id)
