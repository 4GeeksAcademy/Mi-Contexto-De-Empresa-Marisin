"""Sin credenciales por defecto (OWASP A07 · C3 · D13).

`seed_admin()` solo crea el admin inicial si el entorno da `SEED_ADMIN_EMAIL` y
`SEED_ADMIN_PASSWORD` (≥ 12 caracteres); nunca registra la contraseña. Ni la API ni el
benchmark llevan ya `admin@test.com` / su contraseña escritos en el código.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from services.api import database
from services.api.security import verify_user_password
from services.api.services import profiles as profile_service
from services.api.services import users as user_service

ROOT = Path(__file__).resolve().parents[1]
SEED_EMAIL = "seed-admin@example.com"
SEED_PASSWORD = "test-seed-password-" + "x" * 12
LEGACY_EMAIL = "admin@test.com"
LEGACY_PASSWORD = "password" + "123"


@pytest.fixture
def users_table(monkeypatch):
    db = TinyDB(storage=MemoryStorage)
    table = db.table("users")
    monkeypatch.setattr(user_service, "users_table", table)
    monkeypatch.setattr(database, "users_table", table)
    monkeypatch.setattr(profile_service, "profiles_table", db.table("profiles"))
    monkeypatch.delenv(database.SEED_ADMIN_EMAIL_ENV, raising=False)
    monkeypatch.delenv(database.SEED_ADMIN_PASSWORD_ENV, raising=False)
    yield table
    db.close()


def test_without_seed_variables_no_admin_is_created(users_table, caplog):
    with caplog.at_level("INFO", logger="api.security"):
        database.seed_admin()
    assert users_table.all() == []
    assert "Sin SEED_ADMIN_*: no se crea ningún admin por defecto" in caplog.text


def test_only_email_or_only_password_creates_nothing(users_table, monkeypatch):
    monkeypatch.setenv(database.SEED_ADMIN_EMAIL_ENV, SEED_EMAIL)
    database.seed_admin()
    monkeypatch.delenv(database.SEED_ADMIN_EMAIL_ENV)
    monkeypatch.setenv(database.SEED_ADMIN_PASSWORD_ENV, SEED_PASSWORD)
    database.seed_admin()
    assert users_table.all() == []


def test_short_password_creates_nothing(users_table, monkeypatch, caplog):
    monkeypatch.setenv(database.SEED_ADMIN_EMAIL_ENV, SEED_EMAIL)
    monkeypatch.setenv(database.SEED_ADMIN_PASSWORD_ENV, "corta-11ch!")
    with caplog.at_level("WARNING", logger="api.security"):
        database.seed_admin()
    assert users_table.all() == []
    assert "menos de 12 caracteres" in caplog.text
    assert "corta-11ch!" not in caplog.text


def test_seed_variables_create_one_admin_and_never_log_the_password(users_table, monkeypatch, caplog):
    monkeypatch.setenv(database.SEED_ADMIN_EMAIL_ENV, SEED_EMAIL)
    monkeypatch.setenv(database.SEED_ADMIN_PASSWORD_ENV, SEED_PASSWORD)
    with caplog.at_level("DEBUG"):
        database.seed_admin()
        database.seed_admin()  # idempotente
    [admin] = users_table.all()
    assert admin["email"] == SEED_EMAIL
    assert admin["role"] == "admin"
    assert verify_user_password(SEED_PASSWORD, admin)
    assert SEED_PASSWORD not in caplog.text
    assert SEED_PASSWORD not in str(admin)


def test_existing_user_is_not_touched(users_table, monkeypatch):
    users_table.insert({"email": SEED_EMAIL, "role": "manager", "hashed_password": "x", "is_active": True})
    monkeypatch.setenv(database.SEED_ADMIN_EMAIL_ENV, SEED_EMAIL)
    monkeypatch.setenv(database.SEED_ADMIN_PASSWORD_ENV, SEED_PASSWORD)
    database.seed_admin()
    [user] = users_table.all()
    assert user["role"] == "manager" and user["hashed_password"] == "x"


def test_seed_database_delegates_the_admin_to_seed_admin():
    source = inspect.getsource(database.seed_database)
    assert "seed_admin()" in source
    assert "UserCreate" not in source


@pytest.mark.parametrize(
    "path",
    ["services/api/database.py", "services/api/main.py", "scripts/perf/bench_endpoints.py"],
)
def test_default_credentials_are_gone_from_the_code(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    assert LEGACY_EMAIL not in text
    assert LEGACY_PASSWORD not in text


def test_benchmark_reads_its_credentials_from_the_environment(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("bench_endpoints", ROOT / "scripts/perf/bench_endpoints.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)

    monkeypatch.delenv("BENCH_EMAIL", raising=False)
    monkeypatch.delenv("BENCH_PASSWORD", raising=False)
    with pytest.raises(SystemExit) as stop:
        bench.bench_credentials()
    assert "BENCH_EMAIL" in str(stop.value)

    monkeypatch.setenv("BENCH_EMAIL", "bench@example.com")
    monkeypatch.setenv("BENCH_PASSWORD", "synthetic-bench-password")
    assert bench.bench_credentials() == ("bench@example.com", "synthetic-bench-password")
