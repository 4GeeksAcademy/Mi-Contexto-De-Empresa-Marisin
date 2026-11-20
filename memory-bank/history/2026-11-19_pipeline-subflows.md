# Plan por fases — Data Pipeline 3/3: Subflows, tests y dashboard (TrackFlow)

> **Proyecto 4Geeks:** "Hito — Mejora del Pipeline: Subflows y Tests (Parte 3 de 3)".
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-19_pipeline-subflows.md`. Prompt en `prompts/pipeline-subflows/prompt.md`.
> **Rama:** `feature/pipeline-subflows`, creada por Marisin **desde `feature/pipeline-implementation`** (PR #19–#22 pendientes). Cadena: `main ← #19 ← #20 ← #21 ← #22 ← esta`.
> **Ejecución:** Claude implementa y entrega un parche (`git am`); Marisin ejecuta pytest, el pipeline, la API, `npm run typecheck`/`dev`/`build`, la revisión en el navegador y el push.
> **Commit del entregable:** el del refactor del flow lleva el mensaje exacto del enunciado, `feat: refactor business performance pipeline into subflows, add unit tests, and add reporting dashboard`.

---

## 0. Reglas

1. Un commit por acción, prefijo convencional y descripción en español (salvo el commit del entregable).
2. Git solo en local para quien implementa; Marisin crea la rama, aplica los parches y hace push.
3. Nada de `git add .` / `-A` / `git add data/`; el JSON local de TinyDB de proveedores nunca se nombra ni se commitea; ningún `.env*` se lee ni se edita.
4. `telemetry_events`, `services/telemetry/analysis.py` y `GET /telemetry/report` no se tocan. Tampoco `services/reporting/` ni el esquema `reporting`: el dashboard consume los endpoints de la Parte 2 tal cual.
5. Sin dependencias nuevas. En el backoffice, nada de librerías de gráficos: barras con Tailwind.
6. Tras `npm run typecheck`: `git restore uis/backoffice/tsconfig.tsbuildinfo`. Tras `npm run dev`: `git restore uis/backoffice/next-env.d.ts`. Ante "Upgrade now" de Next, **Skip**.

---

## 1. Rúbrica (resumen)

- El flow principal de `data/pipelines/pipeline.py` invoca **≥ 3 subflows** (`@flow`) con entradas y salidas explícitas, ejecutables por separado; los opcionales como subflows con `return_state=True`.
- `tests/pipelines/test_pipeline.py` con **≥ 3 tests** de tasks de transformación, aislados (datos en memoria con forma de telemetría), **≥ 1 defensivo** y **≥ 1 KPI calculado a mano** frente al BRIEFING; `python -m pytest tests/pipelines/test_pipeline.py` sin errores.
- `python data/pipelines/pipeline.py` sigue funcionando (CLI de la Parte 2).
- Nombres con el vocabulario del BRIEFING (nada de `extract_data`).
- Dashboard en `uis/backoffice/` con cada KPI de "KPIs a medir", con su nombre, el periodo y legible para el CEO, alimentado por `services/reporting/`.
- Actividad adicional (opcional): mejoras de las preguntas de diseño anotadas en `PIPELINE_DESIGN.md`.

## 2. Decisiones (D23–D31)

| # | Decisión | Por qué |
|---|---|---|
| D23 | 5 subflows: `extract_warehouse_client_kpi_events`, `compute_weekly_warehouse_client_kpis`, `load_weekly_warehouse_client_performance` y los opcionales `check_capture_coverage` y `export_weekly_performance_snapshot`. | Una etapa por subflow, con nombres del dominio. |
| D24 | La transformación se divide en un task por KPI: `compute_inbound_volume`, `compute_outbound_throughput`, `compute_stockout_frequency` y `compute_discrepancy_rate` (que también une las filas), más `prepare_kpi_events` y `validate_weekly_kpis`. | La rúbrica pide tests de ≥ 3 tasks que calculan los KPIs del BRIEFING. |
| D25 | La caché de 1 h pasa a `prepare_kpi_events` (misma clave: huella + exclusiones + versión). | Es el paso costoso (deduplicación sobre todos los eventos); los KPIs son agregaciones baratas. |
| D26 | `weekly_kpis.ensure_raw_events` valida la entrada (`TypeError` / `RawEventsSchemaError`) y un `timestamp` ilegible o un `event_type` ajeno se rechazan con motivo. | Comportamiento defensivo explícito y testeable. |
| D27 | Subflows con DataFrames: `validate_parameters=False`. | Pydantic no valida DataFrames; la forma ya la comprueba D26. |
| D28 | El flow principal llama a todos los subflows con `return_state=True` y mantiene `_required()`: mismo registro de fallos en `pipeline_runs`. Checkpoints `extract` y `validate`. | Mantener la resiliencia de la Parte 2 con la nueva topología. |
| D29 | Dashboard en `/reporting` (enlace "Reporte semanal"), con la misma sesión que inventario (`reporting/layout.tsx` reutiliza el layout de inventario). | Sin duplicar el guard de sesión. |
| D30 | Tarjeta de total + tabla con barra por almacén × cliente para cada KPI; periodo "Semana del … al …" y navegación por semanas. Nombres de cliente desde `GET /inventory/products`. | "Un gráfico o una tabla por KPI", legible por el CEO sin traducir `ecowear_usa`. |
| D31 | Actividad adicional: no se añaden mejoras nuevas; §17 del diseño documenta las de la Parte 2 y por qué el `Idempotency-Key` queda fuera. | El enunciado pide no inventar mejoras. |

