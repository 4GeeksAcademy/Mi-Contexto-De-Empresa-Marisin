from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from ..database import get_db
from ..models import Inbound, Outbound, Product
from ..schemas import (
    InboundOrderCreate,
    InboundOrderResponse,
    InventoryOrderResponse,
    InventoryUserSummary,
    OutboundOrderCreate,
    OutboundOrderResponse,
    ProductCreate,
    ProductResponse,
    ProductSummary,
)
from ..security import get_current_user
from ..services.profiles import get_profile_by_user_id
from ..services.users import get_user_by_id

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def _warehouse_balances(
    session: Session, product_id: int | None = None
) -> dict[tuple[int, str], int]:
    balances: defaultdict[tuple[int, str], int] = defaultdict(int)
    for model, multiplier in ((Inbound, 1), (Outbound, -1)):
        query = select(
            model.product_id,
            model.warehouse,
            func.sum(model.quantity),
        ).group_by(model.product_id, model.warehouse)
        if product_id is not None:
            query = query.where(model.product_id == product_id)
        for row in session.exec(query).all():
            key = (row[0], row[1])
            balances[key] += multiplier * int(row[2] or 0)
    return dict(balances)


def _product_response(product: Product, stock: int) -> ProductResponse:
    return ProductResponse.model_validate(
        {**product.model_dump(), "current_stock": stock}
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


def _user_summary(user_uuid: str) -> InventoryUserSummary | None:
    try:
        user_id = int(user_uuid)
    except ValueError:
        return None
    user = get_user_by_id(user_id)
    if user is None:
        return None
    profile = get_profile_by_user_id(user_id)
    return InventoryUserSummary(
        user_uuid=user_uuid,
        email=user.get("email"),
        name=profile.get("name") if profile else None,
    )


@router.get("/products", response_model=list[ProductResponse])
def list_products(session: Annotated[Session, Depends(get_db)]):
    products = session.exec(select(Product).order_by(Product.id)).all()
    balances = _warehouse_balances(session)
    stock_by_product: defaultdict[int, int] = defaultdict(int)
    for (product_id, _warehouse), balance in balances.items():
        stock_by_product[product_id] += balance
    return [
        _product_response(product, stock_by_product[product.id])
        for product in products
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
    existing = session.exec(select(Product).where(Product.sku == payload.sku)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El SKU ya existe.")
    product = Product(**payload.model_dump())
    session.add(product)
    session.commit()
    session.refresh(product)
    return _product_response(product, 0)


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: int,
    session: Annotated[Session, Depends(get_db)],
):
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
    stock = sum(_warehouse_balances(session, product_id).values())
    return _product_response(product, stock)


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
    if session.get(Product, payload.product_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
    order = Inbound(**payload.model_dump(), user_uuid=_user_uuid(current_user))
    session.add(order)
    session.commit()
    session.refresh(order)
    return InboundOrderResponse.model_validate(order)


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
    if session.get(Product, payload.product_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado.")
    available = _warehouse_balances(session, payload.product_id).get(
        (payload.product_id, payload.warehouse), 0
    )
    if payload.quantity > available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stock insuficiente para el SKU en {payload.warehouse}: "
                f"disponible {available}, solicitado {payload.quantity}."
            ),
        )
    order = Outbound(**payload.model_dump(), user_uuid=_user_uuid(current_user))
    session.add(order)
    session.commit()
    session.refresh(order)
    return OutboundOrderResponse.model_validate(order)


@router.get("/orders", response_model=list[InventoryOrderResponse])
def list_orders(session: Annotated[Session, Depends(get_db)]):
    inbound_orders = session.exec(select(Inbound)).all()
    outbound_orders = session.exec(select(Outbound)).all()
    products = {
        product.id: product for product in session.exec(select(Product)).all()
    }
    orders = []
    user_cache: dict[str, InventoryUserSummary | None] = {}

    for order_type, rows in (
        ("inbound", inbound_orders),
        ("outbound", outbound_orders),
    ):
        for order in rows:
            product = products.get(order.product_id)
            if product is None:
                continue
            if order.user_uuid not in user_cache:
                user_cache[order.user_uuid] = _user_summary(order.user_uuid)
            orders.append(
                InventoryOrderResponse(
                    id=order.id,
                    order_type=order_type,
                    product=ProductSummary.model_validate(product),
                    warehouse=order.warehouse,
                    quantity=order.quantity,
                    created_at=order.created_at,
                    user_uuid=order.user_uuid,
                    user=user_cache[order.user_uuid],
                )
            )
    return sorted(orders, key=lambda order: order.created_at, reverse=True)