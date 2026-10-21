from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    current_stock: int = Field(description="Stock calculado dinámicamente")


class InboundOrderCreate(BaseModel):
    product_id: int = Field(gt=0)
    warehouse: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class InboundOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    warehouse: str
    quantity: int
    created_at: datetime
    user_uuid: str


class OutboundOrderCreate(BaseModel):
    product_id: int = Field(gt=0)
    warehouse: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class OutboundOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    warehouse: str
    quantity: int
    created_at: datetime
    user_uuid: str