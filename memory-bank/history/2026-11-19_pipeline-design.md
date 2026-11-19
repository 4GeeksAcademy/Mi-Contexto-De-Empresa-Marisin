# Plan por fases — Data Pipeline 1/3: Diseño del Pipeline de Desempeño de Negocio (TrackFlow)

> **Proyecto 4Geeks:** "Hito — Diseño de un Pipeline de Desempeño de Negocio (Parte 1 de 3)".
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-19_pipeline-design.md`. Prompt en `prompts/pipeline-design/prompt.md`.
> **Rama:** `feature/pipeline-design`, creada por Marisin **desde `feature/telemetry-report`** (PR #19 y #20 pendientes de aprobación).
> **Ejecución:** Claude redacta el documento y lo entrega como parches (`git am`). Marisin aplica, revisa en GitHub y hace push.
> **Entregable:** `data/pipelines/PIPELINE_DESIGN.md`. Sin código de orquestación.
> **Commit del entregable:** mensaje exacto del enunciado, `feat: add business performance pipeline design document` (única excepción a la regla de descripciones en español).

---

## 0. Reglas

1. Un commit por acción, prefijo convencional y descripción en español (salvo el commit del entregable, con el mensaje exacto del enunciado).
2. Git solo en local para quien implementa; Marisin crea la rama, aplica los parches y hace push.
3. Nada de `git add .` / `-A`; el JSON local de TinyDB de proveedores nunca se nombra ni se commitea; ningún `.env*` se lee ni se edita.
4. No se toca `services/telemetry/analysis.py`, `GET /telemetry/report` (`services/api/routes/telemetry.py`) ni `telemetry_events`. No hay cambios en `services/`, `uis/` ni dependencias.

---

## 1. Fuente de verdad: BRIEFING de data pipelines

`content/contexts/06-telemetry-data-pipelines/data-pipelines/trackflow-BRIEFING.es.md` del syllabus (no es `CONTEXT.md`; `CONTEXT.md` es el contexto general de la empresa).

- **Entregable:** "Reporte Semanal de Desempeño por Almacén y Cliente" para Thomas (CEO) y Ana (Operaciones), semanal, fresco el lunes por la mañana.
- **KPIs:** Volumen de entrada, Throughput de salida, Frecuencia de quiebre de stock, Tasa de discrepancia.
- **Eventos:** `inbound_order_created`, `outbound_order_created`, `stock_threshold_triggered`, `inventory_discrepancy_detected`. Ninguno más en la v1.
- **Grano:** `warehouse` (`los_angeles`/`zaragoza`) × `client_id` × `week_start` (lunes ISO, UTC).
- **Campos:** `inbound_units_count` (suma de cantidades), `outbound_orders_count`, `stockout_events_count`, `discrepancy_events_count`, `discrepancy_rate` (discrepancias / pedidos, 0 si no hay pedidos).
- **Destino:** `reporting.weekly_warehouse_client_performance` con `unique (warehouse, client_id, week_start)` para el upsert.
- **Endpoints en `services/reporting/`:** `GET /reporting/weekly-warehouse-client-performance`, `GET /reporting/pipeline-runs/latest`, `POST /reporting/pipeline-runs`.
- **Restricciones:** una fila = un cliente; `telemetry_events` solo lectura; el reporte técnico fuera de alcance.

## 2. Rúbrica (resumen)

`PIPELINE_DESIGN.md` en `data/pipelines/` con: estado actual + brecha; formato de extracción; propósito en una frase con entregable y KPIs del BRIEFING; sin tocar el reporte técnico ni escribir en `telemetry_events`; diagrama con ≥ 3 etapas y nombres reales; estrategia de actualización de registros; idempotencia explícita tras fallo en la carga; log con ≥ 5 campos (nombre, tipo, justificación); Prefect con ≥ 1 flow y ≥ 3 tasks; ≥ 3 endpoints en `services/reporting/` con la función de `data/pipelines/` que importa cada uno; coherencia con los eventos del BRIEFING de telemetría.

## 3. Hallazgos del código (confirmados por Claude)

| # | Hallazgo | Consecuencia en el diseño |
|---|---|---|
| H1 | `telemetry_events` es inmutable (triggers) y sin índice único en `eventId` (D40). | Deduplicar por `tags->>'eventId'` en la transformación. |
| H2 | No hay columna de hora de recepción; `timestamp` es la hora de captura. | Recalcular una ventana de 4 semanas en cada corrida (eventos tardíos). |
| H3 | Los 4 eventos ya se capturan (inbound/outbound, umbral 50 en salida, conteo físico en `/inventory/counts`). El `summary` de `telemetry_catalog.py` dice "pending" para la discrepancia, pero la captura existe desde la Fase 5 de captura. | Ningún cambio de captura necesario. |
| H4 | `warehouse` y `client_id` llegan ya normalizados (`telemetry-mappers.ts`); en la BD de dominio son "Los Angeles" y `client_name`. | Usar `tags`; normalizar solo en el control de cobertura. |
| H5 | 46 eventos reales: 2 inbound (uno de verificación, `curl_verification`/`nova_beauty`), 1 outbound, 0 umbral, 0 discrepancia. | Lista configurable `excluded_user_ids`. |
| H6 | El contenedor de la API monta solo `./services`; `prefect` no está en las dependencias. | Anotado para la Parte 2 (montaje de `./data`, dependencia). |
| H7 | `test_serialization_contracts.py` espera 33 rutas. | Parte 2: subirá a 36. |

## 4. Fases

### Fase 0 — Plan
| # | Acción | Commit |
|---|---|---|
| 0.1 | Plan y prompt. | `docs: añadir plan por fases y prompt del diseño del pipeline de negocio` |
| 0.2 | Fila en `prompts/README.md`. | `docs: registrar el proyecto de diseño del pipeline en el índice de prompts` |

### Fase 1 — Documento de diseño
| # | Acción | Commit |
|---|---|---|
| 1.1 | `data/pipelines/PIPELINE_DESIGN.md` (estado actual, propósito, extracción, Mermaid, tablas `reporting`, upsert, idempotencia, log, observabilidad, recuperabilidad, 10 preguntas, Prefect y endpoints). SQL validado en PostgreSQL 16 local (DDL idempotente; upsert repetido → `INSERT 0 0`); Mermaid validado con `mmdc`. | `feat: add business performance pipeline design document` |

### Fase 2 — Revisión y cierre (Marisin)
| # | Acción | Commit |
|---|---|---|
| 2.1 | Push y comprobar en GitHub que el Mermaid se ve. | — |
| 2.2 | `progress.md` y estado "PR abierto". | `docs: actualizar progress.md con el diseño del pipeline de negocio` |

`python -m pytest -q` no cambia (no hay código), pero conviene ejecutarlo como línea base: esperado **100 passed**.

## 5. Checklist final

- [ ] `data/pipelines/PIPELINE_DESIGN.md` existe y se lee bien en GitHub.
- [ ] Estado actual + brecha (§1).
- [ ] Extracción: tablas, forma del payload y cadencia (§3).
- [ ] Propósito en una frase con entregable, KPIs y métricas obligatorias (§2).
- [ ] Sin cambios en `analysis.py`, `GET /telemetry/report` ni `telemetry_events`; destino en `reporting` y `services/reporting/` (§5, §13).
- [ ] Mermaid con extracción, transformación y carga y nombres reales (§4).
- [ ] Actualización de registros con upsert por clave natural (§6).
- [ ] Idempotencia tras fallo en la carga (§7).
- [ ] Log con nombre, tipo y justificación (§8).
- [ ] Prefect: flow, 6 tasks, states, blocks (§9).
- [ ] 3 endpoints con su función de `data/pipelines/` (§13).
- [ ] Commit `feat: add business performance pipeline design document`.
