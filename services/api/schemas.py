from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfilePublic(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class ProfileDetail(BaseModel):
    id: int
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class MeResponse(BaseModel):
    email: str
    profile: Optional[ProfilePublic] = None


class MessageResponse(BaseModel):
    message: str


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=3)


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


# --- SKU Schemas ---
class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(..., description="Código único del SKU")
    name: str = Field(..., description="Nombre del producto")
    client_name: str = Field(..., description="Cliente B2B propietario")
    category: str = Field(..., description="Categoría del producto")
    reference: str = Field(..., description="Referencia interna")

class ProductSummary(BaseModel):
    id: int
    sku: str
    name: str
    client_name: str
    category: str
    reference: str

class ProductResponse(ProductSummary):
    current_stock: int = Field(..., description="Stock actual calculado")


# --- Order Schemas ---
class InboundOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: int = Field(..., description="ID relacional del SKU")
    warehouse: str = Field(..., description="Almacén de destino (Los Angeles o Zaragoza)")
    quantity: int = Field(..., gt=0, description="Cantidad a ingresar")

class InboundOrderResponse(BaseModel):
    id: int
    sku_id: int
    warehouse: str
    quantity: int
    created_at: datetime

class OutboundOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: int = Field(..., description="ID relacional del SKU")
    warehouse: str = Field(..., description="Almacén de origen (Los Angeles o Zaragoza)")
    quantity: int = Field(..., gt=0, description="Cantidad a retirar")
    exit_type: str = Field(..., description="Tipo de salida (ej. B2C Order, B2B Transfer)")
    tracking_number: Optional[str] = Field(default=None, description="Número de seguimiento del transportista")

class OutboundOrderResponse(BaseModel):
    id: int
    sku_id: int
    warehouse: str
    quantity: int
    exit_type: str
    tracking_number: Optional[str]
    created_at: datetime

# --- Historial de Órdenes unificado ---
class ProductOrderSummary(BaseModel):
    sku: str
    name: str


class InventoryOrderListItem(BaseModel):
    id: int
    order_type: Literal["inbound", "outbound"]
    product: ProductOrderSummary
    warehouse: str
    quantity: int
    created_at: datetime
    user_uuid: str