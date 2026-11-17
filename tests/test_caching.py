import ast
from collections.abc import Iterator
import inspect

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from services.api.cache import TTLCache, api_cache
from services.api.database import get_db
from services.api.main import app
from services.api.models import SKU, StockEntry, StockExit
from services.api.routes import incidents as incident_routes
from services.api.routes import inventory as inventory_routes
from services.api.security import get_current_user
from services.api.services import incidents as incident_service


@pytest.fixture(autouse=True)
def isolate_cache(monkeypatch):
    api_cache.clear()
    monkeypatch.setattr(incident_routes, "CACHE_ENABLED", True)
    monkeypatch.setattr(inventory_routes, "CACHE_ENABLED", True)
    yield
    api_cache.clear()


@pytest.fixture
def incident_client(monkeypatch):
    database = TinyDB(storage=MemoryStorage)
    monkeypatch.setattr(
        incident_service, "incidents_table", database.table("incidents")
    )
    # Routers delegate storage to the service; TestClient must not run startup.
    client = TestClient(app)
    yield client
    client.close()
    database.close()


@pytest.fixture
def inventory_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        product = SKU(
            sku="CACHE-SKU",
            name="Cache product",
            client_name="Test client",
            category="Apparel",
            reference="CACHE-REF",
        )
        session.add(product)
        session.flush()
        product_id = product.id
        assert product_id is not None
        session.add(
            StockEntry(
                sku_id=product_id,
                warehouse="Zaragoza",
                quantity=10,
                user_uuid="cache-test",
            )
        )
        session.commit()

    def override_db() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_current_user,
        lambda: {"id": 1, "uuid": "cache-test"},
    )
    client = TestClient(app)
    yield client, engine, product_id
    client.close()
    engine.dispose()


def test_ttl_expiration_and_none_value():
    now = [0.0]
    cache = TTLCache(default_ttl=10, clock=lambda: now[0])
    assert cache.get("key") == (False, None)
    cache.set("key", None)
    assert cache.get("key") == (True, None)
    now[0] = 10
    assert cache.get("key") == (False, None)
    cache.set("short", "value", ttl=2)
    now[0] = 12
    assert cache.get("short") == (False, None)
    assert cache.stats() == {
        "hits": 1, "misses": 3, "invalidations": 0, "size": 0
    }


def test_expired_entries_are_evicted_before_oldest_live_entry():
    now = [0.0]
    cache = TTLCache(default_ttl=10, maxsize=2, clock=lambda: now[0])
    cache.set("old", "keep")
    cache.set("expired", "remove", ttl=1)
    now[0] = 1
    cache.set("new", "new")
    assert cache.get("old") == (True, "keep")
    cache.set("newer", "newer")
    assert cache.get("old") == (False, None)
    assert cache.get("new") == (True, "new")
    assert cache.stats()["size"] == 2


def test_invalidation_prefix_and_clear_metrics():
    cache = TTLCache(default_ttl=10)
    cache.set("inventory:a", 1)
    cache.set("inventory:b", 2)
    cache.set("incidents:summary", 3)
    cache.invalidate("missing")
    cache.invalidate("inventory:a")
    cache.invalidate_prefix("inventory:")
    assert cache.get("inventory:b") == (False, None)
    assert cache.get("incidents:summary") == (True, 3)
    assert cache.stats() == {
        "hits": 1, "misses": 1, "invalidations": 2, "size": 1
    }
    cache.clear()
    assert cache.stats() == {
        "hits": 0, "misses": 0, "invalidations": 0, "size": 0
    }


@pytest.mark.parametrize("ttl", [0, -1, float("inf"), float("nan")])
def test_rejects_non_expiring_or_invalid_ttl(ttl):
    with pytest.raises(ValueError, match="TTL"):
        TTLCache(default_ttl=ttl)
    cache = TTLCache(default_ttl=10)
    with pytest.raises(ValueError, match="TTL"):
        cache.set("invalid", "value", ttl=ttl)


