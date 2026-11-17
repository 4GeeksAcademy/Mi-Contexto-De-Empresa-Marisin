#!/usr/bin/env python3
"""Seed deterministic load data for inventory and incidents."""

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import random
from typing import TypeVar

from sqlalchemy import delete, func
from sqlmodel import Session, SQLModel, select
from tinydb import where

from services.api.database import engine, incidents_table
from services.api.models import (
    IncidentBranch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
    SKU,
    StockEntry,
    StockExit,
)


RANDOM_SEED = 42
SKU_COUNT = 300
ENTRY_COUNT = 8_000
EXIT_COUNT = 4_000
INCIDENT_COUNT = 3_000
BATCH_SIZE = 1_000
SKU_PREFIX = "LOAD-"
INCIDENT_TITLE_PREFIX = "[LOAD]"
WAREHOUSES = ("Los Angeles", "Zaragoza")
CATEGORIES = (
    "Apparel",
    "Electronics",
    "Home",
    "Beauty",
    "Sports",
    "Accessories",
    "Packaging",
    "Toys",
)
CLIENTS = (
    "Aster & Oak",
    "Blue Harbor Goods",
    "Cedar Lane Market",
    "Dawnlight Commerce",
    "Evergreen Outfitters",
    "Fable House",
    "Golden Finch Retail",
    "Harbor & Hearth",
    "Indigo Peak Supply",
    "Juniper Row",
    "Kindred Coast",
    "Lumen Living",
    "Meadowline Brands",
    "Northstar Cart",
    "Olive & Ember",
    "Pioneer Parcel Co",
    "Quartz Bay Retail",
    "Redwood Collective",
    "Silver Fern Shop",
    "Tandem Trail",
    "Umber Home",
    "Violet Current",
    "Westward Goods",
    "Yellow Kite Market",
    "Zephyr & Stone",
)
EXIT_TYPES = ("B2C Order", "B2B Transfer", "Return / Damaged")
CARRIERS = ("UPS", "FedEx", "SEUR", "MRW", "DHL")
INCIDENT_DESCRIPTIONS = (
    "El envío de prueba presenta un retraso durante la clasificación.",
    "Se requiere revisar el embalaje antes de completar la entrega.",
    "El cliente informa de una posible discrepancia en el pedido.",
    "El transportista solicita confirmar los datos de destino.",
    "El artículo devuelto espera una inspección en el almacén.",
    "La actualización de seguimiento necesita validación operativa.",
)

ModelT = TypeVar("ModelT", SKU, StockEntry, StockExit)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete only load-test SKUs, their movements and [LOAD] incidents.",
    )
    return parser.parse_args()


def count_rows(session: Session, model: type[ModelT]) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


def count_incidents() -> int:
    return len(incidents_table)


def load_incidents():
    return incidents_table.search(
        where("title").test(
            lambda title: isinstance(title, str)
            and title.startswith(INCIDENT_TITLE_PREFIX)
        )
    )


def row_counts() -> dict[str, int]:
    if engine is None:
        raise RuntimeError(
            "No se puede preparar la carga: configura DATABASE_URL para PostgreSQL."
        )
    with Session(engine) as session:
        return {
            "SKUs": count_rows(session, SKU),
            "StockEntry": count_rows(session, StockEntry),
            "StockExit": count_rows(session, StockExit),
            "incidents": count_incidents(),
        }


def print_counts(before: dict[str, int], after: dict[str, int]) -> None:
    print("| Tabla | Antes | Después |")
    print("|---|---:|---:|")
    for table in before:
        print(f"| {table} | {before[table]} | {after[table]} |")


def find_load_skus(session: Session) -> list[SKU]:
    return session.exec(
        select(SKU).where(SKU.sku.startswith(SKU_PREFIX)).order_by(SKU.id)
    ).all()


