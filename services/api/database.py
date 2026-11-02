from collections.abc import Iterator
from datetime import datetime
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
users_table = db.table("users")
profiles_table = db.table("profiles")
password_reset_tokens_table = db.table("password_reset_tokens")
auth_db_lock = RLock()


def seed_database():
    """Inserta datos iniciales de prueba si la tabla está vacía."""
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