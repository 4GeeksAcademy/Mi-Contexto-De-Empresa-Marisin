from collections.abc import Iterator
from datetime import datetime
import logging
import os
from pathlib import Path
from threading import RLock

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine
from tinydb import TinyDB

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

database_url = os.getenv("DATABASE_URL", "").strip()
engine = None
if database_url:
    connection_url = make_url(database_url)
    if connection_url.get_backend_name() != "postgresql":
        raise ValueError("DATABASE_URL must be a PostgreSQL connection URI.")
    engine = create_engine(
        connection_url.set(drivername="postgresql+psycopg2"),
        poolclass=NullPool,
        connect_args={"sslmode": "require", "connect_timeout": 10},
    )


def get_db() -> Iterator[Session]:
    if engine is None:
        raise RuntimeError(
            "Set DATABASE_URL in .env to the Supabase Transaction pooler URI."
        )
    with Session(engine) as session:
        yield session


# Definir la ruta de la base de data local (se creará un fichero JSON)
DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "suppliers.json"
)

# Asegurar que el directorio data existe
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

db = TinyDB(DB_PATH)
suppliers_table = db.table("suppliers")
incidents_table = db.table("incidents")
users_table = db.table("users")
profiles_table = db.table("profiles")
password_reset_tokens_table = db.table("password_reset_tokens")
auth_db_lock = RLock()
products_table = db.table("products")
inventory_orders_table = db.table("inventory_orders")
inventory_db_lock = RLock()


SEED_ADMIN_EMAIL_ENV = "SEED_ADMIN_EMAIL"
SEED_ADMIN_PASSWORD_ENV = "SEED_ADMIN_PASSWORD"
SEED_ADMIN_PASSWORD_MIN_LENGTH = 12

security_logger = logging.getLogger("api.security")


def seed_admin() -> None:
    """Crea el admin inicial SOLO si el entorno lo pide (OWASP C3: sin credenciales por defecto).

    Necesita `SEED_ADMIN_EMAIL` y `SEED_ADMIN_PASSWORD` (≥ 12 caracteres). Si faltan, no
    crea nada. Nunca registra la contraseña. Si el usuario ya existe, no lo toca.
    """
    from .models import UserCreate, UserRole
    from .services.users import create_user, get_user_by_email

    email = os.getenv(SEED_ADMIN_EMAIL_ENV, "").strip()
    password = os.getenv(SEED_ADMIN_PASSWORD_ENV, "")
    if not email or not password:
        security_logger.info("Sin SEED_ADMIN_*: no se crea ningún admin por defecto")
        return
    if len(password) < SEED_ADMIN_PASSWORD_MIN_LENGTH:
        security_logger.warning(
            "%s tiene menos de %d caracteres: no se crea ningún admin por defecto",
            SEED_ADMIN_PASSWORD_ENV,
            SEED_ADMIN_PASSWORD_MIN_LENGTH,
        )
        return

    with auth_db_lock:
        if get_user_by_email(email) is None:
            user = create_user(UserCreate(email=email, password=password, name="TrackFlow Administrator"))
            users_table.update({"role": UserRole.admin.value}, doc_ids=[user["id"]])
            security_logger.info("Admin inicial creado desde SEED_ADMIN_EMAIL")


def seed_database():
    """Inserta datos iniciales: el admin solo si lo pide el entorno; proveedores y productos de ejemplo."""
    seed_admin()

    if len(suppliers_table.all()) == 0:
        initial_suppliers = [
            {
                "name": "Global Tech Logistics",
                "country": "United States",
                "categories": ["Logistics", "Software"],
                "rate_usd": 150.0,
                "status": "Active",
                "updated_at": datetime.utcnow().isoformat(),
            },
            {
                "name": "Iberia Express Cargo",
                "country": "Spain",
                "categories": ["Logistics", "Transport"],
                "rate_usd": 85.5,
                "status": "Active",
                "updated_at": datetime.utcnow().isoformat(),
            },
        ]
        for supplier in initial_suppliers:
            suppliers_table.insert(supplier)

    if not products_table.all():
        products_table.insert_multiple([
            {
                "sku": "TF-001",
                "name": "Wireless Keyboard",
                "client_name": "Global Tech Logistics",
                "category": "Electronics",
                "reference": "KEY-001",
                "current_stock": 100,
            },
            {
                "sku": "TF-002",
                "name": "Shipping Box",
                "client_name": "Iberia Express Cargo",
                "category": "Packaging",
                "reference": "BOX-001",
                "current_stock": 250,
            },
        ])