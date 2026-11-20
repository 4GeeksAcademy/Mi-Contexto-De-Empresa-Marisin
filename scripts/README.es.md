# Carpeta `scripts`

Esta carpeta contiene **scripts auxiliares** del monorepo: automatizaciones de desarrollo, utilidades de mantenimiento, tareas repetitivas (setup, lint, migraciones, generación de datos, etc.) y tooling interno.

- **Propósito principal**: agrupar herramientas de soporte que no pertenecen a una app/agente/pipeline específico, pero facilitan el trabajo del equipo.
- **Recomendación**: documenta cada script (qué hace, parámetros, requisitos, ejemplos de uso) y procura que sean reproducibles (y seguros) en distintos entornos.

## `nightly_export.py` — job nocturno de telemetría (Ticket #DEV-53)

Exporta las filas de `telemetry_events` de ayer (UTC) a `data/raw/telemetry_AAAA-MM-DD.csv` (solo si el fichero no existe; snapshot de backup y auditoría), lanza el pipeline de desempeño de negocio como subproceso y registra cada ejecución en `public.job_runs` (`pending → processing → completed | failed`) mediante `services/job_runner.py`. El estado `processing` es el lock: una segunda instancia aborta en silencio. Idempotente por `(job_name, target_date)`.

```bash
python scripts/nightly_export.py                         # ayer (UTC)
TARGET_DATE=2026-11-18 python scripts/nightly_export.py  # un día concreto
```

Requiere `public.job_runs` (`services/sql/001_job_runs.sql`). Lo dispara el crontab del sistema (`15 1 * * *`, ver `infra/cron/`), nunca dentro de FastAPI. Plan: `memory-bank/history/2026-11-19_nightly-export.md`.
