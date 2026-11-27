"""Límite de intentos y registro de fallos de autenticación (auditoría OWASP · H1, D14).

Sin TinyDB: el usuario y la comprobación de contraseña se sustituyen en el módulo
de rutas. Valores sintéticos; `tests/conftest.py` vacía los limitadores en cada test.

    python -m pytest tests/test_auth_rate_limit.py
"""

import logging

import pytest
from fastapi.testclient import TestClient

from services.api import rate_limit
from services.api.main import app
from services.api.routes import auth as auth_routes

EMAIL = "cliente.prueba@example.com"
GOOD_PASSWORD = "test-password-" + "x" * 16
BAD_PASSWORD = "contraseña-incorrecta"
USER = {"id": 501, "email": EMAIL, "is_active": True, "role": "user"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_routes, "get_user_by_email",
                        lambda email: dict(USER) if email.strip().lower() == EMAIL else None)
    monkeypatch.setattr(auth_routes, "verify_user_password", lambda password, user: password == GOOD_PASSWORD)
    return TestClient(app)


@pytest.fixture
def security_log(caplog):
    logger = logging.getLogger("api.security")
    logger.addHandler(caplog.handler)  # api.security no propaga (handler propio, como api.timing)
    caplog.set_level(logging.INFO, logger="api.security")
    yield caplog
    logger.removeHandler(caplog.handler)


def login(client, password=BAD_PASSWORD, email=EMAIL, **kwargs):
    return client.post("/auth/login", json={"email": email, "password": password}, **kwargs)


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def test_sixth_failed_login_of_the_same_pair_is_429_with_retry_after(client):
    assert [login(client).status_code for _ in range(5)] == [401] * 5

    blocked = login(client)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Demasiados intentos. Inténtalo de nuevo más tarde."
    assert 1 <= int(blocked.headers["Retry-After"]) <= rate_limit.WINDOW_SECONDS


def test_the_right_password_is_also_blocked_while_the_pair_is_locked(client):
    for _ in range(5):
        login(client)
    assert login(client, password=GOOD_PASSWORD).status_code == 429


def test_a_successful_login_clears_the_pair_counter(client):
    for _ in range(4):
        login(client)
    assert login(client, password=GOOD_PASSWORD).status_code == 200
    assert [login(client).status_code for _ in range(5)] == [401] * 5
    assert login(client).status_code == 429


def test_twenty_failures_from_one_ip_block_every_email(client):
    for index in range(20):
        assert login(client, email=f"otro{index}@example.com").status_code == 401
    assert login(client, email="nuevo@example.com").status_code == 429


def test_other_ips_are_not_affected(client):
    for _ in range(5):
        login(client)
    other = TestClient(app, client=("203.0.113.7", 50000))
    assert other.post("/auth/login", json={"email": EMAIL, "password": GOOD_PASSWORD}).status_code == 200


def test_x_forwarded_for_is_not_trusted(client):
    for _ in range(5):
        login(client)
    assert login(client, headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 429


def test_failed_logins_are_logged_without_email_or_password(client, security_log):
    login(client)
    for _ in range(5):
        login(client)

    messages = [record.getMessage() for record in security_log.records if record.name == "api.security"]
    assert any(m.startswith("login_failed ") for m in messages)
    assert any(m.startswith("login_rate_limited ") for m in messages)
    assert all(f"email_hash={rate_limit.email_hash(EMAIL)}" in m for m in messages)
    text = "\n".join(messages)
    assert EMAIL not in text and BAD_PASSWORD not in text and GOOD_PASSWORD not in text


# --------------------------------------------------------------------------- #
# Recuperación de contraseña
# --------------------------------------------------------------------------- #
def test_fourth_password_reset_request_is_429(client, monkeypatch, security_log):
    monkeypatch.setattr(auth_routes, "get_user_by_email", lambda email: None)  # no escribe tokens
    statuses = [client.post("/auth/forgot-password", json={"email": EMAIL}).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    messages = [record.getMessage() for record in security_log.records if record.name == "api.security"]
    assert sum(m.startswith("password_reset_requested ") for m in messages) == 3
    assert EMAIL not in "\n".join(messages)


# --------------------------------------------------------------------------- #
# Limitador
# --------------------------------------------------------------------------- #
def test_sliding_window_forgets_old_events():
    now = [1000.0]
    limiter = rate_limit.SlidingWindowLimiter(2, window_seconds=60, clock=lambda: now[0])
    limiter.hit("k")
    now[0] += 30
    limiter.hit("k")
    assert limiter.retry_after("k") == 30  # el primer evento caduca en 30 s

    now[0] += 31
    assert limiter.retry_after("k") is None
    limiter.reset("k")
    assert limiter.retry_after("k") is None


def test_email_hash_is_short_stable_and_case_insensitive():
    assert rate_limit.email_hash(EMAIL) == rate_limit.email_hash(f"  {EMAIL.upper()} ")
    assert len(rate_limit.email_hash(EMAIL)) == 12
    assert EMAIL not in rate_limit.email_hash(EMAIL)
