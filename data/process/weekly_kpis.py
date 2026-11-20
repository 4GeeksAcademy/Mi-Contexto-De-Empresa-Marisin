"""Transformación del Reporte Semanal de Desempeño por Almacén y Cliente.

Funciones puras de Pandas (T1–T6 de `data/pipelines/PIPELINE_DESIGN.md` §4.1):
con los mismos eventos devuelven siempre el mismo resultado, no tocan la base
de datos y no dependen de Prefect, así que se prueban sin infraestructura.

    refinar tipos → motivos de rechazo → deduplicar por eventId → excluir
    verificación → week_start (lunes ISO, UTC) → agrupar → discrepancy_rate

Los nombres de columnas y KPIs son los del BRIEFING de data pipelines de TrackFlow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import hashlib
from typing import Any, Iterable

import numpy as np
import pandas as pd


# Versión de la lógica de transformación. Forma parte de la clave de caché:
# si cambia el cálculo o el tipo que devuelve, se sube este número y ningún
# resultado antiguo se reutiliza.
# v1: Parte 2 (transform_weekly_kpis → TransformResult).
# v2: Parte 3 (prepare_kpi_events → PreparedEvents).
TRANSFORM_VERSION = "2"

INBOUND = "inbound_order_created"
OUTBOUND = "outbound_order_created"
STOCKOUT = "stock_threshold_triggered"
DISCREPANCY = "inventory_discrepancy_detected"
KPI_EVENT_TYPES = (INBOUND, OUTBOUND, STOCKOUT, DISCREPANCY)

WAREHOUSES = ("los_angeles", "zaragoza")
CLIENT_ID_PATTERN = r"[a-z0-9]+(?:_[a-z0-9]+)*"

# Columnas que devuelve la extracción (consulta de PIPELINE_DESIGN.md §3.3).
RAW_COLUMNS = (
    "id",
    "timestamp",
    "event_type",
    "event_id",
    "warehouse",
    "client_id",
    "quantity",
    "user_id",
    "request_id",
)

GRAIN = ("warehouse", "client_id", "week_start")
KPI_COLUMNS = (
    "inbound_units_count",
    "outbound_orders_count",
    "stockout_events_count",
    "discrepancy_events_count",
    "discrepancy_rate",
)
OUTPUT_COLUMNS = GRAIN + KPI_COLUMNS


@dataclass(frozen=True)
class TransformResult:
    """Salida de la transformación: filas con el grano del BRIEFING y estadísticas."""

    kpis: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ventana de semanas
# ---------------------------------------------------------------------------


def week_start_of(day: date) -> date:
    """Lunes de la semana ISO que contiene `day`."""
    return day - timedelta(days=day.weekday())


def resolve_weeks(
    today: date,
    week_start: date | None = None,
    lookback_weeks: int = 4,
) -> list[date]:
    """Semanas que recalcula una corrida (D3 y D11 del diseño).

    - Con `week_start`: solo esa semana (disparo manual). Debe ser lunes.
    - Sin `week_start`: las `lookback_weeks` semanas cerradas que terminan en la
      semana anterior a la actual. La semana en curso nunca entra sola.
    """
    if week_start is not None:
        if week_start.weekday() != 0:
            raise ValueError("week_start debe ser un lunes (inicio de semana ISO).")
        return [week_start]
    if lookback_weeks < 1:
        raise ValueError("lookback_weeks debe ser al menos 1.")
    last_closed = week_start_of(today) - timedelta(weeks=1)
    return [last_closed - timedelta(weeks=offset) for offset in range(lookback_weeks - 1, -1, -1)]


def window_bounds(weeks: list[date]) -> tuple[date, date]:
    """Ventana `[lunes más antiguo, lunes siguiente al más reciente)`."""
    return min(weeks), max(weeks) + timedelta(weeks=1)


# ---------------------------------------------------------------------------
# Clave de caché
# ---------------------------------------------------------------------------


def events_fingerprint(raw_events: pd.DataFrame) -> str:
    """Huella del contenido de la extracción (independiente del orden de filas)."""
    if raw_events.empty:
        return "empty"
    frame = raw_events.reindex(columns=list(RAW_COLUMNS)).astype("string")
    frame = frame.sort_values(["id"], kind="stable").reset_index(drop=True)
    row_hashes = pd.util.hash_pandas_object(frame, index=False).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()


def transform_cache_key(raw_events: pd.DataFrame, excluded_user_ids: Iterable[str]) -> str:
    """Clave = versión de la lógica + eventos extraídos + exclusiones configuradas."""
    excluded = ",".join(sorted(set(excluded_user_ids)))
    return (
        f"weekly-kpis-v{TRANSFORM_VERSION}"
        f"-{events_fingerprint(raw_events)}"
        f"-{hashlib.sha256(excluded.encode()).hexdigest()[:12]}"
    )


# ---------------------------------------------------------------------------
# T1–T6
# ---------------------------------------------------------------------------


class RawEventsSchemaError(ValueError):
    """La extracción no tiene la forma esperada (§3.3 del diseño)."""


@dataclass(frozen=True)
class PreparedEvents:
    """Eventos limpios, deduplicados y con `week_start`, listos para calcular KPIs."""

    events: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)


def ensure_raw_events(raw_events: Any) -> pd.DataFrame:
    """Defensa de entrada: un DataFrame con todas las columnas de la extracción."""
    if not isinstance(raw_events, pd.DataFrame):
        raise TypeError(
            f"Se esperaba un DataFrame de telemetry_events y llegó {type(raw_events).__name__}."
        )
    missing = [column for column in RAW_COLUMNS if column not in raw_events.columns]
    if missing:
        raise RawEventsSchemaError(f"Faltan columnas de la extracción: {', '.join(missing)}.")
    return raw_events


def refine_events(raw_events: pd.DataFrame) -> pd.DataFrame:
    """T1: tipos correctos antes de agrupar. Un `timestamp` ilegible queda como NaT."""
    events = ensure_raw_events(raw_events).reindex(columns=list(RAW_COLUMNS)).copy()
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True, format="ISO8601", errors="coerce")
    for column in ("id", "event_type", "event_id", "warehouse", "client_id", "user_id", "request_id"):
        events[column] = events[column].astype("string").str.strip()
    quantity = pd.to_numeric(events["quantity"], errors="coerce")
    is_integer = quantity.notna() & (quantity % 1 == 0)
    events["quantity"] = quantity.where(is_integer).astype("Int64")
    return events


def rejection_reasons(events: pd.DataFrame) -> pd.Series:
    """Motivo de rechazo por fila (cadena vacía si la fila es válida), §3.2."""
    client_ok = events["client_id"].fillna("").str.fullmatch(CLIENT_ID_PATTERN).fillna(False)
    quantity_ok = events["quantity"].fillna(0) >= 1
    conditions = [
        events["event_id"].isna() | (events["event_id"] == ""),
        events["timestamp"].isna(),
        ~events["event_type"].isin(KPI_EVENT_TYPES).fillna(False),
        ~events["warehouse"].isin(WAREHOUSES).fillna(False),
        ~client_ok.astype(bool),
        (events["event_type"] == INBOUND).fillna(False) & ~quantity_ok.astype(bool),
    ]
    choices = [
        "missing_event_id",
        "invalid_timestamp",
        "invalid_event_type",
        "invalid_warehouse",
        "invalid_client_id",
        "invalid_quantity",
    ]
    return pd.Series(np.select(conditions, choices, default=""), index=events.index)


def add_week_start(events: pd.DataFrame) -> pd.DataFrame:
    """T4: lunes de la semana ISO en UTC."""
    timestamps = events["timestamp"]
    monday = timestamps.dt.normalize() - pd.to_timedelta(timestamps.dt.day_of_week, unit="D")
    return events.assign(week_start=monday.dt.date)


def prepare_events(raw_events: pd.DataFrame, excluded_user_ids: Iterable[str] = ()) -> PreparedEvents:
    """T1–T4: refinar, rechazar inválidos, deduplicar por eventId, excluir verificación y semana ISO."""
    excluded = tuple(excluded_user_ids)
    events = refine_events(raw_events)
    events = events.assign(rejection_reason=rejection_reasons(events))

    has_event_id = events["rejection_reason"] != "missing_event_id"
    with_id = events[has_event_id].sort_values(["timestamp", "id"], kind="stable")
    unique = with_id.drop_duplicates(subset="event_id", keep="first")
    deduplicated = pd.concat([unique, events[~has_event_id]])
    duplicates_dropped = len(with_id) - len(unique)

    is_excluded = deduplicated["user_id"].isin(excluded).fillna(False).astype(bool)
    kept = deduplicated[~is_excluded]
    is_rejected = kept["rejection_reason"] != ""
    rejected = kept[is_rejected]
    valid = add_week_start(kept[~is_rejected]).drop(columns=["rejection_reason"])

    stats = {
        "events_extracted": int(len(raw_events)),
        "duplicates_dropped": int(duplicates_dropped),
        "events_excluded": int(is_excluded.sum()),
        "events_rejected": int(len(rejected)),
        "rejected_by_reason": {
            str(reason): int(count) for reason, count in rejected["rejection_reason"].value_counts().items()
        },
        "events_by_type": {
            event_type: int((valid["event_type"] == event_type).sum()) for event_type in KPI_EVENT_TYPES
        },
        "events_by_warehouse": {
            warehouse: {
                "inbound": int(((valid["warehouse"] == warehouse) & (valid["event_type"] == INBOUND)).sum()),
                "outbound": int(((valid["warehouse"] == warehouse) & (valid["event_type"] == OUTBOUND)).sum()),
            }
            for warehouse in WAREHOUSES
        },
    }
    return PreparedEvents(events=valid.reset_index(drop=True), stats=stats)


# ---------------------------------------------------------------------------
# T5: un cálculo por KPI de la sección "KPIs a medir" del BRIEFING
# ---------------------------------------------------------------------------


def _empty_grain(column: str) -> pd.DataFrame:
    return pd.DataFrame({name: pd.Series(dtype="object") for name in GRAIN}).assign(
        **{column: pd.Series(dtype="int64")}
    )


def _per_grain(events: pd.DataFrame, event_type: str, column: str, units: bool = False) -> pd.DataFrame:
    selected = events[events["event_type"] == event_type]
    if selected.empty:
        return _empty_grain(column)
    grouped = selected.groupby(list(GRAIN), as_index=False, observed=True)
    if units:
        result = grouped["quantity"].sum().rename(columns={"quantity": column})
    else:
        result = grouped.size().rename(columns={"size": column})
    result[column] = result[column].astype("int64")
    return result


def inbound_volume(events: pd.DataFrame) -> pd.DataFrame:
    """Volumen de entrada: unidades recibidas (suma de `quantity` de inbound_order_created)."""
    return _per_grain(events, INBOUND, "inbound_units_count", units=True)


def outbound_throughput(events: pd.DataFrame) -> pd.DataFrame:
    """Throughput de salida: pedidos preparados y despachados (conteo de outbound_order_created)."""
    return _per_grain(events, OUTBOUND, "outbound_orders_count")


def stockout_frequency(events: pd.DataFrame) -> pd.DataFrame:
    """Frecuencia de quiebre de stock: cruces bajo el mínimo (conteo de stock_threshold_triggered)."""
    return _per_grain(events, STOCKOUT, "stockout_events_count")


def discrepancy_events(events: pd.DataFrame) -> pd.DataFrame:
    """Conteo de apoyo de la Tasa de discrepancia (inventory_discrepancy_detected)."""
    return _per_grain(events, DISCREPANCY, "discrepancy_events_count")


def discrepancy_rate(discrepancy_events_count: pd.Series, outbound_orders_count: pd.Series) -> pd.Series:
    """Tasa de discrepancia: discrepancias / pedidos de salida, 0 si no hubo pedidos (BRIEFING §4)."""
    outbound = outbound_orders_count.astype("float64")
    rate = discrepancy_events_count.astype("float64") / outbound.where(outbound > 0)
    return rate.fillna(0.0).astype("float64")


def combine_weekly_kpis(
    inbound: pd.DataFrame,
    outbound: pd.DataFrame,
    stockouts: pd.DataFrame,
    discrepancies: pd.DataFrame,
) -> pd.DataFrame:
    """T6: una fila por almacén × cliente × semana con los cuatro KPIs."""
    grain = list(GRAIN)
    frames = [inbound, outbound, stockouts, discrepancies]
    if all(frame.empty for frame in frames):
        return pd.DataFrame({column: pd.Series(dtype="object") for column in OUTPUT_COLUMNS})
    kpis = frames[0]
    for frame in frames[1:]:
        kpis = kpis.merge(frame, on=grain, how="outer")
    for column in KPI_COLUMNS[:-1]:
        kpis[column] = kpis[column].fillna(0).astype("int64")
    kpis["discrepancy_rate"] = discrepancy_rate(kpis["discrepancy_events_count"], kpis["outbound_orders_count"])
    kpis["warehouse"] = kpis["warehouse"].astype(object)
    kpis["client_id"] = kpis["client_id"].astype(object)
    return (
        kpis[list(OUTPUT_COLUMNS)]
        .sort_values(["week_start", "warehouse", "client_id"], kind="stable")
        .reset_index(drop=True)
    )


def aggregate_weekly_kpis(events: pd.DataFrame) -> pd.DataFrame:
    """T5 + T6 sobre eventos ya preparados."""
    return combine_weekly_kpis(
        inbound_volume(events),
        outbound_throughput(events),
        stockout_frequency(events),
        discrepancy_events(events),
    )


def transform_events(
    raw_events: pd.DataFrame,
    excluded_user_ids: Iterable[str] = (),
) -> TransformResult:
    """Encadena T1–T6 y devuelve los KPIs con las estadísticas para `pipeline_runs`."""
    prepared = prepare_events(raw_events, excluded_user_ids)
    kpis = aggregate_weekly_kpis(prepared.events)
    return TransformResult(kpis=kpis, stats={**prepared.stats, "kpi_rows": int(len(kpis))})


def validate_kpis(kpis: pd.DataFrame, weeks: list[date]) -> list[str]:
    """Contratos del BRIEFING sobre el resultado. Devuelve la lista de violaciones."""
    problems: list[str] = []
    if kpis.empty:
        return problems
    if kpis.duplicated(subset=list(GRAIN)).any():
        problems.append("Hay filas duplicadas para (warehouse, client_id, week_start).")
    if not kpis["warehouse"].isin(WAREHOUSES).all():
        problems.append("Hay almacenes fuera de los_angeles/zaragoza.")
    if not kpis["week_start"].isin(weeks).all():
        problems.append("Hay semanas fuera de la ventana de la corrida.")
    if (kpis[list(KPI_COLUMNS)] < 0).any().any():
        problems.append("Hay KPIs negativos.")
    expected_rate = (
        kpis["discrepancy_events_count"] / kpis["outbound_orders_count"].where(kpis["outbound_orders_count"] > 0)
    ).fillna(0.0)
    if not np.allclose(kpis["discrepancy_rate"].astype(float), expected_rate.astype(float)):
        problems.append("discrepancy_rate no coincide con discrepancias / pedidos de salida.")
    return problems


def normalize_warehouse(value: Any) -> str:
    """'Los Angeles' → 'los_angeles' (misma regla que `telemetry-mappers.ts`)."""
    return "_".join(str(value).strip().lower().split())


def capture_coverage(
    events_by_warehouse: dict[str, dict[str, int]],
    domain_orders: pd.DataFrame,
    warning_threshold: float,
) -> tuple[dict[str, Any], list[str]]:
    """Eventos de órdenes frente a filas de `stock_entries`/`stock_exits` (§10.3).

    Devuelve la cobertura por almacén y tipo, y los avisos: `low_capture_coverage`
    si se capturó menos del umbral, `coverage_above_one` si hay más eventos que
    órdenes (posibles duplicados) y `capture_silence` si hubo órdenes sin eventos.
    """
    orders = domain_orders.assign(warehouse=domain_orders["warehouse"].map(normalize_warehouse))
    orders = orders.groupby(["warehouse", "kind"], as_index=False)["orders"].sum()
    coverage: dict[str, Any] = {}
    warnings: list[str] = []
    for warehouse in WAREHOUSES:
        coverage[warehouse] = {}
        for kind in ("inbound", "outbound"):
            matched = orders.loc[(orders["warehouse"] == warehouse) & (orders["kind"] == kind), "orders"]
            domain_count = int(matched.sum())
            event_count = int(events_by_warehouse.get(warehouse, {}).get(kind, 0))
            ratio = None if domain_count == 0 else round(event_count / domain_count, 4)
            coverage[warehouse][kind] = {"events": event_count, "orders": domain_count, "coverage": ratio}
            if domain_count > 0 and event_count == 0:
                warnings.append(f"capture_silence:{warehouse}:{kind}")
            elif ratio is not None and ratio < warning_threshold:
                warnings.append(f"low_capture_coverage:{warehouse}:{kind}")
            elif ratio is not None and ratio > 1:
                warnings.append(f"coverage_above_one:{warehouse}:{kind}")
    return coverage, warnings


def kpis_to_records(kpis: pd.DataFrame) -> list[dict[str, Any]]:
    """Filas listas para el upsert, con tipos nativos de Python."""
    records = []
    for row in kpis.to_dict(orient="records"):
        records.append(
            {
                "warehouse": str(row["warehouse"]),
                "client_id": str(row["client_id"]),
                "week_start": row["week_start"],
                "inbound_units_count": int(row["inbound_units_count"]),
                "outbound_orders_count": int(row["outbound_orders_count"]),
                "stockout_events_count": int(row["stockout_events_count"]),
                "discrepancy_events_count": int(row["discrepancy_events_count"]),
                "discrepancy_rate": float(row["discrepancy_rate"]),
            }
        )
    return records