def purge_load_data() -> None:
    if engine is None:
        raise RuntimeError(
            "No se puede purgar la carga: configura DATABASE_URL para PostgreSQL."
        )

    with Session(engine) as session:
        skus = find_load_skus(session)
        sku_ids = [sku.id for sku in skus if sku.id is not None]
        if sku_ids:
            session.exec(
                delete(StockEntry).where(StockEntry.sku_id.in_(sku_ids))
            )
            session.exec(
                delete(StockExit).where(StockExit.sku_id.in_(sku_ids))
            )
            session.exec(delete(SKU).where(SKU.id.in_(sku_ids)))
        session.commit()

    incidents_table.remove(
        where("title").test(
            lambda title: isinstance(title, str)
            and title.startswith(INCIDENT_TITLE_PREFIX)
        )
    )


def create_skus() -> list[int]:
    rng = random.Random(RANDOM_SEED)
    with Session(engine) as session:
        sku_rows = [
            SKU(
                sku=f"LOAD-{CATEGORIES[index % len(CATEGORIES)].upper()[:3]}-{index + 1:04d}",
                name=f"{rng.choice(('Essential', 'Premium', 'Everyday', 'Compact'))} "
                f"{rng.choice(('Pack', 'Kit', 'Item', 'Set'))} {index + 1:04d}",
                client_name=CLIENTS[index % len(CLIENTS)],
                category=CATEGORIES[index % len(CATEGORIES)],
                reference=f"LOAD-REF-{index + 1:05d}",
            )
            for index in range(SKU_COUNT)
        ]
        session.add_all(sku_rows)
        session.flush()
        sku_ids = [sku.id for sku in sku_rows if sku.id is not None]
        session.commit()
        return sku_ids


