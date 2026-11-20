"""Carga idempotente en `reporting.weekly_warehouse_client_performance` (§6 y §7 del diseño).

Toda la carga de una corrida es **una sola transacción**:

1. `pg_advisory_xact_lock`: serializa dos cargas simultáneas (cron + disparo manual).
2. Upsert por la clave natural `(warehouse, client_id, week_start)` del BRIEFING.
   Las filas sin cambios no se reescriben (`is distinct from`) y conservan su
   `computed_at`.
3. Reconciliación: se borran las filas de las semanas recalculadas que ya no
   aparecen en el resultado nuevo.
4. `pipeline_runs.loaded_at = now()` y los conteos de la carga.

Si algo falla, el rollback deja el destino como estaba. Como el resultado se
recalcula siempre desde la fuente, repetir la carga da exactamente el mismo estado.
"""

from __future__ import annotations

from datetime import date
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine


PIPELINE_LOCK_KEY = "weekly_warehouse_client_performance:load"

_RECORDSET = """jsonb_to_recordset(cast(:rows as jsonb)) as r(
    warehouse text,
    client_id text,
    week_start date,
    inbound_units_count integer,
    outbound_orders_count integer,
    stockout_events_count integer,
    discrepancy_events_count integer,
    discrepancy_rate numeric
  )"""

LOCK_SQL = "select pg_advisory_xact_lock(hashtext(:lock_key))"

UPSERT_SQL = f"""
insert into reporting.weekly_warehouse_client_performance as t
  (warehouse, client_id, week_start, inbound_units_count, outbound_orders_count,
   stockout_events_count, discrepancy_events_count, discrepancy_rate, computed_at)
select r.warehouse, r.client_id, r.week_start, r.inbound_units_count, r.outbound_orders_count,
       r.stockout_events_count, r.discrepancy_events_count, r.discrepancy_rate, now()
from {_RECORDSET}
on conflict (warehouse, client_id, week_start) do update set
  inbound_units_count      = excluded.inbound_units_count,
  outbound_orders_count    = excluded.outbound_orders_count,
  stockout_events_count    = excluded.stockout_events_count,
  discrepancy_events_count = excluded.discrepancy_events_count,
  discrepancy_rate         = excluded.discrepancy_rate,
  computed_at              = excluded.computed_at
where (t.inbound_units_count, t.outbound_orders_count, t.stockout_events_count,
       t.discrepancy_events_count, t.discrepancy_rate)
  is distinct from
      (excluded.inbound_units_count, excluded.outbound_orders_count, excluded.stockout_events_count,
       excluded.discrepancy_events_count, excluded.discrepancy_rate)
returning (xmax = 0) as inserted
"""

RECONCILE_SQL = f"""
delete from reporting.weekly_warehouse_client_performance t
where t.week_start = any(cast(:weeks as date[]))
  and not exists (
    select 1
    from {_RECORDSET}
    where r.warehouse = t.warehouse
      and r.client_id = t.client_id
      and r.week_start = t.week_start
  )
"""

RUN_LOADED_SQL = """
update reporting.pipeline_runs
set loaded_at = now(),
    heartbeat_at = now(),
    last_completed_phase = 'load',
    rows_inserted = :rows_inserted,
    rows_updated = :rows_updated,
    rows_unchanged = :rows_unchanged,
    rows_deleted = :rows_deleted
where run_id = :run_id
"""


def _rows_json(records: list[dict[str, Any]]) -> str:
    return json.dumps(records, default=str)


def upsert_weekly_kpis(
    engine: Engine,
    run_id: UUID,
    records: list[dict[str, Any]],
    weeks: list[date],
) -> dict[str, int]:
    """Escribe las filas de la corrida y devuelve los conteos de la carga."""
    rows = _rows_json(records)
    with engine.begin() as connection:
        connection.execute(text(LOCK_SQL), {"lock_key": PIPELINE_LOCK_KEY})
        written = connection.execute(text(UPSERT_SQL), {"rows": rows}).scalars().all()
        deleted = connection.execute(text(RECONCILE_SQL), {"rows": rows, "weeks": list(weeks)}).rowcount
        inserted = sum(1 for is_insert in written if is_insert)
        counts = {
            "rows_inserted": inserted,
            "rows_updated": len(written) - inserted,
            "rows_unchanged": len(records) - len(written),
            "rows_deleted": int(deleted or 0),
        }
        connection.execute(text(RUN_LOADED_SQL), {**counts, "run_id": run_id})
    return counts