## 3. Hallazgos

| # | Hallazgo |
|---|---|
| H11 | No hay ESLint ni librería de gráficos en el backoffice; Tailwind 4 y Next 16.4. |
| H12 | `fetchWithAuth` ya registra telemetría técnica de las llamadas: el dashboard genera `api_latency_recorded` para `/reporting/...` sin cambios. |
| H13 | El contrato de rutas sigue en 36 (no hay endpoints nuevos). |

## 4. Fases

### Fase 0 — Plan
| # | Acción | Commit |
|---|---|---|
| 0.1 | Plan y prompt. | `docs: añadir plan por fases y prompt de los subflows, tests y dashboard del pipeline` |
| 0.2 | Fila en `prompts/README.md`. | `docs: registrar el proyecto de subflows y dashboard en el índice de prompts` |

### Fase 1 — Subflows
| # | Acción | Commit |
|---|---|---|
| 1.1 | `weekly_kpis.py`: un cálculo por KPI y validación de entrada. | `refactor: separar los KPIs del BRIEFING en funciones de transformación` |
| 1.2 | `pipeline.py` con 5 subflows y tasks por KPI (CLI intacto). | `feat: refactor business performance pipeline into subflows, add unit tests, and add reporting dashboard` |
| 1.3 | `tests/test_pipeline_flow.py` a la nueva topología + subflows ejecutados por separado. | `test: adaptar los tests del flow a los subflows` |

### Fase 2 — Tests unitarios
| # | Acción | Commit |
|---|---|---|
| 2.1 | `tests/pipelines/test_pipeline.py` (13 tests). | `test: añadir los tests unitarios de los tasks de KPI` |

### Fase 3 — CLI
**Marisin:** `python -m pytest -q`; `python data/pipelines/pipeline.py --week-start 2026-11-16`; `python data/pipelines/pipeline.py`.

### Fase 4 — Dashboard
| # | Acción | Commit |
|---|---|---|
| 4.1 | `src/lib/reporting.ts`. | `feat: añadir el cliente del reporte semanal en el backoffice` |
| 4.2 | `src/app/reporting/page.tsx` y `layout.tsx`. | `feat: añadir el dashboard del reporte semanal en /reporting` |
| 4.3 | Enlace en `BackofficeNav.tsx`. | `feat: añadir el reporte semanal al menú del backoffice` |

**Marisin:** `npm run typecheck`, `npm run dev` y revisión en el navegador (captura), `npm run build`.

### Fase 5 — Documentación y cierre
| # | Acción | Commit |
|---|---|---|
| 5.1 | `PIPELINE_DESIGN.md`: §9.1, §9.5, diagrama, §13.3, §16 y §17. | `docs: documentar los subflows, los tests y el dashboard del pipeline` |
| 5.2 | `progress.md`. | `docs: actualizar progress.md con los subflows y el dashboard del pipeline` |
| 5.3 | **Marisin:** evidencias (pytest, CLI, dashboard). | `docs: añadir la verificación de los subflows y el dashboard` |

## 5. Checklist final

- [ ] `pipeline.py`: flow principal + 5 subflows (3 críticos y 2 opcionales con `return_state=True`).
- [ ] `python -m pytest tests/pipelines/test_pipeline.py` en verde (13 tests: 4 KPIs, a mano, defensivos).
- [ ] `python -m pytest -q` en verde.
- [ ] `python data/pipelines/pipeline.py` sin errores.
- [ ] `/reporting` muestra los 4 KPIs con su nombre del BRIEFING y el periodo, con datos reales.
- [ ] `telemetry_events`, `analysis.py`, `GET /telemetry/report` y `services/reporting/` intactos.
- [ ] PR que menciona la actividad adicional (no se añadieron mejoras nuevas; §17).