def make_movement_data(
    sku_ids: list[int],
) -> tuple[list[StockEntry], list[StockExit]]:
    rng = random.Random(RANDOM_SEED)
    now = datetime.now(timezone.utc)
    lower_bound = now - timedelta(days=548)
    warehouse_stock: defaultdict[tuple[int, str], int] = defaultdict(int)
    entries: list[StockEntry] = []

    for index in range(ENTRY_COUNT):
        sku_index = index % SKU_COUNT
        warehouse = WAREHOUSES[(index // SKU_COUNT) % len(WAREHOUSES)]
        sku_id = sku_ids[sku_index]
        quantity = rng.randint(15, 80)
        created_at = lower_bound + timedelta(
            seconds=rng.randrange(int((now - lower_bound).total_seconds()))
        )
        entries.append(
            StockEntry(
                sku_id=sku_id,
                warehouse=warehouse,
                quantity=quantity,
                created_at=created_at,
                user_uuid="seed-load",
            )
        )
        warehouse_stock[(sku_id, warehouse)] += quantity

    available_keys = list(warehouse_stock)
    exits: list[StockExit] = []
    for index in range(EXIT_COUNT):
        sku_id, warehouse = rng.choice(available_keys)
        available = warehouse_stock[(sku_id, warehouse)]
        quantity = rng.randint(1, min(available, 50))
        warehouse_stock[(sku_id, warehouse)] -= quantity
        created_at = lower_bound + timedelta(
            seconds=rng.randrange(int((now - lower_bound).total_seconds()))
        )
        carrier = rng.choice(CARRIERS)
        exits.append(
            StockExit(
                sku_id=sku_id,
                warehouse=warehouse,
                quantity=quantity,
                exit_type=rng.choice(EXIT_TYPES),
                tracking_number=f"{carrier}-LOAD-{index + 1:08d}",
                created_at=created_at,
                user_uuid="seed-load",
            )
        )

    return entries, exits


def insert_in_batches(rows: list[StockEntry] | list[StockExit]) -> None:
    for offset in range(0, len(rows), BATCH_SIZE):
        with Session(engine) as session:
            session.add_all(rows[offset : offset + BATCH_SIZE])
            session.commit()


def verify_non_negative_stock(sku_ids: list[int]) -> None:
    with Session(engine) as session:
        entry_totals = session.exec(
            select(
                StockEntry.sku_id,
                StockEntry.warehouse,
                func.sum(StockEntry.quantity),
            )
            .where(StockEntry.sku_id.in_(sku_ids))
            .group_by(StockEntry.sku_id, StockEntry.warehouse)
        ).all()
        exit_totals = session.exec(
            select(
                StockExit.sku_id,
                StockExit.warehouse,
                func.sum(StockExit.quantity),
            )
            .where(StockExit.sku_id.in_(sku_ids))
            .group_by(StockExit.sku_id, StockExit.warehouse)
        ).all()

    entries_by_key = {
        (sku_id, warehouse): int(quantity or 0)
        for sku_id, warehouse, quantity in entry_totals
    }
    exits_by_key = {
        (sku_id, warehouse): int(quantity or 0)
        for sku_id, warehouse, quantity in exit_totals
    }
    negative = [
        (sku_id, warehouse, entries_by_key.get((sku_id, warehouse), 0), quantity)
        for (sku_id, warehouse), quantity in exits_by_key.items()
        if quantity > entries_by_key.get((sku_id, warehouse), 0)
    ]
    if negative:
        raise RuntimeError(
            f"La verificación de stock encontró salidas superiores a entradas: "
            f"{negative[:5]}"
        )


def create_incidents() -> None:
    rng = random.Random(RANDOM_SEED)
    now = datetime.now(timezone.utc)
    branches = list(IncidentBranch)
    categories = list(IncidentCategory)
    statuses = list(IncidentStatus)
    origins = list(IncidentOrigin)
    incident_rows = []
    for index in range(INCIDENT_COUNT):
        created_at = now - timedelta(
            seconds=rng.randrange(1, 18 * 30 * 24 * 60 * 60)
        )
        updated_at = created_at + timedelta(
            seconds=rng.randrange(int((now - created_at).total_seconds()) + 1)
        )
        incident_rows.append(
            {
                "title": f"{INCIDENT_TITLE_PREFIX} Incidencia operativa {index + 1:04d}",
                "description": rng.choice(INCIDENT_DESCRIPTIONS),
                "category": rng.choice(categories).value,
                "status": rng.choice(statuses).value,
                "origin": rng.choice(origins).value,
                "branch": rng.choice(branches).value,
                "created_at": created_at.isoformat(),
                "updated_at": updated_at.isoformat(),
            }
        )
    incidents_table.insert_multiple(incident_rows)


def run_seed(purge: bool) -> None:
    if engine is None:
        raise RuntimeError(
            "No se puede ejecutar el seeder: DATABASE_URL no configura PostgreSQL."
        )

    SQLModel.metadata.create_all(engine)
    before = row_counts()

    if purge:
        purge_load_data()
        print("Datos de carga eliminados.")
        print_counts(before, row_counts())
        return

    existing_skus = find_load_skus_in_session()
    existing_incidents = load_incidents()
    if existing_skus or existing_incidents:
        print(
            "Ya existen datos de carga; no se insertó nada para evitar duplicados. "
            "Usa --purge explícitamente antes de volver a sembrar."
        )
        print_counts(before, row_counts())
        return

    sku_ids = create_skus()
    entries, exits = make_movement_data(sku_ids)
    insert_in_batches(entries)
    insert_in_batches(exits)
    verify_non_negative_stock(sku_ids)
    create_incidents()

    print(
        f"Seed completado: {len(sku_ids)} SKUs, {len(entries)} entradas, "
        f"{len(exits)} salidas y {INCIDENT_COUNT} incidencias."
    )
    print("Invariante de stock no negativo: verificado por SKU y almacén.")
    print_counts(before, row_counts())


def find_load_skus_in_session() -> list[SKU]:
    with Session(engine) as session:
        return find_load_skus(session)


def main() -> None:
    args = parse_args()
    run_seed(args.purge)


if __name__ == "__main__":
    main()
