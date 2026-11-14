"""Carga idempotente del historico CSV en la tabla de incidencias."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from packages.shared.incident_validation import transform_csv_row, validate_csv_row
from services.api.database import incidents_table

DEFAULT_CSV_PATH = Path(__file__).with_name("incidents-trackflow.csv")


def read_rows(csv_path: Path) -> Iterable[Mapping[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        yield from csv.DictReader(csv_file)


def seed_incidents(csv_path: Path) -> dict[str, int]:
    if not csv_path.exists():
        raise FileNotFoundError(f"No existe el CSV historico: {csv_path}")

    inserted = 0
    duplicates = 0
    invalid = Counter()

    existing_ids = {
        item.get("source_incident_id")
        for item in incidents_table.all()
        if item.get("source_incident_id")
    }

    for row in read_rows(csv_path):
        validation = validate_csv_row(row)
        if not validation.valid:
            invalid[validation.reason or "invalid_row"] += 1
            continue

        source_id = str(row["incident_id"]).strip()
        if source_id in existing_ids:
            duplicates += 1
            continue

        try:
            incident = transform_csv_row(row)
        except ValueError:
            invalid["invalid_date"] += 1
            continue

        incidents_table.insert(incident)
        existing_ids.add(source_id)
        inserted += 1

    summary = {"inserted": inserted, "duplicates": duplicates, "invalid": sum(invalid.values())}
    print(
        f"Seed de incidencias: {inserted} insertadas, "
        f"{duplicates} duplicadas, {summary['invalid']} invalidas."
    )
    for reason, count in sorted(invalid.items()):
        print(f"  - {reason}: {count}")
    return summary


def main() -> int:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV_PATH
    try:
        seed_incidents(csv_path)
    except (OSError, csv.Error) as error:
        print(f"[Error] No se pudo ejecutar el seed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
