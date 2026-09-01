from datetime import datetime
from typing import List, Optional
from .database import db, seed_database, suppliers_table
from fastapi import FastAPI, HTTPException, Query
from .models import (
    Supplier,
    SupplierCreate,
    SupplierStatus,
    SupplierUpdateRate,
    SupplierUpdateStatus,
)

app = FastAPI(
    title="TrackFlow - Supplier Directory API",
    version="1.0.0",
    description="API RESTful para la gestión del directorio de proveedores",
)


@app.on_event("startup")
async def startup_event():
  seed_database()


@app.get("/suppliers", response_model=List[Supplier])
def get_suppliers(
    country: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[SupplierStatus] = None,
    search: Optional[str] = None,
):
  """Obtiene la lista de proveedores con filtros opcionales de país, categoría, estado y búsqueda."""
  all_suppliers = suppliers_table.all()
  results = []

  for item in all_suppliers:
    supplier_data = {**item, "id": str(item.doc_id)}

    if country and country.lower() not in supplier_data["country"].lower():
      continue
    if category and category not in supplier_data["categories"]:
      continue
    if status and supplier_data["status"] != status.value:
      continue
    if search and search.lower() not in supplier_data["name"].lower():
      continue

    results.append(supplier_data)

  return results


@app.get("/suppliers/{supplier_id}", response_model=Supplier)
def get_supplier_by_id(supplier_id: int):
  """Devuelve el detalle de un proveedor por su ID."""
  if not suppliers_table.contains(doc_id=supplier_id):
    raise HTTPException(status_code=404, detail="Supplier not found")

  item = suppliers_table.get(doc_id=supplier_id)
  return {**item, "id": str(supplier_id)}


@app.post("/suppliers", response_model=Supplier, status_code=201)
def create_supplier(supplier_in: SupplierCreate):
  """Registra un nuevo proveedor en el directorio."""
  new_data = supplier_in.dict()
  new_data["updated_at"] = datetime.utcnow().isoformat()

  doc_id = suppliers_table.insert(new_data)
  created = suppliers_table.get(doc_id=doc_id)

  return {**created, "id": str(doc_id)}


@app.patch("/suppliers/{supplier_id}/rate", response_model=Supplier)
def update_supplier_rate(supplier_id: int, rate_in: SupplierUpdateRate):
  """Actualiza la tarifa de un proveedor existente."""
  if not suppliers_table.contains(doc_id=supplier_id):
    raise HTTPException(status_code=404, detail="Supplier not found")

  suppliers_table.update(
      {
          "rate_usd": rate_in.rate_usd,
          "updated_at": datetime.utcnow().isoformat(),
      },
      doc_ids=[supplier_id],
  )

  updated = suppliers_table.get(doc_id=supplier_id)
  return {**updated, "id": str(supplier_id)}


@app.patch("/suppliers/{supplier_id}/status", response_model=Supplier)
def update_supplier_status(supplier_id: int, status_in: SupplierUpdateStatus):
  """Actualiza el estado operativo de un proveedor."""
  if not suppliers_table.contains(doc_id=supplier_id):
    raise HTTPException(status_code=404, detail="Supplier not found")

  suppliers_table.update(
      {
          "status": status_in.status.value,
          "updated_at": datetime.utcnow().isoformat(),
      },
      doc_ids=[supplier_id],
  )

  updated = suppliers_table.get(doc_id=supplier_id)
  return {**updated, "id": str(supplier_id)}


@app.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int):
  """Elimina un proveedor del directorio."""
  if not suppliers_table.contains(doc_id=supplier_id):
    raise HTTPException(status_code=404, detail="Supplier not found")

  suppliers_table.remove(doc_ids=[supplier_id])
  return None
