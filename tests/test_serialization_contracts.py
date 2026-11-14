import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from services.api.database import get_db
from services.api.main import app
from services.api.models import (
    SKU,
    StockEntry,
    SupplierPublic,
    SupplierUpdateRate,
    SupplierUpdateStatus,
)
from services.api.routes import auth as auth_routes
from services.api.routes import suppliers as supplier_routes
from services.api.schemas import (
    InventoryOrderListItem,
    ProductListItem,
    ProductOrderSummary,
)
from services.api.security import get_current_user
from services.api.services import profiles as profile_service
from services.api.services import users as user_service


DOCUMENTED_NO_BODY_ENDPOINTS = {
    "delete_supplier",
    "remove_user",
}


def _api_routes(routes):
    seen = set()
    pending = list(routes)
    while pending:
        route = pending.pop()
        if id(route) in seen:
            continue
        seen.add(id(route))
        if isinstance(route, APIRoute):
            yield route
            continue

        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            pending.extend(nested_router.routes)
        else:
            pending.extend(getattr(route, "routes", ()))


@pytest.fixture
def api_client(monkeypatch):
    database = TinyDB(storage=MemoryStorage)
    users_table = database.table("users")
    profiles_table = database.table("profiles")
    reset_tokens_table = database.table("password_reset_tokens")
    suppliers_table = database.table("suppliers")
    sent_reset_tokens = []

    monkeypatch.setattr(user_service, "users_table", users_table)
    monkeypatch.setattr(profile_service, "profiles_table", profiles_table)
    monkeypatch.setattr(auth_routes, "users_table", users_table)
    monkeypatch.setattr(auth_routes, "password_reset_tokens_table", reset_tokens_table)
    monkeypatch.setattr(supplier_routes, "suppliers_table", suppliers_table)
    monkeypatch.setattr(
        auth_routes,
        "send_password_reset_email",
        lambda email, token: sent_reset_tokens.append((email, token)),
    )
    monkeypatch.setattr(
        auth_routes.secrets,
        "token_urlsafe",
        lambda _: "temporary-reset-token",
    )
    monkeypatch.setitem(
        app.dependency_overrides,
        get_current_user,
        lambda: {"id": 999, "email": "authenticated@example.com", "role": "admin"},
    )

    client = TestClient(app)
    client.sent_reset_tokens = sent_reset_tokens
    yield client
    database.close()


def _response_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _response_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _response_keys(nested)


def test_every_api_route_declares_a_response_model_or_documented_204():
    routes = list(_api_routes(app.routes))

    assert len(routes) == 25
    for route in routes:
        if route.response_model is None:
            assert route.status_code == 204
            assert route.name in DOCUMENTED_NO_BODY_ENDPOINTS
        else:
            assert route.response_model is not None

    assert {
        route.name for route in routes if route.response_model is None
    } == DOCUMENTED_NO_BODY_ENDPOINTS


def test_auth_responses_do_not_expose_credentials_or_email(api_client):
    registration = api_client.post(
        "/users",
        json={
            "email": "person@example.com",
            "password": "initial-password",
            "name": "Test Person",
        },
    )
    assert registration.status_code == 201

    login = api_client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "initial-password"},
    )
    assert login.status_code == 200

    forgot = api_client.post(
        "/auth/forgot-password",
        json={"email": "person@example.com"},
    )
    assert forgot.status_code == 200
    assert api_client.sent_reset_tokens == [
        ("person@example.com", "temporary-reset-token")
    ]

    reset = api_client.post(
        "/auth/reset-password",
        json={
            "token": "temporary-reset-token",
            "new_password": "updated-password",
        },
    )
    assert reset.status_code == 200

    for response in (registration, login, forgot, reset):
        keys = set(_response_keys(response.json()))
        assert not keys.intersection({"email", "password", "hashed_password"})

    app.dependency_overrides.pop(get_current_user)
    unauthenticated_me = api_client.get("/auth/me")
    unauthenticated_change = api_client.post(
        "/auth/change-password",
        json={
            "current_password": "initial-password",
            "new_password": "updated-password",
        },
    )
    for response in (unauthenticated_me, unauthenticated_change):
        assert response.status_code == 401
        assert "email" not in set(_response_keys(response.json()))


