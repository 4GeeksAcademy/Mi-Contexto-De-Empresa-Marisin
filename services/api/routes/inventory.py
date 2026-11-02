from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException

from ..database import inventory_db_lock, inventory_orders_table, products_table
from ..models import InboundOrderCreate, InventoryOrder, OutboundOrderCreate, SKUProduct
from ..security import get_current_user

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def _get_product(product_id: int) -> dict:
    product = products_table.get(doc_id=product_id) if product_id > 0 else None
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {**product, "id": product.doc_id}


@router.get("/products", response_model=list[SKUProduct])
def get_products(user: Annotated[dict, Depends(get_current_user)]):
    with inventory_db_lock:
        return [{**product, "id": product.doc_id} for product in products_table.all()]


@router.get("/products/{product_id}", response_model=SKUProduct)
def get_product(product_id: int, user: Annotated[dict, Depends(get_current_user)]):
    with inventory_db_lock:
        return _get_product(product_id)


def _create_order(
    payload: InboundOrderCreate,
    order_type: Literal["inbound", "outbound"],
    user: dict,
) -> dict:
    with inventory_db_lock:
        product = _get_product(payload.sku_id)
        stock = product["current_stock"]
        if order_type == "outbound" and payload.quantity > stock:
            raise HTTPException(status_code=409, detail="Insufficient stock")

        product["current_stock"] = (
            stock + payload.quantity if order_type == "inbound" else stock - payload.quantity
        )
        order = {
            **payload.model_dump(exclude={"sku_id"}),
            "order_type": order_type,
            "product": product,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "user_uuid": str(user["id"]),
        }
        products_table.update(
            {"current_stock": product["current_stock"]}, doc_ids=[payload.sku_id]
        )
        order_id = inventory_orders_table.insert(order)
        return {**order, "id": order_id}


@router.post("/orders/inbound", response_model=InventoryOrder, status_code=201)
def create_inbound_order(
    payload: InboundOrderCreate,
    user: Annotated[dict, Depends(get_current_user)],
):
    return _create_order(payload, "inbound", user)


@router.post("/orders/outbound", response_model=InventoryOrder, status_code=201)
def create_outbound_order(
    payload: OutboundOrderCreate,
    user: Annotated[dict, Depends(get_current_user)],
):
    return _create_order(payload, "outbound", user)


@router.get("/orders", response_model=list[InventoryOrder])
def get_orders(user: Annotated[dict, Depends(get_current_user)]):
    with inventory_db_lock:
        return [{**order, "id": order.doc_id} for order in inventory_orders_table.all()]