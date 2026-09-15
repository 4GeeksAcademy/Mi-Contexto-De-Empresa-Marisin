from datetime import datetime
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from ..database import suppliers_table
from ..models import (
    Supplier,
    SupplierCreate,
    SupplierStatus,
    SupplierUpdateRate,
    SupplierUpdateStatus,
)
from ..security import get_current_user

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get("", response_model=List[Supplier])
def get_suppliers(
    country: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[SupplierStatus] = None,
    search: Optional[str] = None,
    _: Annotated[dict, Depends(get_current_user)] = None,
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


@router.get("/{supplier_id}", response_model=Supplier)
def get_supplier_by_id(supplier_id: int, _: Annotated[dict, Depends(get_current_user)]):
    """Devuelve el detalle de un proveedor por su ID."""
    if not suppliers_table.contains(doc_id=supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")

    item = suppliers_table.get(doc_id=supplier_id)
    return {**item, "id": str(supplier_id)}


@router.post("", response_model=Supplier, status_code=201)
def create_supplier(supplier_in: SupplierCreate, _: Annotated[dict, Depends(get_current_user)]):
    """Registra un nuevo proveedor en el directorio."""
    new_data = supplier_in.dict()
    new_data["updated_at"] = datetime.utcnow().isoformat()

    doc_id = suppliers_table.insert(new_data)
    created = suppliers_table.get(doc_id=doc_id)

    return {**created, "id": str(doc_id)}


@router.patch("/{supplier_id}/rate", response_model=Supplier)
def update_supplier_rate(
    supplier_id: int,
    rate_in: SupplierUpdateRate,
    _: Annotated[dict, Depends(get_current_user)],
):
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


@router.patch("/{supplier_id}/status", response_model=Supplier)
def update_supplier_status(
    supplier_id: int,
    status_in: SupplierUpdateStatus,
    _: Annotated[dict, Depends(get_current_user)],
):
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


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int, _: Annotated[dict, Depends(get_current_user)]):
    """Elimina un proveedor del directorio."""
    if not suppliers_table.contains(doc_id=supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")

    suppliers_table.remove(doc_ids=[supplier_id])
    return None