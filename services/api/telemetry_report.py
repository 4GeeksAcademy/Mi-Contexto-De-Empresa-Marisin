"""Contrato y periodo de `GET /telemetry/report`.

El endpoint resuelve la ventana una sola vez y la pasa a cada métrica del
pipeline (`services/telemetry/analysis.py`), que la aplica en SQL. Inicio
inclusivo, fin exclusivo, siempre en UTC.
"""

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_REPORT_WINDOW = timedelta(days=7)
MAX_REPORT_WINDOW = timedelta(days=92)


class ReportPeriodError(ValueError):
    """La ventana pedida no es válida (orden o tamaño)."""


class ReportPeriod(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime


class EventsPerDay(BaseModel):
    date: str
    event_type: str
    events: int


class ErrorRatePerDay(BaseModel):
    date: str
    total_events: int
    error_events: int
    warning_events: int
    error_rate: float
    warning_rate: float


class ApiLatencyPerDay(BaseModel):
    date: str
    api_endpoint: str
    http_method: str
    observations: int
    estimated_requests: float
    avg_ms: float
    p95_ms: float
    max_ms: float


class AuthFailureRate(BaseModel):
    date: str
    login_attempts: int
    login_failures: int
    failure_rate: float


class ReportMetrics(BaseModel):
    events_per_day: list[EventsPerDay]
    error_rate_per_day: list[ErrorRatePerDay]
    api_latency_per_day: list[ApiLatencyPerDay]
    auth_failure_rate: list[AuthFailureRate]


class TelemetryReport(BaseModel):
    period: ReportPeriod
    metrics: ReportMetrics


def _as_utc(value: datetime) -> datetime:
    """Una fecha sin zona se interpreta como UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_period(
    start_date: datetime | None,
    end_date: datetime | None,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Resuelve `[start, end)` en UTC.

    Sin parámetros: los últimos 7 días hasta ahora. `now` se trunca al minuto para
    que peticiones seguidas sin parámetros compartan la misma clave de caché; si
    no, cada petición tendría una ventana distinta y la caché nunca acertaría.
    """
    default_end = _as_utc(now).replace(second=0, microsecond=0)
    end = _as_utc(end_date) if end_date is not None else default_end
    start = _as_utc(start_date) if start_date is not None else end - DEFAULT_REPORT_WINDOW
    if start >= end:
        raise ReportPeriodError("start_date must be earlier than end_date")
    if end - start > MAX_REPORT_WINDOW:
        raise ReportPeriodError("The report window cannot exceed 92 days")
    return start, end


def report_cache_key(start: datetime, end: datetime) -> str:
    return f"telemetry:report:{start.isoformat()}|{end.isoformat()}"
