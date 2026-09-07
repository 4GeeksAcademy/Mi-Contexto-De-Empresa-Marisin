from datetime import datetime
from .database import suppliers_table


def run_seed():
  if len(suppliers_table.all()) > 0:
    print(
        "⚠️ La base de datos ya contiene registros. No se ha insertado nada para"
        " evitar duplicados."
    )
    return

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

  suppliers_table.insert_multiple(initial_suppliers)
  print(f"✅ ¡Se han insertado {len(initial_suppliers)} proveedores iniciales!")


if __name__ == "__main__":
  run_seed()
  