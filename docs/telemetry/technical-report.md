# Reporte técnico de telemetría

`GET /telemetry/report` es un radar operacional para el equipo de ingeniería: cuánto se usa el sistema, cuántos errores produce, qué tan rápido responde la API y si el acceso funciona. **No es un reporte de negocio**: no mide órdenes, inventario, clientes ni ventas; ese análisis queda para el Hito de Data Pipelines.

- Pipeline: `services/telemetry/analysis.py`
- Endpoint y caché: `services/api/routes/telemetry.py`, `services/api/telemetry_report.py`, `services/api/cache.py`
- Decisiones: D43–D53 en `memory-bank/history/2026-11-19_telemetry-report.md`

## Cómo se calcula

Cada métrica sigue el mismo orden:

```
cargar (SQL) → refinar (Pandas) → convertir tipos → agrupar → agregar → servir
```

1. **Cargar:** una consulta por métrica con la ventana `"timestamp" >= :start_date and "timestamp" < :end_date` y, si hace falta, `event_type in (...)`. Solo se leen las columnas que usa la métrica; nunca la tabla entera.
2. **Refinar:** las dimensiones de `tags` se extraen con `pd.json_normalize` y se descartan las filas con la dimensión nula. Los indicadores derivados (`is_error`, `is_warning`, `is_failure`, el peso del muestreo) se construyen como columnas.
3. **Convertir tipos:** `pd.to_datetime(timestamp, utc=True, format="ISO8601")` y la fecha UTC del evento, siempre antes de agrupar.
4. **Agrupar y agregar:** `groupby(...).agg(...)` con `count`, `sum`, `mean`, `max`. Sin bucles.
5. **Servir:** `reset_index().to_dict(orient="records")`, con las fechas como texto ISO.

## Métricas

| Clave | Pregunta operacional | Agrupación | Campos |
|---|---|---|---|
| `events_per_day` | ¿Qué eventos ocurren cada día y con qué frecuencia? ¿Hay picos o caídas de actividad? | día × `event_type` | `date`, `event_type`, `events` |
| `error_rate_per_day` | ¿Qué parte del tráfico de cada día son errores (`level = error`) o avisos (`level = warn`)? | día | `date`, `total_events`, `error_events`, `warning_events`, `error_rate`, `warning_rate` |
| `api_latency_per_day` | ¿Qué endpoints responden más lento cada día? | día × `api_endpoint` × `http_method` | `date`, `api_endpoint`, `http_method`, `observations`, `estimated_requests`, `avg_ms`, `p95_ms`, `max_ms` |
| `auth_failure_rate` | ¿Qué proporción de los intentos de login falla cada día? Un aumento brusco apunta a problemas de credenciales o a intentos de fuerza bruta. | día | `date`, `login_attempts`, `login_failures`, `failure_rate` |

**La latencia está muestreada.** Según §8 del plan de telemetría, `api_latency_recorded` incluye el 100 % de las respuestas lentas (más de 1 s) o con error y el 20 % del resto. Cada observación pesa `1 / sample_rate`: `observations` es lo que llegó, `estimated_requests` es el tráfico estimado, y `avg_ms` y `p95_ms` son la media y el percentil 95 ponderados. Sin ponderar saldrían sesgados hacia las respuestas lentas.

**La tasa de error es por día y no por tipo de evento** porque en este catálogo el `level` es fijo para cada tipo (§6): una tasa por tipo daría siempre 0 o 1.

## Periodo y caché

- `start_date` y `end_date` son opcionales, en ISO 8601 (`2026-11-12` o `2026-11-12T08:00:00Z`). Sin zona horaria se toman como UTC.
- Sin parámetros: los últimos 7 días hasta ahora, con `now` truncado al minuto para que peticiones seguidas compartan la caché.
- `start_date >= end_date` o una ventana de más de 92 días → `422`.
- El resultado se guarda **60 s** por ventana. Dentro de ese tiempo, la misma ventana no vuelve a ejecutar el pipeline: el log de la API escribe `Telemetry report computed ...` solo cuando calcula.
- Requiere sesión (`Authorization: Bearer <token>`); sin token → `401`. Si Supabase no responde → `503`.

## Cómo consultarlo

Con la API arrancada (`python -m uvicorn services.api.main:app --reload --port 8000`):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "<tu-email>", "password": "<tu-contraseña>"}' | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8000/telemetry/report -H "Authorization: Bearer $TOKEN" | python -m json.tool
curl -s "http://localhost:8000/telemetry/report?start_date=2026-11-12&end_date=2026-11-20" -H "Authorization: Bearer $TOKEN"
```

Una muestra real de la respuesta está en `docs/telemetry/evidence/report-sample.json`.

## Verificación con datos reales (2026-11-19)

Con la API arrancada y un token de `/auth/login`, `GET /telemetry/report` sin parámetros devolvió `200` para la ventana `2026-11-12T07:30:00Z` – `2026-11-19T07:30:00Z` (muestra completa en `evidence/report-sample.json`):

- `events_per_day`: 8 tipos de evento el 19 de noviembre (23 `api_latency_recorded`, 13 `page_viewed`, 4 `web_vital_recorded`, 2 `inbound_order_created`…).
- `error_rate_per_day`: 46 eventos, 1 error y 1 aviso (`error_rate` y `warning_rate` de 0,0217).
- `api_latency_per_day`: `GET /inventory/orders` es el endpoint más lento (p95 de 1868 ms y unas 23 peticiones estimadas), seguido de `GET /inventory/products` (p95 de 654 ms) y `POST /auth/login` (98 ms).
- `auth_failure_rate`: 2 intentos de login, 1 fallido (`failure_rate` 0,5).

**Caché.** Dos peticiones seguidas sin parámetros: el log de la API escribió `Telemetry report computed` una sola vez. La primera tardó 843 ms (pipeline contra Supabase) y la segunda 2,1 ms (servida desde la caché).

**Autenticación.** Sin token o con un token inválido, el endpoint responde `401`.
