"""Pipeline de análisis técnico de la telemetría de TrackFlow.

Cada métrica responde una pregunta operacional sobre el sistema (volumen,
errores, latencia, autenticación) y sigue siempre el mismo orden:

    cargar (SQL) → refinar (Pandas) → convertir tipos → agrupar → agregar → servir

- La ventana `[start_date, end_date)` (inicio inclusivo, fin exclusivo, UTC) y los
  `event_type` se filtran **una sola vez en SQL**: nunca se carga la tabla entera.
- Las dimensiones de `tags` se extraen y se limpian en Pandas.
- `timestamp` se convierte con `pd.to_datetime(..., utc=True)` antes de agrupar.
- No hay bucles: solo operaciones vectorizadas de Pandas.
- Las funciones no tienen efectos secundarios: con los mismos parámetros y los
  mismos datos devuelven el mismo resultado. La caché vive en el endpoint.

Este módulo no importa nada de `services/api`: recibe el `engine` como parámetro,
así funciona igual con la API arrancada desde la raíz del repo o desde el
contenedor, donde `/app` es `services/`.
"""

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import bindparam, text


AUTH_EVENT_TYPES = ("user_login_failed", "user_login_succeeded")
LATENCY_EVENT_TYPE = "api_latency_recorded"
LATENCY_PERCENTILE = 0.95


