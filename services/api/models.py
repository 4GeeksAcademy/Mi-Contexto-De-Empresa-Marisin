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
  