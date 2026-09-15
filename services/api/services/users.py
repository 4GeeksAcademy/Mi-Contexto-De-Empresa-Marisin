from datetime import datetime, timezone
from typing import Optional

from tinydb import Query

from ..database import profiles_table, users_table
from ..models import UserCreate, UserRole, UserUpdate
from .profiles import create_profile


def create_user(user_in: UserCreate) -> dict:
    """Crea un usuario y su perfil opcional dentro de TinyDB."""
    created_at = datetime.now(timezone.utc).isoformat()
    user_data = {
        "email": str(user_in.email),
        "hashed_password": user_in.hashed_password,
        "is_active": True,
        "role": UserRole.user.value,
        "created_at": created_at,
    }
    user_id = users_table.insert(user_data)
    users_table.update({"id": user_id}, doc_ids=[user_id])

    create_profile(user_id, user_in.profile)

    return get_user_by_id(user_id)


def get_user_by_id(user_id: int) -> Optional[dict]:
    return users_table.get(doc_id=user_id)


def get_user_by_email(email: str) -> Optional[dict]:
    return users_table.get(Query().email == email)


def list_users() -> list[dict]:
    return users_table.all()


def update_user(user_id: int, user_in: UserUpdate) -> Optional[dict]:
    changes = user_in.model_dump(exclude_unset=True, exclude_none=True)
    if "role" in changes:
        changes["role"] = changes["role"].value

    if changes:
        users_table.update(changes, doc_ids=[user_id])
    return get_user_by_id(user_id)


def delete_user(user_id: int) -> bool:
    if not get_user_by_id(user_id):
        return False

    profiles_table.remove(Query().user_id == user_id)
    users_table.remove(doc_ids=[user_id])
    return True
