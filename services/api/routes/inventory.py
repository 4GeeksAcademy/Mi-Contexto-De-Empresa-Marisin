from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlmodel import Session, select

from ..cache import (
    CACHE_ENABLED,
    PRODUCTS_LIST_KEY,
    PRODUCTS_LIST_TTL,
    api_cache,
)
from ..database import get_db
from ..models import SKU, StockEntry, StockExit
from ..schemas import (
    DirectStockEditRequest,
    InboundOrderCreate,
    InboundOrderResponse,
    InventoryOrderListItem,
    MessageResponse,
    OutboundOrderCreate,
    OutboundOrderResponse,
    ProductCreate,
    ProductListItem,
    ProductOrderSummary,
    ProductResponse,
)
from ..security import require_staff, require_staff_or_service

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


# Staff o servicio MCP (D9); sin datos por usuario: la lista usa una clave de caché global.
@router.get(
    "/products",
    response_model=list[ProductListItem],
    dependencies=[Depends(require_staff_or_service)],
)
def list_products(response: Response, session: Annotated[Session, Depends(get_db)]):
    if CACHE_ENABLED:
        hit, cached = api_cache.get(PRODUCTS_LIST_KEY)
        if hit:
            response.headers["X-Cache"] = "HIT"
            return list(cached)

    skus = session.exec(select(SKU).order_by(SKU.id)).all()
    balances = _warehouse_balances(session)
    stock_by_sku: defaultdict[int, int] = defaultdict(int)
    for (sku_id, _warehouse), balance in balances.items():
        stock_by_sku[sku_id] += balance
    products = [
        _product_response(sku_obj, stock_by_sku[sku_obj.id])
        for sku_obj in skus
    ]
    if CACHE_ENABLED:
        api_cache.set(PRODUCTS_LIST_KEY, products, ttl=PRODUCTS_LIST_TTL)
        response.headers["X-Cache"] = "MISS"
    else:
        response.headers["X-Cache"] = "BYPASS"
    return products


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    payload: ProductCreate,
    session: Annotated[Session, Depends(get_db)],
    _: Annotated[dict, Depends(require_staff)],
):
    existing = session.exec(select(SKU).where(SKU.sku == payload.sku)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El SKU ya existe.")
    sku_obj = SKU(**payload.model_dump())
    session.add(sku_obj)
    session.commit()
    api_cache.invalidate(PRODUCTS_LIST_KEY)
    session.refresh(sku_obj)
    return _product_response(sku_obj, 0)


@router.get(
    "/products/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(require_staff_or_service)],
)
def get_product(
    product_id: int,
    session: Annotated[Session, Depends(get_db)],
):
    sku_obj = session.get(SKU, product_id)
    if sku_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU no encontrado.")
    stock = sum(_warehouse_balances(session, product_id).values())
    return _product_response(sku_obj, stock)


DIRECT_STOCK_EDIT_REJECTED = "El stock solo se modifica con órdenes de entrada o salida."


@router.patch(
    "/products/{product_id}/stock",
    response_model=MessageResponse,
    responses={405: {"model": MessageResponse, "description": DIRECT_STOCK_EDIT_REJECTED}},
)
def reject_direct_stock_edit(
    product_id: int,
    payload: DirectStockEditRequest,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_staff)],
):
    """Regla de negocio explícita: el stock nunca se edita directamente (D28).

    No toca modelos, caché ni balances; solo responde 405 para que el
    backoffice registre el intento como direct_stock_edit_rejected.
    """
    if session.get(SKU, product_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU no encontrado.")
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail=DIRECT_STOCK_EDIT_REJECTED,
    )


@router.post(
    "/orders/inbound",
    response_model=InboundOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_inbound_order(
    payload: InboundOrderCreate,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_staff)],
):
    if session.get(SKU, payload.sku_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU no encontrado.")
    order = StockEntry(**payload.model_dump(), user_uuid=_user_uuid(current_user))
    session.add(order)
    session.commit()
    api_cache.invalidate(PRODUCTS_LIST_KEY)
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
    current_user: Annotated[dict, Depends(require_staff)],
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
    api_cache.invalidate(PRODUCTS_LIST_KEY)
    session.refresh(order)
    return OutboundOrderResponse.model_validate(order, from_attributes=True)


@router.get(
    "/orders",
    response_model=list[InventoryOrderListItem],
    dependencies=[Depends(require_staff)],
)
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