def test_authenticated_me_returns_only_public_profile(api_client, monkeypatch):
    monkeypatch.delitem(app.dependency_overrides, get_current_user)
    registration = api_client.post(
        "/users",
        json={
            "email": "person@example.com",
            "password": "initial-password",
            "name": "Test Person",
            "phone": "123456789",
            "address": "Test Street",
        },
    )
    assert registration.status_code == 201

    login = api_client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "initial-password"},
    )
    assert login.status_code == 200
    response = api_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "email": "person@example.com",
        "profile": {
            "name": "Test Person",
            "phone": "123456789",
            "address": "Test Street",
        },
    }
    assert not set(_response_keys(body)).intersection(
        {"password", "hashed_password", "id", "user_id", "role"}
    )


def test_product_list_uses_list_item_and_preserves_consumed_fields(monkeypatch):
    route = next(route for route in _api_routes(app.routes) if route.name == "list_products")
    assert route.response_model == list[ProductListItem]

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        product = SKU(
            sku="SKU-1",
            name="Product",
            client_name="Client",
            category="Category",
            reference="REF-1",
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        session.add(StockEntry(sku_id=product.id, warehouse="Zaragoza", quantity=4, user_uuid="1"))
        session.commit()
        monkeypatch.setitem(app.dependency_overrides, get_db, lambda: session)

        response = TestClient(app).get("/inventory/products")

        assert response.status_code == 200
        assert response.json() == [{
            "id": product.id,
            "sku": "SKU-1",
            "name": "Product",
            "client_name": "Client",
            "category": "Category",
            "reference": "REF-1",
            "current_stock": 4,
        }]
    engine.dispose()


def test_write_endpoint_rejects_fields_not_in_its_input_schema(api_client):
    response = api_client.post(
        "/suppliers",
        json={
            "name": "Test Supplier",
            "country": "Spain",
            "categories": ["Transport"],
            "rate_usd": 25,
            "status": "Active",
            "unexpected": True,
        },
    )

    assert response.status_code == 422


def test_supplier_patch_routes_use_strict_input_and_public_output():
    routes_by_name = {route.name: route for route in _api_routes(app.routes)}
    rate_route = routes_by_name["update_supplier_rate"]
    status_route = routes_by_name["update_supplier_status"]

    assert (
        rate_route.dependant.body_params[0].field_info.annotation
        is SupplierUpdateRate
    )
    assert (
        status_route.dependant.body_params[0].field_info.annotation
        is SupplierUpdateStatus
    )
    assert SupplierUpdateRate.model_config["extra"] == "forbid"
    assert SupplierUpdateStatus.model_config["extra"] == "forbid"
    assert rate_route.response_model is SupplierPublic
    assert status_route.response_model is SupplierPublic


def test_inventory_order_list_product_is_limited_to_sku_and_name():
    product_field = InventoryOrderListItem.model_fields["product"]

    assert product_field.annotation is ProductOrderSummary
    assert set(ProductOrderSummary.model_fields) == {"sku", "name"}


@pytest.mark.parametrize(
    "route_name",
    ["update_supplier_rate", "update_supplier_status"],
)
def test_supplier_patch_input_rejects_extra_fields(api_client, route_name):
    route = next(
        route for route in _api_routes(app.routes) if route.name == route_name
    )
    schema = route.dependant.body_params[0].field_info.annotation

    with pytest.raises(ValueError):
        schema.model_validate(
            (
                {"rate_usd": 35.5, "unexpected": True}
                if route_name == "update_supplier_rate"
                else {"status": "Active", "unexpected": True}
            )
        )

