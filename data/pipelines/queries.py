"""Lecturas para los endpoints de `services/reporting/` (§13.1 del diseño).

Solo consultas: ninguna lógica de ETL. Reciben el `engine` como parámetro para
no depender de cómo arranque la API.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from data.pipelines import runs


LATEST_WEEK_SQL = "select max(week_start) from reporting.weekly_warehouse_client_performance"

WEEK_ROWS_SQL = """
select warehouse,
       client_id,
       inbound_units_count,
       outbound_orders_count,
       stockout_events_count,
       discrepancy_events_count,
       discrepancy_rate
from reporting.weekly_warehouse_client_performance
where week_start = :week_start
order by warehouse, client_id
"""


def get_weekly_performance(engine: Engine, week_start: date | None = None) -> dict[str, Any] | None:
    """Filas de una semana con el contrato del BRIEFING (§6).

    Sin `week_start`, la semana calculada más reciente. `None` si no hay datos.
    """
    with engine.connect() as connection:
        if week_start is None:
            week_start = connection.execute(text(LATEST_WEEK_SQL)).scalar_one_or_none()
            if week_start is None:
                return None
        rows = connection.execute(text(WEEK_ROWS_SQL), {"week_start": week_start}).mappings().all()
    if not rows:
        return None
    entries = [
        {
            "warehouse": row["warehouse"],
            "client_id": row["client_id"],
            "inbound_units_count": int(row["inbound_units_count"]),
            "outbound_orders_count": int(row["outbound_orders_count"]),
            "stockout_events_count": int(row["stockout_events_count"]),
            "discrepancy_events_count": int(row["discrepancy_events_count"]),
            "discrepancy_rate": float(row["discrepancy_rate"]),
        }
        for row in rows
    ]
    return {"week_start": week_start, "entries": entries}


def get_latest_pipeline_run(engine: Engine) -> dict[str, Any] | None:
    """Metadata de la última corrida, con `records_processed` para el backoffice."""
    run = runs.get_latest_run(engine)
    if run is None:
        return None
    return {**run, "records_processed": run["events_extracted"]}