def _load_events(
    engine,
    start_date: datetime,
    end_date: datetime,
    columns: str,
    event_types: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Carga (SQL): solo las columnas y filas que necesita la métrica."""
    sql = (
        f"select {columns} from public.telemetry_events "
        'where "timestamp" >= :start_date and "timestamp" < :end_date'
    )
    params: dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    statement = text(sql)
    if event_types:
        statement = text(sql + " and event_type in :event_types").bindparams(
            bindparam("event_types", expanding=True)
        )
        params["event_types"] = list(event_types)
    with engine.connect() as connection:
        return pd.read_sql(statement, connection, params=params)


def _with_utc_date(events: pd.DataFrame) -> pd.DataFrame:
    """Convertir tipos: datetime UTC y fecha del evento antes de cualquier groupby."""
    events = events.copy()
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True, format="ISO8601")
    events["date"] = events["timestamp"].dt.date
    return events


def _records(result: pd.DataFrame) -> list[dict[str, Any]]:
    """Servir: lista de dicts serializable a JSON (fechas como texto ISO)."""
    result = result.reset_index()
    result = result.drop(columns=["index"], errors="ignore")
    if "date" in result.columns:
        result["date"] = result["date"].astype(str)
    return result.to_dict(orient="records")


def events_per_day(start_date: datetime, end_date: datetime, engine) -> list[dict[str, Any]]:
    """¿Qué eventos ocurren cada día y con qué frecuencia?

    Volumen de eventos por día y `event_type`, de mayor a menor dentro de cada día.
    """
    events = _load_events(engine, start_date, end_date, '"timestamp", event_type')
    if events.empty:
        return []
    events = _with_utc_date(events)
    volume = (
        events.groupby(["date", "event_type"])
        .agg(events=("event_type", "count"))
        .sort_values(["date", "events"], ascending=[True, False])
    )
    return _records(volume)


def error_rate_per_day(start_date: datetime, end_date: datetime, engine) -> list[dict[str, Any]]:
    """¿Qué proporción de los eventos de cada día son errores o avisos?

    Carga todos los tipos de la ventana (una tasa necesita el total) y deriva en
    Pandas `is_error` (`level = 'error'`) e `is_warning` (`level = 'warn'`).
    """
    events = _load_events(engine, start_date, end_date, '"timestamp", level')
    if events.empty:
        return []
    events = events.dropna(subset=["level"])
    events = events.assign(
        is_error=events["level"].eq("error"),
        is_warning=events["level"].eq("warn"),
    )
    events = _with_utc_date(events)
    daily = events.groupby("date").agg(
        total_events=("level", "count"),
        error_events=("is_error", "sum"),
        warning_events=("is_warning", "sum"),
    )
    daily = daily.assign(
        error_rate=(daily["error_events"] / daily["total_events"]).round(4),
        warning_rate=(daily["warning_events"] / daily["total_events"]).round(4),
    )
    return _records(daily)


def api_latency_per_day(start_date: datetime, end_date: datetime, engine) -> list[dict[str, Any]]:
    """¿Qué endpoints responden más lento cada día?

    Latencia observada por el cliente por día, endpoint y método. Las mediciones
    están muestreadas (§8 del plan): cada observación pesa `1 / sample_rate`, de
    modo que `estimated_requests`, `avg_ms` y `p95_ms` estiman el tráfico real.
    """
    events = _load_events(
        engine, start_date, end_date, '"timestamp", tags', event_types=(LATENCY_EVENT_TYPE,)
    )
    if events.empty:
        return []
    dimensions = pd.json_normalize(events["tags"].tolist())
    dimensions = dimensions.reindex(
        columns=["api_endpoint", "http_method", "duration_ms", "sample_rate"]
    )
    events = pd.concat([events[["timestamp"]].reset_index(drop=True), dimensions], axis=1)
    events = events.dropna(subset=["api_endpoint", "http_method", "duration_ms", "sample_rate"])
    events = events[events["sample_rate"] > 0]
    if events.empty:
        return []
    events = events.assign(
        duration_ms=events["duration_ms"].astype(float),
        weight=1 / events["sample_rate"].astype(float),
    )
    events = events.assign(weighted_ms=events["duration_ms"] * events["weight"])
    events = _with_utc_date(events)

    keys = ["date", "api_endpoint", "http_method"]
    summary = events.groupby(keys).agg(
        observations=("duration_ms", "count"),
        estimated_requests=("weight", "sum"),
        weighted_ms=("weighted_ms", "sum"),
        max_ms=("duration_ms", "max"),
    )
    summary = summary.assign(
        avg_ms=(summary["weighted_ms"] / summary["estimated_requests"]).round(1),
        estimated_requests=summary["estimated_requests"].round(1),
    ).drop(columns=["weighted_ms"])

    # p95 ponderado: primera duración cuyo peso acumulado alcanza el 95 % del grupo.
    ordered = events.sort_values(keys + ["duration_ms"])
    cumulative = ordered.groupby(keys)["weight"].cumsum()
    group_total = ordered.groupby(keys)["weight"].transform("sum")
    at_percentile = ordered[cumulative / group_total >= LATENCY_PERCENTILE]
    p95 = at_percentile.groupby(keys).agg(p95_ms=("duration_ms", "first"))

    latency = summary.join(p95).sort_values(["date", "p95_ms"], ascending=[True, False])
    latency = latency[["observations", "estimated_requests", "avg_ms", "p95_ms", "max_ms"]]
    return _records(latency)


def auth_failure_rate(start_date: datetime, end_date: datetime, engine) -> list[dict[str, Any]]:
    """¿Qué proporción de los intentos de login falla cada día?

    `user_login_failed / (user_login_failed + user_login_succeeded)` por día.
    Ambos tipos se cargan en una sola consulta con `event_type IN (...)`.
    """
    events = _load_events(
        engine, start_date, end_date, '"timestamp", event_type', event_types=AUTH_EVENT_TYPES
    )
    if events.empty:
        return []
    events = events.assign(is_failure=events["event_type"].eq("user_login_failed"))
    events = _with_utc_date(events)
    daily = events.groupby("date").agg(
        login_attempts=("event_type", "count"),
        login_failures=("is_failure", "sum"),
    )
    daily = daily.assign(
        failure_rate=(daily["login_failures"] / daily["login_attempts"]).round(4)
    )
    return _records(daily)


def build_report_metrics(start_date: datetime, end_date: datetime, engine) -> dict[str, Any]:
    """Ejecuta todas las métricas con la misma ventana, resuelta por el endpoint."""
    return {
        "events_per_day": events_per_day(start_date, end_date, engine),
        "error_rate_per_day": error_rate_per_day(start_date, end_date, engine),
        "api_latency_per_day": api_latency_per_day(start_date, end_date, engine),
        "auth_failure_rate": auth_failure_rate(start_date, end_date, engine),
    }
