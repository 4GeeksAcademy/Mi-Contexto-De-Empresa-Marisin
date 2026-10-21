from datetime import datetime

from sqlmodel import Session, SQLModel, select

from .database import engine, suppliers_table
from .models import Inbound, Outbound, Product


INVENTORY_SEED = (
    {
        "sku": "TF-TEE-001",
        "name": "Camiseta de algodón",
        "inbound": (("Los Angeles", 120), ("Zaragoza", 80)),
        "outbound": (("Los Angeles", 15), ("Zaragoza", 12)),
    },
    {
        "sku": "TF-BOTTLE-001",
        "name": "Botella reutilizable",
        "inbound": (("Los Angeles", 40), ("Zaragoza", 55)),
        "outbound": (("Los Angeles", 5), ("Zaragoza", 9)),
    },
)
SEED_USER_UUID = "system:seed"


def seed_inventory() -> dict[str, int | bool]:
  if engine is None:
    raise RuntimeError(
        "Configura DATABASE_URL para sembrar el inventario en Supabase."
    )

  SQLModel.metadata.create_all(engine)
  seed_skus = {item["sku"] for item in INVENTORY_SEED}
  with Session(engine) as session:
    with session.begin():
      existing = session.exec(
          select(Product).where(Product.sku.in_(seed_skus))
      ).all()
      if existing:
        existing_skus = {product.sku for product in existing}
        if existing_skus != seed_skus:
          raise RuntimeError(
              "La semilla de inventario está incompleta; revisa los SKU existentes."
          )
        return {
            "inserted": False,
            "products": len(existing),
            "orders": 0,
        }

      product_count = 0
      order_count = 0
      for item in INVENTORY_SEED:
        product = Product(sku=item["sku"], name=item["name"])
        session.add(product)
        session.flush()
        product_count += 1

        for warehouse, quantity in item["inbound"]:
          session.add(
              Inbound(
                  product_id=product.id,
                  warehouse=warehouse,
                  quantity=quantity,
                  user_uuid=SEED_USER_UUID,
              )
          )
          order_count += 1
        for warehouse, quantity in item["outbound"]:
          session.add(
              Outbound(
                  product_id=product.id,
                  warehouse=warehouse,
                  quantity=quantity,
                  user_uuid=SEED_USER_UUID,
              )
          )
          order_count += 1

  return {
      "inserted": True,
      "products": product_count,
      "orders": order_count,
  }


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
  print(f"Semilla de inventario: {seed_inventory()}")
  