def test_replacing_entry_renews_age_without_evicting_another_key():
    cache = TTLCache(default_ttl=10, maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("a", 3)
    assert cache.get("b") == (True, 2)
    cache.set("c", 4)
    assert cache.get("a") == (True, 3)
    assert cache.get("b") == (False, None)


def create_incident(client: TestClient):
    response = client.post(
        "/api/incidents",
        json={
            "title": "Test incident",
            "description": "Delayed delivery",
            "category": "DELAYED_DELIVERY",
            "status": "open",
            "origin": "internal",
            "branch": "Zaragoza",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_incident_summary_hit_and_create_invalidation(incident_client):
    first = incident_client.get("/api/incidents/summary")
    second = incident_client.get("/api/incidents/summary")
    assert first.status_code == second.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()
    create_incident(incident_client)
    refreshed = incident_client.get("/api/incidents/summary")
    assert refreshed.headers["X-Cache"] == "MISS"
    assert refreshed.json()["total"] == first.json()["total"] + 1


def test_incident_invalid_transition_keeps_cache_valid(incident_client):
    incident_id = create_incident(incident_client)
    before = incident_client.get("/api/incidents/summary")
    response = incident_client.patch(
        f"/api/incidents/{incident_id}/status", json={"status": "resolved"}
    )
    assert response.status_code == 400
    after = incident_client.get("/api/incidents/summary")
    assert after.headers["X-Cache"] == "HIT"
    assert after.json() == before.json()


def test_incident_successful_transition_invalidates_summary(incident_client):
    incident_id = create_incident(incident_client)
    incident_client.get("/api/incidents/summary")
    response = incident_client.patch(
        f"/api/incidents/{incident_id}/status", json={"status": "in_progress"}
    )
    assert response.status_code == 200
    after = incident_client.get("/api/incidents/summary")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["by_status"]["open"] == 0
    assert after.json()["by_status"]["in_progress"] == 1


@pytest.mark.parametrize("operation", ["product", "inbound", "outbound"])
def test_inventory_writes_invalidate_product_list(inventory_client, operation):
    client, _, product_id = inventory_client
    first = client.get("/inventory/products")
    second = client.get("/inventory/products")
    assert first.status_code == second.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()
    assert first.json()[0]["current_stock"] == 10

    if operation == "product":
        response = client.post(
            "/inventory/products",
            json={
                "sku": "CACHE-NEW",
                "name": "New product",
                "client_name": "Test client",
                "category": "Apparel",
                "reference": "CACHE-NEW-REF",
            },
        )
    else:
        payload = {
            "sku_id": product_id,
            "warehouse": "Zaragoza",
            "quantity": 3,
        }
        if operation == "outbound":
            payload["exit_type"] = "B2C Order"
        response = client.post(f"/inventory/orders/{operation}", json=payload)

    assert response.status_code == 201
    refreshed = client.get("/inventory/products")
    assert refreshed.headers["X-Cache"] == "MISS"
    if operation == "product":
        assert len(refreshed.json()) == 2
    else:
        expected_stock = 13 if operation == "inbound" else 7
        assert refreshed.json()[0]["current_stock"] == expected_stock


def test_outbound_validation_uses_fresh_stock_not_cached_list(inventory_client):
    client, engine, product_id = inventory_client
    cached = client.get("/inventory/products")
    assert cached.json()[0]["current_stock"] == 10

    # Simulate another writer after the visual list was cached.
    with Session(engine) as session:
        session.add(
            StockExit(
                sku_id=product_id,
                warehouse="Zaragoza",
                quantity=9,
                exit_type="B2C Order",
                user_uuid="external-writer",
            )
        )
        session.commit()

    response = client.post(
        "/inventory/orders/outbound",
        json={
            "sku_id": product_id,
            "warehouse": "Zaragoza",
            "quantity": 2,
            "exit_type": "B2C Order",
        },
    )
    assert response.status_code == 400
    assert "disponible 1" in response.json()["detail"]
    after = client.get("/inventory/products")
    assert after.headers["X-Cache"] == "HIT"
    assert after.json() == cached.json()
    with Session(engine) as session:
        exits = session.exec(select(StockExit)).all()
        assert len(exits) == 1


def test_incident_summary_bypass(incident_client, monkeypatch):
    monkeypatch.setattr(incident_routes, "CACHE_ENABLED", False)
    for _ in range(2):
        response = incident_client.get("/api/incidents/summary")
        assert response.status_code == 200
        assert response.headers["X-Cache"] == "BYPASS"
    assert api_cache.stats()["size"] == 0


def test_inventory_bypass(inventory_client, monkeypatch):
    client, _, _ = inventory_client
    monkeypatch.setattr(inventory_routes, "CACHE_ENABLED", False)
    for _ in range(2):
        response = client.get("/inventory/products")
        assert response.status_code == 200
        assert response.headers["X-Cache"] == "BYPASS"
        assert response.json()[0]["current_stock"] == 10
    assert api_cache.stats()["size"] == 0


def test_only_global_unauthenticated_routes_read_cache():
    def uses_current_user(dependant):
        return dependant.call is get_current_user or any(
            uses_current_user(child) for child in dependant.dependencies
        )

    pending = list(app.routes)
    cache_readers = set()
    while pending:
        route = pending.pop()
        if not isinstance(route, APIRoute):
            router = getattr(route, "original_router", None)
            if router is not None:
                pending.extend(router.routes)
            continue
        tree = ast.parse(inspect.getsource(route.endpoint))
        reads_cache = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "api_cache"
            and node.func.attr == "get"
            for node in ast.walk(tree)
        )
        if reads_cache:
            assert not uses_current_user(route.dependant), route.path
            cache_readers.add(route.endpoint.__name__)

    assert cache_readers == {"list_products", "get_incidents_summary"}
