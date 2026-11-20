"""Configuración y conexión del pipeline (§9.3 del diseño: Prefect blocks).

- `trackflow-supabase-database-url` (block `Secret`): URI del pooler de Supabase.
  Si existe `DATABASE_URL` en el entorno o en `.env`, se usa esa y no hace falta
  el block, igual que en `services/api/database.py`.
- `trackflow-reporting-config` (block `JSON`): parámetros operativos. Si el block
  no existe, se usan los valores por defecto de `PipelineConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from functools import lru_cache
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool


REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL_SECRET_BLOCK = "trackflow-supabase-database-url"
CONFIG_BLOCK = "trackflow-reporting-config"

logger = logging.getLogger(__name__)


class DatabaseNotConfiguredError(RuntimeError):
    """No hay `DATABASE_URL` ni block `Secret` con la conexión a Supabase."""


@dataclass(frozen=True)
class PipelineConfig:
    lookback_weeks: int = 4
    excluded_user_ids: tuple[str, ...] = ("curl_verification",)
    coverage_warning_threshold: float = 0.9
    stale_run_minutes: int = 30


def load_config() -> PipelineConfig:
    """Lee el block JSON de Prefect; si no existe, devuelve los valores por defecto."""
    defaults = PipelineConfig()
    try:
        from prefect.blocks.system import JSON

        values: dict[str, Any] = dict(JSON.load(CONFIG_BLOCK).value)
    except Exception:  # block inexistente o Prefect sin servidor: configuración por defecto
        logger.info("Block %s no disponible: se usa la configuración por defecto.", CONFIG_BLOCK)
        return defaults
    known = {field.name for field in fields(PipelineConfig)}
    overrides = {key: value for key, value in values.items() if key in known}
    if "excluded_user_ids" in overrides:
        overrides["excluded_user_ids"] = tuple(overrides["excluded_user_ids"])
    return replace(defaults, **overrides)


def database_url() -> str:
    load_dotenv(REPO_ROOT / ".env")
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    try:
        from prefect.blocks.system import Secret

        return str(Secret.load(DATABASE_URL_SECRET_BLOCK).get()).strip()
    except Exception as exc:
        raise DatabaseNotConfiguredError(
            "Define DATABASE_URL en .env o crea el block Secret "
            f"'{DATABASE_URL_SECRET_BLOCK}' con la URI del pooler de Supabase."
        ) from exc


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Engine propio del pipeline, con las mismas opciones que la API."""
    connection_url = make_url(database_url())
    if connection_url.get_backend_name() != "postgresql":
        raise ValueError("DATABASE_URL must be a PostgreSQL connection URI.")
    return create_engine(
        connection_url.set(drivername="postgresql+psycopg2"),
        poolclass=NullPool,
        connect_args={
            "sslmode": os.getenv("TRACKFLOW_DB_SSLMODE", "require"),
            "connect_timeout": 10,
        },
    )
