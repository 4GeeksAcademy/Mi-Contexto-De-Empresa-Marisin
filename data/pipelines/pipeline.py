"""Pipeline de Desempeño de Negocio de TrackFlow (Prefect 3).

Produce el "Reporte Semanal de Desempeño por Almacén y Cliente" del BRIEFING de
data pipelines: lee en solo lectura los eventos `inbound_order_created`,
`outbound_order_created`, `stock_threshold_triggered` e
`inventory_discrepancy_detected` de `public.telemetry_events` y escribe
`reporting.weekly_warehouse_client_performance`, con el log de cada corrida en
`reporting.pipeline_runs`. Diseño: `data/pipelines/PIPELINE_DESIGN.md`.

Frecuencia: semanal, los lunes a las 05:00 UTC (antes de las 07:00 de Madrid),
recalculando las 4 últimas semanas cerradas.

Ejecución (desde la raíz del repo, con el entorno virtual activado):

    python data/pipelines/pipeline.py                          # 4 últimas semanas cerradas
    python data/pipelines/pipeline.py --week-start 2026-11-16  # una semana concreta
    python data/pipelines/pipeline.py --serve                  # programación semanal (cron)

Topología (Parte 3): el flow principal `weekly_warehouse_client_performance`
solo coordina; cada etapa es un subflow con entradas y salidas explícitas.

    open_pipeline_run
    → extract_warehouse_client_kpi_events          (subflow: extracción)
    → compute_weekly_warehouse_client_kpis         (subflow: transformación, un task por KPI)
    → [check_capture_coverage, opcional]           (subflow: calidad)
    → load_weekly_warehouse_client_performance     (subflow: carga)
    → [export_weekly_performance_snapshot, opcional] (subflow: eval)
    → close_pipeline_run
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

# Ejecutado como script (`python data/pipelines/pipeline.py`), Python solo añade
# `data/pipelines/` al path: se añade la raíz del repo para importar `data.*`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from prefect.context import TaskRunContext
from prefect.exceptions import MissingContextError
from prefect.runtime import flow_run
from prefect.states import Cancelled, State

from data.pipelines import extract, load, runs
from data.pipelines.config import REPO_ROOT, get_engine, load_config
from data.process import weekly_kpis
from data.process.weekly_kpis import PreparedEvents, TransformResult


FLOW_NAME = "weekly_warehouse_client_performance"
SCHEDULE_CRON = "0 5 * * 1"  # lunes 05:00 UTC
EVAL_SNAPSHOT_PATH = (
    REPO_ROOT / "data" / "eval" / "snapshots" / "weekly_warehouse_client_performance_latest.json"
)


def task_logger() -> logging.Logger | logging.LoggerAdapter:
    """Logger del run de Prefect; fuera de un run (tests con `task.fn`), el logger estándar."""
    try:
        return get_run_logger()
    except MissingContextError:
        return logging.getLogger(__name__)


class PipelineStageError(RuntimeError):
    """Una etapa crítica falló tras agotar sus reintentos."""

    def __init__(self, stage: str, cause: BaseException | None):
        self.stage = stage
        self.cause = cause
        detail = f"{type(cause).__name__}: {cause}" if cause is not None else "sin detalle"
        super().__init__(f"La etapa {stage} falló: {detail}")


class KpiValidationError(ValueError):
    """El resultado de la transformación viola los contratos del BRIEFING."""


# ---------------------------------------------------------------------------
# Tasks de control de la corrida
# ---------------------------------------------------------------------------


# 2 reintentos (cada 5 s): es una inserción pequeña en Supabase. Si tres intentos
# en ~10 s no bastan, la base de datos no está disponible y conviene fallar pronto:
# la ausencia de la fila del lunes dispara la alerta de §9.4 del diseño.
@task(name="open_pipeline_run", retries=2, retry_delay_seconds=5, cache_policy=NO_CACHE)
def open_pipeline_run(
    run_id: UUID,
    trigger: str,
    triggered_by: str | None,
    window_start: date,
    window_end: date,
    stale_minutes: int,
) -> runs.OpenRunResult:
    prefect_id = flow_run.id
    return runs.open_run(
        get_engine(),
        run_id=run_id,
        trigger=trigger,
        triggered_by=triggered_by,
        window_start=window_start,
        window_end=window_end,
        prefect_flow_run_id=UUID(prefect_id) if prefect_id else None,
        stale_minutes=stale_minutes,
    )


# 2 reintentos (cada 5 s): un UPDATE de una fila. Si falla, no se pierde el dato
# (la corrida queda como `stale_run` en la siguiente), así que no merece esperar más.
@task(name="heartbeat_pipeline_run", retries=2, retry_delay_seconds=5, cache_policy=NO_CACHE)
def heartbeat_pipeline_run(run_id: UUID, phase: str, counters: dict[str, Any]) -> None:
    runs.heartbeat(get_engine(), run_id, phase, **counters)


# 2 reintentos (cada 5 s): mismo criterio que open_pipeline_run.
@task(name="close_pipeline_run", retries=2, retry_delay_seconds=5, cache_policy=NO_CACHE)
def close_pipeline_run(
    run_id: UUID,
    status: str,
    warnings: list[str],
    capture_coverage: dict[str, Any] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    runs.close_run(
        get_engine(),
        run_id,
        status=status,
        warnings=warnings,
        capture_coverage=capture_coverage,
        error_type=error_type,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# Extracción
# ---------------------------------------------------------------------------


# 3 reintentos con espera creciente (10 + 30 + 60 s ≈ 1,7 min): absorben cortes
# breves del pooler de Supabase y timeouts de red. Más allá, el fallo ya no es
# transitorio y conviene alertar; el cron de las 05:00 UTC deja ~2 h de margen.
# Sin caché: la extracción debe leer siempre la fuente para recoger eventos tardíos.
# Sin timeout_seconds: en una task síncrona Prefect no puede interrumpir una consulta
# bloqueante; la espera de conexión ya está acotada con connect_timeout=10 (config.py).
@task(
    name="extract_kpi_events",
    retries=3,
    retry_delay_seconds=[10, 30, 60],
    cache_policy=NO_CACHE,
)
def extract_kpi_events(window_start: date, window_end: date) -> dict[str, Any]:
    logger = task_logger()
    engine = get_engine()
    events = extract.extract_events(engine, window_start, window_end)
    signals = extract.extract_source_signals(engine, window_start, window_end)
    logger.info(
        "Extraídos %d eventos de negocio (%d eventos en total) entre %s y %s",
        len(events),
        signals["total_events"],
        window_start,
        window_end,
    )
    return {"events": events, "signals": signals}


# ---------------------------------------------------------------------------
# Transformación: preparación + un task por KPI del BRIEFING
# ---------------------------------------------------------------------------


PREPARE_CACHE_NAMESPACE = "prepare-kpi-events"


def _prepare_cache_key(context: TaskRunContext, parameters: dict[str, Any]) -> str:
    """Clave de caché de prepare_kpi_events.

    La define el nombre del task (`prepare-kpi-events`, para no compartir clave con
    ningún otro task ni con el `transform_weekly_kpis` de la Parte 2, que guardaba un
    `TransformResult`), la versión de la lógica (`weekly_kpis.TRANSFORM_VERSION`),
    el contenido exacto de los eventos extraídos (huella de todas sus filas) y la
    lista de `excluded_user_ids`. Si llega un evento tardío o cambia la
    configuración, la clave cambia y se recalcula; si no, se reutiliza el resultado.
    """
    return f"{PREPARE_CACHE_NAMESPACE}-" + weekly_kpis.transform_cache_key(
        parameters["raw_events"], parameters["excluded_user_ids"]
    )


# Caché de 1 hora: si la misma extracción ya se preparó con éxito en la última
# hora (p. ej. un reintento manual tras un fallo en la carga), se reutiliza el
# resultado. Una hora cubre los reintentos de una corrida y los disparos manuales
# seguidos sin servir nunca un resultado de otra semana: la clave depende de los datos.
@task(
    name="prepare_kpi_events",
    cache_key_fn=_prepare_cache_key,
    cache_expiration=timedelta(hours=1),
    persist_result=True,
)
def prepare_kpi_events(raw_events: pd.DataFrame, excluded_user_ids: tuple[str, ...]) -> PreparedEvents:
    """Refina tipos, rechaza filas inválidas, deduplica por eventId, excluye verificación y añade week_start."""
    prepared = weekly_kpis.prepare_events(raw_events, excluded_user_ids)
    stats = prepared.stats
    task_logger().info(
        "Preparación: %d eventos válidos, %d duplicados, %d excluidos, %d rechazados",
        len(prepared.events),
        stats["duplicates_dropped"],
        stats["events_excluded"],
        stats["events_rejected"],
    )
    return prepared


@task(name="compute_inbound_volume", cache_policy=NO_CACHE)
def compute_inbound_volume(events: pd.DataFrame) -> pd.DataFrame:
    """KPI Volumen de entrada → `inbound_units_count`."""
    return weekly_kpis.inbound_volume(events)


@task(name="compute_outbound_throughput", cache_policy=NO_CACHE)
def compute_outbound_throughput(events: pd.DataFrame) -> pd.DataFrame:
    """KPI Throughput de salida → `outbound_orders_count`."""
    return weekly_kpis.outbound_throughput(events)


@task(name="compute_stockout_frequency", cache_policy=NO_CACHE)
def compute_stockout_frequency(events: pd.DataFrame) -> pd.DataFrame:
    """KPI Frecuencia de quiebre de stock → `stockout_events_count`."""
    return weekly_kpis.stockout_frequency(events)


@task(name="compute_discrepancy_rate", cache_policy=NO_CACHE)
def compute_discrepancy_rate(
    events: pd.DataFrame,
    inbound: pd.DataFrame,
    outbound: pd.DataFrame,
    stockouts: pd.DataFrame,
) -> pd.DataFrame:
    """KPI Tasa de discrepancia → `discrepancy_events_count` y `discrepancy_rate`.

    Une los cuatro KPIs en el grano del BRIEFING (almacén × cliente × semana) y
    calcula discrepancias / pedidos de salida, con 0 si no hubo pedidos.
    """
    return weekly_kpis.combine_weekly_kpis(
        inbound, outbound, stockouts, weekly_kpis.discrepancy_events(events)
    )


# Sin reintentos: valida en memoria; repetirla daría el mismo resultado.
@task(name="validate_weekly_kpis", cache_policy=NO_CACHE)
def validate_weekly_kpis(kpis: pd.DataFrame, weeks: list[date]) -> int:
    problems = weekly_kpis.validate_kpis(kpis, weeks)
    if problems:
        raise KpiValidationError("; ".join(problems))
    return len(kpis)


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------


# 3 reintentos cada 30 s: la carga es una sola transacción idempotente (upsert por
# la clave natural del BRIEFING), así que reintentar es seguro. 3 × 30 s cubre un
# reinicio del pooler de Supabase sin comerse el margen del reporte del lunes.
@task(
    name="load_weekly_kpis",
    retries=3,
    retry_delay_seconds=30,
    cache_policy=NO_CACHE,
)
def load_weekly_kpis(run_id: UUID, kpis: pd.DataFrame, weeks: list[date]) -> dict[str, int]:
    counts = load.upsert_weekly_kpis(get_engine(), run_id, weekly_kpis.kpis_to_records(kpis), weeks)
    task_logger().info("Carga: %s", counts)
    return counts


# ---------------------------------------------------------------------------
# Tasks opcionales (no críticas)
# ---------------------------------------------------------------------------


# 1 reintento (10 s): es un control de calidad; si Supabase falla dos veces, se
# registra un aviso y la corrida sigue sin cobertura.
@task(name="check_capture_coverage", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def check_capture_coverage(
    window_start: date,
    window_end: date,
    events_by_warehouse: dict[str, dict[str, int]],
    warning_threshold: float,
) -> tuple[dict[str, Any], list[str]]:
    domain_orders = extract.extract_domain_orders(get_engine(), window_start, window_end)
    return weekly_kpis.capture_coverage(events_by_warehouse, domain_orders, warning_threshold)


# Sin reintentos: escribe un fichero local; si falla, solo se pierde el snapshot.
@task(name="export_eval_snapshot", cache_policy=NO_CACHE)
def export_eval_snapshot(
    run_id: UUID,
    weeks: list[date],
    kpis: pd.DataFrame,
    stats: dict[str, Any],
    load_counts: dict[str, int],
    warnings: list[str],
) -> str:
    EVAL_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "run_id": str(run_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weeks": [week.isoformat() for week in weeks],
        "stats": stats,
        "load": load_counts,
        "warnings": warnings,
        "rows": weekly_kpis.kpis_to_records(kpis),
    }
    EVAL_SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str) + "\n", encoding="utf-8")
    return str(EVAL_SNAPSHOT_PATH)


# ---------------------------------------------------------------------------
# Subflows: una etapa cada uno, con entradas y salidas explícitas
# ---------------------------------------------------------------------------
# Los subflows que reciben DataFrames desactivan `validate_parameters`: Pydantic no
# sabe validar un DataFrame, y la forma ya la comprueba `weekly_kpis.ensure_raw_events`.


@flow(name="extract_warehouse_client_kpi_events")
def extract_warehouse_client_kpi_events_flow(window_start: date, window_end: date) -> dict[str, Any]:
    """Extracción: eventos de los cuatro KPIs + señales de silencio de `telemetry_events`.

    Devuelve `{"events": DataFrame, "signals": {...}}`. Se puede ejecutar sola:
    `extract_warehouse_client_kpi_events_flow(date(2026, 11, 16), date(2026, 11, 23))`.
    """
    return extract_kpi_events(window_start, window_end)


@flow(name="compute_weekly_warehouse_client_kpis", validate_parameters=False)
def compute_weekly_warehouse_client_kpis_flow(
    raw_events: pd.DataFrame,
    excluded_user_ids: tuple[str, ...],
    weeks: list[date],
) -> TransformResult:
    """Transformación: Volumen de entrada, Throughput de salida, Frecuencia de
    quiebre de stock y Tasa de discrepancia por almacén × cliente × semana ISO.

    No toca la base de datos: se puede ejecutar sola con un DataFrame en memoria.
    """
    prepared = prepare_kpi_events(raw_events, excluded_user_ids)
    inbound = compute_inbound_volume(prepared.events)
    outbound = compute_outbound_throughput(prepared.events)
    stockouts = compute_stockout_frequency(prepared.events)
    kpis = compute_discrepancy_rate(prepared.events, inbound, outbound, stockouts)
    validate_weekly_kpis(kpis, weeks)
    return TransformResult(kpis=kpis, stats={**prepared.stats, "kpi_rows": int(len(kpis))})


@flow(name="load_weekly_warehouse_client_performance", validate_parameters=False)
def load_weekly_warehouse_client_performance_flow(
    run_id: UUID,
    kpis: pd.DataFrame,
    weeks: list[date],
) -> dict[str, int]:
    """Carga idempotente en `reporting.weekly_warehouse_client_performance`.

    Devuelve los conteos `rows_inserted`, `rows_updated`, `rows_unchanged` y `rows_deleted`.
    """
    return load_weekly_kpis(run_id, kpis, weeks)


@flow(name="check_capture_coverage")
def check_capture_coverage_flow(
    window_start: date,
    window_end: date,
    events_by_warehouse: dict[str, dict[str, int]],
    warning_threshold: float,
) -> tuple[dict[str, Any], list[str]]:
    """Opcional: cobertura de captura frente a `stock_entries`/`stock_exits` (§10.3)."""
    return check_capture_coverage(window_start, window_end, events_by_warehouse, warning_threshold)


@flow(name="export_weekly_performance_snapshot", validate_parameters=False)
def export_weekly_performance_snapshot_flow(
    run_id: UUID,
    weeks: list[date],
    kpis: pd.DataFrame,
    stats: dict[str, Any],
    load_counts: dict[str, int],
    warnings: list[str],
) -> str:
    """Opcional: snapshot de eval de la corrida en `data/eval/snapshots/`."""
    return export_eval_snapshot(run_id, weeks, kpis, stats, load_counts, warnings)


# ---------------------------------------------------------------------------
# Flow principal
# ---------------------------------------------------------------------------


def _required(state: State, stage: str) -> Any:
    """Etapa crítica: si su state no es Completed, se detiene el flow."""
    if state.is_completed():
        return state.result()
    raise PipelineStageError(stage, state.result(raise_on_failure=False))


def _optional_failure(state: State, name: str) -> str:
    cause = state.result(raise_on_failure=False)
    return f"{name}_failed:{type(cause).__name__}"


@flow(name=FLOW_NAME)
def weekly_warehouse_client_performance_flow(
    week_start: date | None = None,
    lookback_weeks: int | None = None,
    trigger: str = "scheduled",
    run_id: UUID | None = None,
    triggered_by: str | None = None,
) -> dict[str, Any] | State:
    """Coordina los subflows: recalcula las semanas de la ventana y las carga de forma idempotente."""
    logger = get_run_logger()
    config = load_config()
    today = datetime.now(timezone.utc).date()
    weeks = weekly_kpis.resolve_weeks(today, week_start, lookback_weeks or config.lookback_weeks)
    window_start, window_end = weekly_kpis.window_bounds(weeks)
    run_id = run_id or uuid4()
    logger.info("Corrida %s (%s): semanas %s", run_id, trigger, [week.isoformat() for week in weeks])

    opened = open_pipeline_run(
        run_id, trigger, triggered_by, window_start, window_end, config.stale_run_minutes
    )
    if not opened.opened:
        message = f"Ya hay una corrida en marcha ({opened.active_run_id}); esta se cancela."
        logger.warning(message)
        return Cancelled(message=message)

    warnings: list[str] = []
    coverage: dict[str, Any] | None = None
    try:
        # Subflows críticos: return_state=True para registrar el fallo en pipeline_runs
        # antes de detener el flow, en lugar de dejar que la excepción se propague sola.
        extracted = _required(
            extract_warehouse_client_kpi_events_flow(window_start, window_end, return_state=True),
            "extract",
        )
        signals = extracted["signals"]
        heartbeat_pipeline_run(
            run_id,
            "extract",
            {
                "events_extracted": len(extracted["events"]),
                "source_max_timestamp": signals["source_max_timestamp"],
            },
        )
        if signals["technical_events"] == 0:
            warnings.append("capture_silence:no_technical_events")

        transformed: TransformResult = _required(
            compute_weekly_warehouse_client_kpis_flow(
                extracted["events"], config.excluded_user_ids, weeks, return_state=True
            ),
            "transform",
        )
        stats = transformed.stats
        heartbeat_pipeline_run(
            run_id,
            "validate",
            {
                "duplicates_dropped": stats["duplicates_dropped"],
                "events_excluded": stats["events_excluded"],
                "events_rejected": stats["events_rejected"],
                "events_by_type": stats["events_by_type"],
            },
        )
        warnings.extend(f"rejected:{reason}:{count}" for reason, count in stats["rejected_by_reason"].items())

        # Opcional: si falla, se anota el aviso y la carga sigue.
        coverage_state = check_capture_coverage_flow(
            window_start,
            window_end,
            stats["events_by_warehouse"],
            config.coverage_warning_threshold,
            return_state=True,
        )
        if coverage_state.is_completed():
            coverage, coverage_warnings = coverage_state.result()
            warnings.extend(coverage_warnings)
        else:
            warnings.append(_optional_failure(coverage_state, "check_capture_coverage"))
            logger.warning("check_capture_coverage falló; la corrida continúa sin cobertura.")

        load_counts = _required(
            load_weekly_warehouse_client_performance_flow(
                run_id, transformed.kpis, weeks, return_state=True
            ),
            "load",
        )

        # Opcional: el snapshot de eval no debe tumbar una carga ya confirmada.
        snapshot_state = export_weekly_performance_snapshot_flow(
            run_id, weeks, transformed.kpis, stats, load_counts, warnings, return_state=True
        )
        if not snapshot_state.is_completed():
            warnings.append(_optional_failure(snapshot_state, "export_eval_snapshot"))
            logger.warning("export_eval_snapshot falló; la carga ya está confirmada.")
    except Exception as exc:
        cause = exc.cause if isinstance(exc, PipelineStageError) and exc.cause is not None else exc
        close_state = close_pipeline_run(
            run_id,
            "failed",
            warnings,
            coverage,
            error_type=type(cause).__name__,
            error_message=str(exc),
            return_state=True,
        )
        if not close_state.is_completed():
            logger.error("No se pudo registrar el fallo en pipeline_runs; quedará como stale_run.")
        raise

    close_pipeline_run(run_id, "completed", warnings, coverage)
    summary = {
        "run_id": str(run_id),
        "status": "completed",
        "weeks": [week.isoformat() for week in weeks],
        "events_extracted": stats["events_extracted"],
        "kpi_rows": stats["kpi_rows"],
        **load_counts,
        "warnings": warnings,
    }
    logger.info("Corrida completada: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# CLI (sin cambios desde la Parte 2)
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline de Desempeño de Negocio de TrackFlow")
    parser.add_argument("--week-start", type=date.fromisoformat, help="Lunes de la semana a recalcular (AAAA-MM-DD)")
    parser.add_argument("--lookback-weeks", type=int, help="Semanas cerradas a recalcular (por defecto, 4)")
    parser.add_argument(
        "--trigger", choices=("scheduled", "manual", "backfill"), default="manual", help="Origen de la corrida"
    )
    parser.add_argument("--serve", action="store_true", help="Programar el flow con el cron semanal")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.serve:
        weekly_warehouse_client_performance_flow.serve(
            name="weekly",
            cron=SCHEDULE_CRON,
            parameters={"trigger": "scheduled"},
        )
        return
    summary = weekly_warehouse_client_performance_flow(
        week_start=args.week_start,
        lookback_weeks=args.lookback_weeks,
        trigger=args.trigger,
        triggered_by="cli",
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
