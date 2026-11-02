from datetime import datetime, timezone
import os

from sqlmodel import Session, SQLModel, select

if __package__:
    from .api.database import engine, suppliers_table, users_table
    from .api.models import SKU, StockEntry, StockExit
else:
    from api.database import engine, suppliers_table, users_table
    from api.models import SKU, StockEntry, StockExit


INVENTORY_SEED = (
    {
        "sku": "TF-TEE-001",
        "name": "Camiseta de algodón",
        "client_name": "EcoWear USA",
        "category": "Apparel",
        "reference": "REF-TEE-001",
        "inbound": (("Los Angeles", 120), ("Zaragoza", 80)),
        "outbound": (
            ("Los Angeles", 15, "B2C Order", "TRK-LA-001"),
            ("Zaragoza", 12, "B2C Order", "TRK-ZA-001"),
        ),
    },
    {
        "sku": "TF-BOTTLE-001",
        "name": "Botella reutilizable",
        "client_name": "HydroLife",
        "category": "Accessories",
        "reference": "REF-BOT-001",
        "inbound": (("Los Angeles", 40), ("Zaragoza", 55)),
        "outbound": (
            ("Los Angeles", 5, "B2C Order", "TRK-LA-002"),
            ("Zaragoza", 9, "B2C Order", "TRK-ZA-002"),
        ),
    },
)
SEED_USER_UUID = os.getenv("SEED_USER_UUID", "").strip()


def seed_inventory() -> dict[str, int | bool]:
    if engine is None:
        raise RuntimeError(
            "Configura DATABASE_URL para sembrar el inventario en Supabase."
        )

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        with session.begin():
            sku_count = 0
            order_count = 0
            for item in INVENTORY_SEED:
                sku_obj = session.exec(
                    select(SKU).where(SKU.sku == item["sku"]).with_for_update()
                ).first()
                if sku_obj is None:
                    sku_obj = SKU(
                        sku=item["sku"],
                        name=item["name"],
                        client_name=item["client_name"],
                        category=item["category"],
                        reference=item["reference"],
                    )
                    session.add(sku_obj)
                    session.flush()
                    sku_count += 1

                for warehouse, quantity in item["inbound"]:
                    existing = session.exec(
                        select(StockEntry).where(
                            StockEntry.sku_id == sku_obj.id,
                            StockEntry.warehouse == warehouse,
                            StockEntry.quantity == quantity,
                        )
                    ).first()
                    if existing is not None:
                        continue
                    session.add(
                        StockEntry(
                            sku_id=sku_obj.id,
                            warehouse=warehouse,
                            quantity=quantity,
                            user_uuid=seed_user_uuid(),
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    session.flush()
                    order_count += 1
                    
                for warehouse, quantity, exit_type, tracking_number in item["outbound"]:
                    existing = session.exec(
                        select(StockExit).where(
                            StockExit.sku_id == sku_obj.id,
                            StockExit.warehouse == warehouse,
                            StockExit.quantity == quantity,
                            StockExit.exit_type == exit_type,
                            StockExit.tracking_number == tracking_number,
                        )
                    ).first()
                    if existing is not None:
                        continue
                    entries = session.exec(select(StockEntry).where(
                        StockEntry.sku_id == sku_obj.id,
                        StockEntry.warehouse == warehouse,
                    )).all()
                    exits = session.exec(select(StockExit).where(
                        StockExit.sku_id == sku_obj.id,
                        StockExit.warehouse == warehouse,
                    )).all()
                    stock = sum(order.quantity for order in entries) - sum(
                        order.quantity for order in exits
                    )
                    if stock < quantity:
                        raise RuntimeError(
                            f"Stock insuficiente para {item['sku']} en {warehouse}."
                        )
                    session.add(
                        StockExit(
                            sku_id=sku_obj.id,
                            warehouse=warehouse,
                            quantity=quantity,
                            exit_type=exit_type,
                            tracking_number=tracking_number,
                            user_uuid=seed_user_uuid(),
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    session.flush()
                    order_count += 1

    return {
        "inserted": bool(sku_count or order_count),
        "skus": sku_count,
        "orders": order_count,
    }


def seed_user_uuid() -> str:
    users = users_table.all()
    for user in users:
        identifier = str(
            user.get("uuid") or user.get("user_uuid")
            or user.get("id", user.doc_id)
        )
        if SEED_USER_UUID == identifier or (not SEED_USER_UUID and len(users) == 1):
            return identifier
    raise RuntimeError(
        "Configura SEED_USER_UUID con el identificador de un usuario de TinyDB "
        "existente para atribuir los movimientos de la semilla."
    )


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
    print(f"Semilla de inventario: {seed_inventory()}")
    