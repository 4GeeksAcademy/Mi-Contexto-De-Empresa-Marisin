from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlmodel import Field as SQLField, SQLModel

class SKU(SQLModel, table=True):
    __tablename__ = "skus"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    sku: str = SQLField(index=True, unique=True, description="Código único del SKU")
    name: str = SQLField(..., description="Nombre del producto")
    client_name: str = SQLField(..., description="Cliente B2B propietario del inventario")
    category: str = SQLField(..., description="Categoría del producto")
    reference: str = SQLField(..., description="Referencia interna o del fabricante")


class StockEntry(SQLModel, table=True):
    __tablename__ = "stock_entries"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    sku_id: int = SQLField(foreign_key="skus.id", description="ID relacional del SKU")
    warehouse: str = SQLField(..., description="Almacén de destino: Los Angeles o Zaragoza")
    quantity: int = SQLField(..., gt=0, description="Cantidad que entra")
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    user_uuid: str = SQLField(..., description="UUID del usuario de TinyDB que registró la orden")


class StockExit(SQLModel, table=True):
    __tablename__ = "stock_exits"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    sku_id: int = SQLField(foreign_key="skus.id", description="ID relacional del SKU")
    warehouse: str = SQLField(..., description="Almacén de origen: Los Angeles o Zaragoza")
    quantity: int = SQLField(..., gt=0, description="Cantidad que sale")
    exit_type: str = SQLField(..., description="Tipo de salida (ej. B2C Order, B2B Transfer)")
    tracking_number: Optional[str] = SQLField(default=None, description="Número de seguimiento del transportista")
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    user_uuid: str = SQLField(..., description="UUID del usuario de TinyDB que registró la orden")


class SupplierStatus(str, Enum):
    active = "Active"
    suspended = "Suspended"


class CountryEnum(str, Enum):
    us = "United States"
    es = "Spain"


class SupplierCreate(BaseModel):
    name: str = PydanticField(..., min_length=1, description="Nombre del proveedor")
    country: CountryEnum = PydanticField(..., description="País en el que opera")
    categories: List[str] = PydanticField(..., min_length=1, description="Categorías de productos")
    rate_usd: float = PydanticField(..., gt=0, description="Tarifa vigente (debe ser mayor a 0)")
    status: SupplierStatus = PydanticField(default=SupplierStatus.active, description="Estado operativo")


class SupplierUpdateRate(BaseModel):
    rate_usd: float = PydanticField(..., gt=0, description="Nueva tarifa (debe ser mayor a 0)")


class SupplierUpdateStatus(BaseModel):
    status: SupplierStatus = PydanticField(..., description="Nuevo estado del proveedor")


class Supplier(SupplierCreate):
    id: str = PydanticField(..., description="ID único asignado por TinyDB")
    updated_at: str = PydanticField(..., description="Timestamp de la última actualización")


class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    user = "user"


class ProfileCreate(BaseModel):
    name: Optional[str] = PydanticField(default=None, min_length=1)
    phone: Optional[str] = None
    address: Optional[str] = None


class Profile(ProfileCreate):
    id: int
    user_id: int


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = PydanticField(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = PydanticField(..., min_length=8, exclude=True)
    name: Optional[str] = PydanticField(default=None, min_length=1)
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
    model_config = ConfigDict(extra="forbid")

    email: Optional[str] = PydanticField(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: Optional[str] = PydanticField(default=None, min_length=8, exclude=True)
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


class UserPublic(BaseModel):
    id: int
    email: str
    is_active: bool
    role: UserRole


class UserListItem(BaseModel):
    id: int
    email: str
    is_active: bool
    role: UserRole


class LoginRequest(BaseModel):
    email: str = PydanticField(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    email: str
    role: UserRole
    profile: Optional[Profile] = None


class ForgotPasswordRequest(BaseModel):
    email: str = PydanticField(..., min_length=3)


class ResetPasswordRequest(BaseModel):
    token: str = PydanticField(..., min_length=1)
    new_password: str = PydanticField(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str = PydanticField(..., min_length=1)
    new_password: str = PydanticField(..., min_length=8)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SKUProduct(BaseModel):
    id: int
    sku: str
    name: str
    client_name: str
    category: str
    reference: str
    current_stock: int = PydanticField(..., ge=0)


class InboundOrderCreate(BaseModel):
    sku_id: int = PydanticField(..., gt=0, strict=True)
    warehouse: str = PydanticField(..., min_length=1, pattern=r"\S")
    quantity: int = PydanticField(..., gt=0, strict=True)


class OutboundOrderCreate(InboundOrderCreate):
    exit_type: str = PydanticField(..., min_length=1, pattern=r"\S")
    tracking_number: Optional[str] = None


class InventoryOrder(BaseModel):
    id: int
    order_type: Literal["inbound", "outbound"]
    product: SKUProduct
    warehouse: str
    quantity: int = PydanticField(..., gt=0)
    created_at: datetime
    user_uuid: str
    exit_type: Optional[str] = None
    tracking_number: Optional[str] = None
    