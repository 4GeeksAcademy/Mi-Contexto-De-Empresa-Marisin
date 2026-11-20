"""Extracción en solo lectura desde `public.telemetry_events` (§3 del diseño).

La ventana `[window_start, window_end)` (lunes 00:00 UTC) y los cuatro
`event_type` del BRIEFING se filtran **en SQL**: nunca se carga la tabla entera.
Este módulo solo ejecuta `select`; no escribe nunca en `telemetry_events`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


EXTRACT_SQL = """
select id,
       "timestamp",
       event_type,
       tags->>'eventId'   as event_id,
       tags->>'warehouse' as warehouse,
       tags->>'client_id' as client_id,
       tags->>'quantity'  as quantity,
       tags->>'userId'    as user_id,
       tags->>'requestId' as request_id
from public.telemetry_events
where "timestamp" >= :window_start
  and "timestamp" <  :window_end
  and event_type in (
    'inbound_order_created',
    'outbound_order_created',
    'stock_threshold_triggered',
    'inventory_discrepancy_detected'
  )
"""

# Señales de silencio (§10.1): ¿hubo actividad técnica aunque no haya negocio?
SOURCE_SIGNALS_SQL = """
select count(*) as total_events,
       count(*) filter (where event_type in ('page_viewed', 'api_latency_recorded')) as technical_events,
       max("timestamp") as source_max_timestamp
from public.telemetry_events
where "timestamp" >= :window_start
  and "timestamp" <  :window_end
"""

# Cobertura de captura (§10.3): órdenes reales del dominio por almacén.
# Se excluyen los SKUs sintéticos LOAD-, que no emiten eventos de negocio (D15).
DOMAIN_ORDERS_SQL = """
select 'inbound' as kind, e.warehouse, count(*) as orders
from public.stock_entries e
join public.skus s on s.id = e.sku_id
where e.created_at >= :window_start
  and e.created_at <  :window_end
  and s.sku not like 'LOAD-%'
group by e.warehouse
union all
select 'outbound' as kind, x.warehouse, count(*) as orders
from public.stock_exits x
join public.skus s on s.id = x.sku_id
where x.created_at >= :window_start
  and x.created_at <  :window_end
  and s.sku not like 'LOAD-%'
group by x.warehouse
"""


def utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _window_params(window_start: date, window_end: date) -> dict[str, datetime]:
    return {"window_start": utc_midnight(window_start), "window_end": utc_midnight(window_end)}


def extract_events(engine: Engine, window_start: date, window_end: date) -> pd.DataFrame:
    """Eventos crudos de los cuatro tipos del BRIEFING dentro de la ventana."""
    with engine.connect() as connection:
        return pd.read_sql(text(EXTRACT_SQL), connection, params=_window_params(window_start, window_end))


def extract_source_signals(engine: Engine, window_start: date, window_end: date) -> dict[str, Any]:
    """Conteos de la ventana para distinguir silencio, caída de captura y actividad cero."""
    with engine.connect() as connection:
        row = connection.execute(
            text(SOURCE_SIGNALS_SQL), _window_params(window_start, window_end)
        ).mappings().one()
    return {
        "total_events": int(row["total_events"]),
        "technical_events": int(row["technical_events"]),
        "source_max_timestamp": row["source_max_timestamp"],
    }


def extract_domain_orders(engine: Engine, window_start: date, window_end: date) -> pd.DataFrame:
    """Órdenes de `stock_entries` y `stock_exits` por almacén (solo control de calidad)."""
    with engine.connect() as connection:
        return pd.read_sql(text(DOMAIN_ORDERS_SQL), connection, params=_window_params(window_start, window_end))
