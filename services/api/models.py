from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SupplierStatus(str, Enum):
  active = "Active"
  suspended = "Suspended"


class CountryEnum(str, Enum):
  us = "United States"
  es = "Spain"


class SupplierCreate(BaseModel):
  name: str = Field(..., min_length=1, description="Nombre del proveedor")
  country: CountryEnum = Field(..., description="País en el que opera")
  categories: List[str] = Field(
      ..., min_items=1, description="Categorías de productos"
  )
  rate_usd: float = Field(
      ..., gt=0, description="Tarifa vigente (debe ser mayor a 0)"
  )
  status: SupplierStatus = Field(
      default=SupplierStatus.active, description="Estado operativo"
  )


class SupplierUpdateRate(BaseModel):
  rate_usd: float = Field(
      ..., gt=0, description="Nueva tarifa (debe ser mayor a 0)"
  )


class SupplierUpdateStatus(BaseModel):
  status: SupplierStatus = Field(..., description="Nuevo estado del proveedor")


class Supplier(SupplierCreate):
  id: str = Field(..., description="ID único asignado por TinyDB")
  updated_at: str = Field(
      ..., description="Timestamp de la última actualización"
  )


class UserRole(str, Enum):
  admin = "admin"
  manager = "manager"
  user = "user"


class ProfileCreate(BaseModel):
  name: Optional[str] = Field(default=None, min_length=1)
  phone: Optional[str] = None
  address: Optional[str] = None


class Profile(ProfileCreate):
  id: int
  user_id: int


class UserCreate(BaseModel):
  email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
  password: str = Field(..., min_length=8, exclude=True)
  name: Optional[str] = Field(default=None, min_length=1)
  phone: Optional[str] = None
  address: Optional[str] = None

  @property
  def profile(self) -> ProfileCreate:
    return ProfileCreate(name=self.name, phone=self.phone, address=self.address)

  @property
  def hashed_password(self) -> str:
    from .security import password_context

    return password_context.hash(self.password)


class UserUpdate(BaseModel):
  email: Optional[str] = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
  password: Optional[str] = Field(default=None, min_length=8, exclude=True)
  role: Optional[UserRole] = None

  @property
  def hashed_password(self) -> Optional[str]:
    if self.password is None:
      return None

    from .security import password_context

    return password_context.hash(self.password)

  def model_dump(self, **kwargs):
    user_data = super().model_dump(**kwargs)
    password = user_data.pop("password", None)
    if password is not None:
      user_data["hashed_password"] = self.hashed_password
    return user_data


class User(BaseModel):
  id: int
  email: str
  hashed_password: str
  is_active: bool
  role: UserRole
  created_at: str


class UserResponse(BaseModel):
  id: int
  email: str
  is_active: bool
  role: UserRole
  created_at: str


class LoginRequest(BaseModel):
  email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
  password: str


class Token(BaseModel):
  access_token: str
  token_type: str = "bearer"


class MeResponse(BaseModel):
  email: str
  role: UserRole
  profile: Optional[Profile] = None
