from datetime import datetime
import os
from tinydb import TinyDB

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