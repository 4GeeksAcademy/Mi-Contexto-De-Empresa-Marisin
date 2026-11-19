# Plan por fases — Telemetría 4: Reporte técnico (TrackFlow)

> **Proyecto 4Geeks:** "Telemetría de tu compañía – Reporte técnico".
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-19_telemetry-report.md`. Prompt en `prompts/telemetry-report/prompt.md`.
> **Rama:** `feature/telemetry-report`, creada por Marisin **desde `feature/telemetry-storage`** (PR #19 pendiente de aprobación).
> **Ejecución:** como en el almacenamiento, Claude implementa cada fase y la entrega como parche (`git am`). pytest, uvicorn, curl y Supabase los ejecuta Marisin.
> **PR:** título exacto `feat: telemetry report endpoint`.

---

## 0. Reglas

1. Un commit por acción, prefijo convencional y descripción en español.
2. Git solo en local para quien implementa; Marisin crea la rama, aplica los parches y hace push.
3. Nada de `git add .` / `-A`; el JSON local de TinyDB de proveedores nunca se nombra ni se commitea; ningún `.env*` se lee ni se edita.
4. Sin dependencias nuevas en el Codespace: `pandas` ya está en `pyproject.toml`. Solo se añade a `services/requirements.txt` (D53), que no lo tenía.
5. El frontend no se toca salvo en la actividad adicional del dashboard (Fase 4, opcional).

---

## 1. Rúbrica (resumen)

- `services/telemetry/analysis.py` con **al menos 3 funciones de métrica** independientes y sin efectos secundarios.
- Cada función: **cargar (SQL) → refinar (Pandas) → convertir tipos → agrupar → agregar**. Ventana `[start_date, end_date)` UTC y `event_type` filtrados **en SQL**; dimensiones de `tags` extraídas y limpiadas en Pandas; `pd.to_datetime(..., utc=True)` antes de cualquier `groupby`; sin bucles; salida `reset_index().to_dict(orient="records")`.
- `GET /telemetry/report` con `start_date`/`end_date` opcionales (ISO 8601, 7 días por defecto), ventana resuelta una vez y pasada a cada métrica, respuesta `{ "period": {...}, "metrics": {...} }`.
- **Caché en memoria con TTL de 60 s** por combinación de fechas.
- Métricas **técnicas/operacionales** con dimensión de agrupamiento; nada de negocio.
- Adicionales: `auth_failure_rate` (hecha) y dashboard en el backoffice (opcional).

---

## 2. Decisiones (D43–D53)

| # | Decisión | Por qué |
|---|---|---|
| D43 | Rama desde `feature/telemetry-storage`. | El reporte lee de `telemetry_events`, que llega con el PR #19. |
| D44 | **Cuatro métricas técnicas:** `events_per_day` (volumen por día y `event_type`), `error_rate_per_day` (proporción de eventos `level = error` y `warn` por día), `api_latency_per_day` (latencia por día, endpoint y método) y `auth_failure_rate` (fallos de login por día). | Cubren volumen, errores, rendimiento y acceso, las dimensiones que pide el tech lead. Ninguna mide inventario, ventas ni clientes. |
| D45 | La tasa de error es **por día**, no por `event_type`. | En este catálogo `level` es fijo por tipo (§6, `x-level`): una tasa "por tipo" daría siempre 0 o 1 y no diría nada. La pregunta útil es qué parte del tráfico de cada día es error o aviso. |
| D46 | La latencia **pondera por `1 / sample_rate`** (`estimated_requests`, `avg_ms` y `p95_ms`), con el p95 calculado como percentil ponderado vectorizado (orden + `cumsum` por grupo). | §8 del plan muestrea el 20 % de las respuestas normales y el 100 % de las lentas o con error: sin ponderar, la media y el p95 saldrían sesgados hacia lo lento. |
| D47 | `analysis.py` **no importa nada de `services/api`**: recibe el `engine` como parámetro. La ruta lo importa como `services.telemetry` o, en Docker, como `telemetry`. | En el contenedor `/app` es `services/` y el paquete raíz es `api`, así que una importación relativa entre paquetes rompería allí. |
| D48 | **Ventana por defecto truncada al minuto** (`end = ahora` sin segundos, `start = end − 7 d`). | Si no, cada petición sin parámetros tendría una clave distinta y la caché nunca acertaría. |
| D49 | Fechas sin zona horaria se interpretan como UTC; `start >= end` o más de **92 días** → 422. | Ventanas explícitas y acotadas: nunca se carga un rango arbitrario de la tabla. |
| D50 | **Caché propia** `telemetry_report_cache` (`TTLCache`, TTL 60 s, 32 entradas) en `services/api/cache.py`, respetando `TRACKFLOW_CACHE_ENABLED`. | Reutiliza la caché del proyecto de caching sin que las ventanas del reporte desalojen las entradas de inventario o incidencias. |
| D51 | El reporte **exige sesión** (`get_current_user`). | Son datos operativos internos del equipo de ingeniería. La ingesta sigue siendo pública porque la usa el `TelemetryService`. |
| D52 | Fallo de BD o `DATABASE_URL` ausente → 503; respuesta tipada con `TelemetryReport`. | Mismo criterio que la ingesta (D39) y `response_model` exigido por `test_serialization_contracts.py` (33 rutas). |
| D53 | `pandas` se añade a `services/requirements.txt`, sin fijar versión, igual que en `pyproject.toml`. | La imagen de Docker de la API instala desde ese fichero y no lo tenía: sin él, la API no arrancaría en el contenedor. |

---

## 3. Fases

### Fase 0 — Plan
| # | Acción | Commit |
|---|---|---|
| 0.1 | Plan y prompt. | `docs: añadir plan por fases y prompt del reporte técnico de telemetría` |
| 0.2 | Fila en `prompts/README.md`. | `docs: registrar el proyecto de reporte técnico en el índice de prompts` |

### Fase 1 — Pipeline de análisis
| # | Acción | Commit |
|---|---|---|
| 1.0 | `pandas` en `services/requirements.txt` (D53). | `chore: añadir pandas a las dependencias del contenedor de la API` |
| 1.1 | `services/telemetry/analysis.py` con las 4 métricas y `build_report_metrics`. | `feat: añadir el pipeline de análisis técnico de telemetría con Pandas` |
| 1.2 | `tests/test_telemetry_analysis.py`: corte de día UTC, tasas, latencia ponderada, `IN (...)` del login, misma ventana para todas, JSON serializable, idempotencia, ventana vacía y filtros en SQL. | `test: cubrir las métricas del pipeline de análisis técnico` |

### Fase 2 — Endpoint con caché
| # | Acción | Commit |
|---|---|---|
| 2.1 | `services/api/telemetry_report.py`: modelos de respuesta y `resolve_period`. | `feat: añadir el contrato y la ventana del reporte técnico de telemetría` |
| 2.2 | `telemetry_report_cache` en `cache.py`. | `feat: añadir la caché de 60 segundos del reporte técnico` |
| 2.3 | `GET /telemetry/report` en `routes/telemetry.py`. | `feat: añadir el endpoint GET /telemetry/report` |
| 2.4 | `tests/test_telemetry_report.py`: estructura, 7 días por defecto, ventana explícita, caché, expiración, 422, 401 y 503. | `test: cubrir el endpoint del reporte técnico y su caché` |
| 2.5 | Contrato de rutas: 32 → 33. | `test: actualizar el contrato de rutas con el endpoint del reporte` |

**Marisin:** `python -m pytest -q`.

### Fase 3 — Verificación con datos reales y cierre
| # | Acción | Commit |
|---|---|---|
| 3.1 | Guía `docs/telemetry/technical-report.md`: métricas, pregunta que responde cada una y cómo consultarlo. | `docs: documentar las métricas del reporte técnico de telemetría` |
| 3.2 | **Marisin:** API arrancada, token con `/auth/login`, `curl` a `/telemetry/report` → `docs/telemetry/evidence/report-sample.json`. Segunda llamada idéntica: en el log de la API solo aparece una vez `Telemetry report computed`. | `docs: añadir una muestra real del reporte técnico` |
| 3.3 | `progress.md` y estado "PR abierto". | `docs: actualizar progress.md con el cierre del reporte técnico` |

### Fase 4 — Dashboard (opcional)
Página `/telemetry` en el backoffice que consuma el reporte con `fetchWithAuth` y muestre el `period` y una tabla por métrica. Solo si queda tiempo.

---

## 4. Checklist final

- [ ] `services/telemetry/analysis.py` con 4 métricas independientes y sin bucles.
- [ ] Ventana y `event_type` en SQL; `tags` refinados en Pandas; `to_datetime(utc=True)` antes de agrupar.
- [ ] Cada métrica devuelve una lista de dicts serializable y agrupada (día y dimensión).
- [ ] `GET /telemetry/report` con 7 días por defecto, `{period, metrics}` y caché de 60 s.
- [ ] Métricas técnicas, ninguna de negocio.
- [ ] Muestra real del JSON en el PR, con la métrica de autenticación.
