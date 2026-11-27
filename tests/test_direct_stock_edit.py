from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from services.api.database import get_db
from services.api.main import app
from services.api.models import SKU, StockEntry, StockExit
from services.api.security import get_current_user, require_staff_or_service


@pytest.fixture
def stock_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        product = SKU(
            sku="EDIT-SKU",
            name="Edit product",
            client_name="Test client",
            category="Apparel",
            reference="EDIT-REF",
        )
        session.add(product)
        session.flush()
        product_id = product.id
        session.add(
            StockEntry(
                sku_id=product_id,
                warehouse="Zaragoza",
                quantity=10,
                user_uuid="edit-test",
            )
        )
        session.commit()

    def override_db() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    client = TestClient(app)
    yield client, engine, product_id
    client.close()
    engine.dispose()


def _authenticate(monkeypatch):
    monkeypatch.setitem(
        app.dependency_overrides,
        get_current_user,
        lambda: {"id": 1, "uuid": "edit-test", "role": "manager"},
    )
    monkeypatch.setitem(
        app.dependency_overrides,
        require_staff_or_service,
        lambda: {"id": 1, "uuid": "edit-test", "role": "manager"},
    )


def _movement_count(engine) -> int:
    with Session(engine) as session:
        entries = session.exec(select(StockEntry)).all()
        exits = session.exec(select(StockExit)).all()
        return len(entries) + len(exits)


def test_direct_stock_edit_is_always_rejected_and_stock_is_unchanged(
    stock_client, monkeypatch
):
    client, engine, product_id = stock_client
    _authenticate(monkeypatch)

    response = client.patch(
        f"/inventory/products/{product_id}/stock",
        json={"warehouse": "Zaragoza", "quantity": 99},
    )

    assert response.status_code == 405
    assert response.json() == {
        "detail": "El stock solo se modifica con órdenes de entrada o salida."
    }
    assert _movement_count(engine) == 1
    product = client.get(f"/inventory/products/{product_id}").json()
    assert product["current_stock"] == 10


def test_direct_stock_edit_on_unknown_product_returns_404(stock_client, monkeypatch):
    client, _, _ = stock_client
    _authenticate(monkeypatch)

    response = client.patch(
        "/inventory/products/999999/stock",
        json={"warehouse": "Zaragoza", "quantity": 1},
    )

    assert response.status_code == 404


def test_direct_stock_edit_requires_authentication(stock_client):
    client, engine, product_id = stock_client

    response = client.patch(
        f"/inventory/products/{product_id}/stock",
        json={"warehouse": "Zaragoza", "quantity": 1},
    )

    assert response.status_code == 401
    assert _movement_count(engine) == 1
