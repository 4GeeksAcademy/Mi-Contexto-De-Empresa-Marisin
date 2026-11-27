"""NIST · acción irreversible con confirmación humana explícita (BRIEFING §5.2).

«Confirmar el despacho de un envío de alto valor sin validación adicional» es una
de las acciones del BRIEFING que exigen confirmación humana. En el fork la salida
de inventario (`POST /inventory/orders/outbound`) es la acción que despacha:

* Por debajo del umbral se registra como siempre.
* Con `HIGH_VALUE_DISPATCH_UNITS` unidades o más y sin `confirm_high_value` → **409**,
  no se registra nada y queda `high_value_dispatch_blocked` en `api.security`.
* Con la confirmación explícita de la persona → 201 y `high_value_dispatch_confirmed`.
* Un cliente (`user`) no puede despachar (403), ni confirmando.
* El stock insuficiente se comprueba antes (no se pide confirmar algo imposible).

    python -m pytest tests/test_nist_high_value_dispatch.py
"""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from services.api.cache import api_cache
from services.api.database import get_db
from services.api.main import app
from services.api.models import SKU, StockEntry, StockExit
from services.api.routes import inventory as inventory_routes
from services.api.security import get_current_user

STAFF = {"id": 1, "uuid": "nist-staff", "role": "manager"}
CUSTOMER = {"id": 9001, "uuid": "nist-customer", "role": "user"}


@pytest.fixture
def dispatch(monkeypatch):
    monkeypatch.setenv("HIGH_VALUE_DISPATCH_UNITS", "100")
    api_cache.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        product = SKU(sku="NIST-SKU", name="Producto de alto valor", client_name="Marca de prueba",
                      category="Electronics", reference="NIST-REF")
        session.add(product)
        session.flush()
        session.add(StockEntry(sku_id=product.id, warehouse="Zaragoza", quantity=500, user_uuid="nist-staff"))
        session.commit()
        product_id = product.id

    def override_db() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    user = {"current": STAFF}
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user["current"])
    client = TestClient(app)

    def post(quantity, *, confirm=None, as_user=STAFF):
        user["current"] = as_user
        body = {"sku_id": product_id, "warehouse": "Zaragoza", "quantity": quantity, "exit_type": "B2B Transfer"}
        if confirm is not None:
            body["confirm_high_value"] = confirm
        return client.post("/inventory/orders/outbound", json=body)

    def exits():
        with Session(engine) as session:
            return session.exec(select(StockExit)).all()

    yield post, exits
    client.close()
    engine.dispose()
    api_cache.clear()


@pytest.fixture
def security_log(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("api.security"), "propagate", True)  # su handler no propaga
    caplog.set_level(logging.INFO, logger="api.security")
    return caplog


def test_small_dispatch_is_registered_without_extra_confirmation(dispatch):
    post, exits = dispatch
    assert post(99).status_code == 201
    assert len(exits()) == 1


def test_high_value_dispatch_without_confirmation_is_refused_and_not_registered(dispatch, security_log):
    post, exits = dispatch
    response = post(100)

    assert response.status_code == 409
    assert "Requiere confirmación humana explícita" in response.json()["detail"]
    assert "100 unidades (umbral 100)" in response.json()["detail"]
    assert exits() == []
    assert any("high_value_dispatch_blocked" in record.getMessage() for record in security_log.records)


def test_explicit_false_is_not_a_confirmation(dispatch):
    post, exits = dispatch
    assert post(250, confirm=False).status_code == 409
    assert exits() == []


def test_high_value_dispatch_with_human_confirmation_is_registered_and_audited(dispatch, security_log):
    post, exits = dispatch
    response = post(250, confirm=True)

    assert response.status_code == 201
    assert [exit.quantity for exit in exits()] == [250]
    confirmed = [r.getMessage() for r in security_log.records if "high_value_dispatch_confirmed" in r.getMessage()]
    assert confirmed and '"user_uuid": "nist-staff"' in confirmed[0] and '"role": "manager"' in confirmed[0]


def test_a_customer_cannot_dispatch_even_confirming(dispatch):
    post, exits = dispatch
    assert post(250, confirm=True, as_user=CUSTOMER).status_code == 403
    assert exits() == []


def test_insufficient_stock_is_reported_before_asking_for_confirmation(dispatch):
    post, _ = dispatch
    assert post(600).status_code == 400


def test_the_threshold_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("HIGH_VALUE_DISPATCH_UNITS", raising=False)
    assert inventory_routes.high_value_dispatch_units() == inventory_routes.DEFAULT_HIGH_VALUE_DISPATCH_UNITS
    monkeypatch.setenv("HIGH_VALUE_DISPATCH_UNITS", "0")
    assert inventory_routes.high_value_dispatch_units() == inventory_routes.DEFAULT_HIGH_VALUE_DISPATCH_UNITS
