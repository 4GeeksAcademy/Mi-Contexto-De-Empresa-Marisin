from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from ..database import get_db
from ..models import SKU, StockEntry, StockExit
from ..schemas import (
    InboundOrderCreate,
    InboundOrderResponse,
    InventoryOrderListItem,
    OutboundOrderCreate,
    OutboundOrderResponse,
    ProductCreate,
    ProductOrderSummary,
    ProductResponse,
)
from ..security import get_current_user

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def _warehouse_balances(
    session: Session, sku_id: int | None = None
) -> dict[tuple[int, str], int]:
    balances: defaultdict[tuple[int, str], int] = defaultdict(int)
    for model, multiplier in ((StockEntry, 1), (StockExit, -1)):
        query = select(
            model.sku_id,
            model.warehouse,
            func.sum(model.quantity),
        ).group_by(model.sku_id, model.warehouse)
        if sku_id is not None:
            query = query.where(model.sku_id == sku_id)
        for row in session.exec(query).all():
            key = (row[0], row[1])
            balances[key] += multiplier * int(row[2] or 0)
    return dict(balances)


def _product_response(sku_obj: SKU, stock: int) -> ProductResponse:
    return ProductResponse.model_validate(
        {**sku_obj.model_dump(), "current_stock": stock}
    )


def _user_uuid(current_user: dict) -> str:
    identifier = current_user.get("uuid") or current_user.get("user_uuid")
    if identifier is None:
        identifier = current_user.get("id")
    if identifier is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El usuario autenticado no tiene un identificador válido.",
        )
    return str(identifier)


@router.get("/products", response_model=list[ProductResponse])
def list_products(session: Annotated[Session, Depends(get_db)]):
    skus = session.exec(select(SKU).order_by(SKU.id)).all()
    balances = _warehouse_balances(session)
    stock_by_sku: defaultdict[int, int] = defaultdict(int)
    for (sku_id, _warehouse), balance in balances.items():
        stock_by_sku[sku_id] += balance
    return [
        _product_response(sku_obj, stock_by_sku[sku_obj.id])
        for sku_obj in skus
    ]


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    payload: ProductCreate,
    session: Annotated[Session, Depends(get_db)],
    _: Annotated[dict, Depends(get_current_user)],
):
    existing = session.exec(select(SKU).where(SKU.sku == payload.sku)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El SKU ya existe.")
    sku_obj = SKU(**payload.model_dump())
    session.add(sku_obj)
    session.commit()
    session.refresh(sku_obj)
    return _product_response(sku_obj, 0)


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: int,
    session: Annotated[Session, Depends(get_db)],
):
    sku_obj = session.get(SKU, product_id)
    if sku_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU no encontrado.")
    stock = sum(_warehouse_balances(session, product_id).values())
    return _product_response(sku_obj, stock)


@router.post(
    "/orders/inbound",
    response_model=InboundOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_inbound_order(
    payload: InboundOrderCreate,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    if session.get(SKU, payload.sku_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU no encontrado.")
    order = StockEntry(**payload.model_dump(), user_uuid=_user_uuid(current_user))
    session.add(order)
    session.commit()
    session.refresh(order)
    return InboundOrderResponse.model_validate(order, from_attributes=True)


@router.post(
    "/orders/outbound",
    response_model=OutboundOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_outbound_order(
    payload: OutboundOrderCreate,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    if session.get(SKU, payload.sku_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU no encontrado.")

    available = _warehouse_balances(session, payload.sku_id).get(
        (payload.sku_id, payload.warehouse), 0
    )
    if payload.quantity > available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stock insuficiente para el SKU en {payload.warehouse}: "
                f"disponible {available}, solicitado {payload.quantity}."
            ),
        )
    order = StockExit(**payload.model_dump(), user_uuid=_user_uuid(current_user))
    session.add(order)
    session.commit()
    session.refresh(order)
    return OutboundOrderResponse.model_validate(order, from_attributes=True)


@router.get("/orders", response_model=list[InventoryOrderListItem])
def list_orders(session: Annotated[Session, Depends(get_db)]):
    inbound_orders = session.exec(select(StockEntry)).all()
    outbound_orders = session.exec(select(StockExit)).all()
    skus = {
        sku_obj.id: sku_obj for sku_obj in session.exec(select(SKU)).all()
    }
    orders = []

    for order_type, rows in (
        ("inbound", inbound_orders),
        ("outbound", outbound_orders),
    ):
        for order in rows:
            sku_obj = skus.get(order.sku_id)
            if sku_obj is None:
                continue
            orders.append(
                InventoryOrderListItem(
                    id=order.id,
                    order_type=order_type,
                    product=ProductOrderSummary(sku=sku_obj.sku, name=sku_obj.name),
                    warehouse=order.warehouse,
                    quantity=order.quantity,
                    created_at=order.created_at,
                    user_uuid=order.user_uuid,
                )
            )
    return sorted(orders, key=lambda order: order.created_at, reverse=True)
