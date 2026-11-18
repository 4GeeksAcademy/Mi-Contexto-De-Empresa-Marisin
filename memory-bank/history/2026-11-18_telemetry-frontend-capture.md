# Plan por fases — Telemetría 2/3: Captura en el frontend (TrackFlow)

> **Proyecto 4Geeks:** "Telemetría de tu compañía – Captura en el frontend" (2 de 3). El de *Almacenamiento* (3/3) va aparte y **no** se planifica aquí.
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-18_telemetry-frontend-capture.md`. Prompt en `prompts/telemetry-frontend-capture/prompt.md`.
> **Rama:** `feature/telemetry-frontend-capture`, creada por Marisin **desde `feature/telemetry-design-plan`** (el PR 1 está pendiente de aprobación).
> **Contrato aprobado:** `docs/telemetry/telemetry-plan.md` y `docs/telemetry/event-schemas.json`. Los `event_type`, las claves de `properties`, los enums y los puntos de captura de §12 salen **de ahí**, no de este plan ni del README de 4Geeks.
> **PR:** título exacto `feat: telemetry event capture`.

---

## 0. Reglas de ejecución para el agente

1. **Una fase cada vez.** Al terminar una fase, el agente se detiene, entrega el resumen de la §11 y no sigue hasta recibir `OK fase N, continúa`.
2. **Un commit por acción**, con prefijo convencional y descripción en español (`feat:`, `test:`, `docs:`, `fix:`, `chore:`).
3. **Git solo en local:** prohibido `git pull`, `git fetch`, `git merge`, `git rebase`, `git push`, cambiar de rama y abrir el PR.
4. Prohibido `git add .` y `git add -A`: añadir rutas explícitas y ejecutar `git status` a solas antes de cada commit. Si aparece el JSON local de TinyDB de proveedores, parar y avisar; nunca escribir su ruta en comandos.
5. **Ficheros autorizados.** Solo se pueden crear o modificar los de la §3. Nada de `infra/`, `.env` reales, credenciales, manifiestos (`package.json`, `package-lock.json`, `pyproject.toml`, `uv.lock`) ni otros frontends (`uis/website`, `uis/application`).
6. **No instalar dependencias.** Ni npm ni pip. Todo con lo que ya hay: Next.js, React, la Web Crypto API del navegador, FastAPI y Pydantic.
7. **Next.js 16 no es el que conoces** (lo avisa `uis/backoffice/AGENTS.md`). Antes de usar `error.tsx`, `useReportWebVitals`, variables `NEXT_PUBLIC_*` o `usePathname`, leer la guía correspondiente en `uis/backoffice/node_modules/next/dist/docs/` y citar en el resumen el fichero leído.
8. **Entorno Python, servidores y build:** pytest, uvicorn, `npm run dev` y `npm run build` los ejecuta **Marisin en su terminal**. El agente prepara los comandos exactos, para y espera la salida. Sí puede ejecutar `npm run typecheck` en `uis/backoffice`.
9. **Cero PII:** ningún evento lleva email, nombre, contraseña, token, `tracking_number`, IP, user agent ni texto libre del usuario. Ante la duda, no se emite.
10. Si algo del código real contradice este plan, **no inventar**: parar y avisar en el resumen.

---

## 1. Lo que exige la rúbrica (resumen)

- **Stub** `POST /telemetry/events`, en su propio router, que acepta `{ "events": [...] }`, registra en el log el número de eventos y el `event_type` de cada uno, y responde `200 { "received": N }`.
- **Modelo Pydantic `TelemetryEvent`** con el envelope completo. Se reutilizará **sin cambios** en el proyecto 3, así que hay que definirlo bien ahora.
- El backend declara **`TELEMETRY_ENDPOINT`** en su configuración de entorno.
- El frontend lee **`NEXT_PUBLIC_TELEMETRY_ENDPOINT`**, sin URL hardcodeada.
- **`TelemetryService`** con cola local, envío por lotes (cada 10 s o al llegar a 20 eventos), flush con `sendBeacon` en `visibilitychange` y 3 reintentos con backoff exponencial.
- El servicio genera automáticamente `eventId`, `sessionId`, `userId`, `timestamp`, `schemaVersion` y `requestId`. Única función pública: `track(eventType, properties)`.
- Ninguna llamada `fetch` de telemetría fuera del servicio.
- **Las 5 métricas obligatorias, instrumentadas.**
- **Piso técnico:** errores no capturados, al menos una métrica de rendimiento y `page_viewed` en las secciones principales.
- Resto del catálogo, respetando los allowlists. Cero PII. Evidencia en DevTools: lotes con respuesta 200.
- **Actividad adicional:** Web Vitals y eventos de autenticación capturados en el hook o componente de auth.

---

## 2. Decisiones de implementación ya tomadas (D23–D29)

Se documentan en `telemetry-plan.md` (acción 1.5) para que el contrato y el código digan lo mismo.

| # | Decisión | Por qué |
|---|---|---|
| D23 | **`NEXT_PUBLIC_TELEMETRY_ENDPOINT=/api/backend/telemetry/events`** (ruta relativa por el proxy `rewrites` que ya existe en `next.config.ts`), en lugar del `http://localhost:8000/telemetry/events` que sugiere el README. | En Codespaces el navegador corre en el ordenador de Marisin y **no llega** a `localhost:8000`. Además, `sendBeacon` hacia otro origen con `application/json` lo bloquea CORS. Por el proxy es mismo origen: sin CORS y funciona igual en local y en Codespaces. Sigue siendo variable de entorno, así que se cumple la rúbrica. |
| D24 | **`userId` = el `sub` del JWT**, decodificado en el cliente (solo se lee el payload, sin verificar la firma) desde el token que ya guarda `login()`. `null` si no hay token. | Resuelve el requisito de identidad de §12. `create_access_token(user["id"])` firma `sub = str(user.id)`, y `_user_uuid` usa ese mismo id porque los usuarios de TinyDB no tienen campo `uuid`. Es exactamente el identificador de inventario, sin tocar el backend y sin usar el email. |
| D25 | **`sessionId`** en `sessionStorage` (clave `tf_telemetry_session`): UUID creado al cargar la app si no existe y rotado en `user_login_succeeded`. | Es la "memoria de sesión" que pide la rúbrica: sobrevive a recargas de la pestaña y no pasa a otras pestañas. |
| D26 | **`requestId`:** `fetchWithAuth` genera un UUID por llamada y lo envía como `X-Request-ID`. Los eventos que nacen de esa llamada se emiten dentro de `withRequestId(id, () => track(...))`, un helper **síncrono** que fija el `requestId` solo durante esa llamada. `ApiError` lleva su `requestId` para que los `catch` de las páginas correlacionen también. Cualquier otro evento recibe un UUID nuevo. | Cumple "una única función pública `track()`" y "los componentes no pasan campos del envelope", y aun así correlaciona con la API. Es seguro porque JS es monohilo y no hay `await` entre fijar y limpiar el contexto. |
| D27 | **El stub es público (sin JWT)** y se limita a 50 eventos por lote (el `max_length=50` del modelo devuelve `422` si hay más). Valida con Pydantic, en el stub, `TelemetryBatch(events: list[TelemetryEvent])`. | `sendBeacon` no puede enviar la cabecera `Authorization`. El límite evita lotes abusivos. La validación parcial por evento (`model_validate` en bucle) llega en el proyecto 3: aquí solo se verifica el formato. |
| D28 | **`direct_stock_edit_rejected`:** nuevo endpoint `PATCH /inventory/products/{product_id}/stock` que **siempre responde `405`** (`detail`: "El stock solo se modifica con órdenes de entrada o salida."), con JWT obligatorio. En `inventory/products/page.tsx`, un control "Ajustar stock" por fila (almacén + cantidad) lo llama; ante el 405 emite el evento y muestra enlaces a entrada y salida. | La métrica es obligatoria y hoy no existe ni UI ni endpoint. El endpoint hace **explícita** la regla de negocio en lugar de dejarla implícita, y el control canaliza y educa un intento que hoy se hace por fuera del sistema. `rejection_reason: http_405` ya está en el enum, así que el esquema no cambia. |
| D29 | **`inventory_discrepancy_detected`:** nueva página `/inventory/counts` ("Conteo físico") con SKU, almacén y cantidad contada. Compara con el stock del sistema calculado desde `getOrders()` y, si la diferencia no es 0, emite el evento con `detection_source: physical_count`. **No persiste nada** en la BD. | Métrica obligatoria sin punto de captura. El conteo en sí es el hecho que se registra, en telemetría. Persistir conteos sería un modelo de negocio nuevo, fuera de alcance. |

---

## 3. Ficheros autorizados

**Backend (`services/`, `tests/`)**
- Nuevos: `services/api/telemetry_schemas.py` (modelos `TelemetryEvent` y `TelemetryBatch`), `services/api/routes/telemetry.py` (router del stub) y `tests/test_telemetry_stub.py`.
- Modificar: `services/api/main.py` (solo `include_router`), `services/api/routes/inventory.py` (solo el endpoint 405 de D28) y `.env.example` (solo `TELEMETRY_ENDPOINT`).

**Frontend (`uis/backoffice/`)**
- Nuevos: `src/lib/telemetry.ts` (el servicio), `src/lib/telemetry-mappers.ts` (normalizadores y sanitizadores), `src/components/TelemetryProvider.tsx`, `src/app/error.tsx`, `src/app/inventory/counts/page.tsx` y `.env.example`.
- Modificar: `src/lib/api.ts`, `src/lib/inventory.ts` (helper `computeStockIndex` y las llamadas de D28/D29), `src/app/layout.tsx`, `src/app/login/page.tsx`, `src/components/BackofficeNav.tsx` (logout y enlace a Conteo), `src/app/inventory/layout.tsx`, `src/app/inventory/products/page.tsx`, `src/app/inventory/orders/inbound/page.tsx` y `src/app/inventory/orders/outbound/page.tsx`.
- `uis/backoffice/.env.local` lo crea **Marisin** (está en `.gitignore`). El agente solo le da el contenido.

**Docs:** `docs/telemetry/telemetry-plan.md` (D23–D29 y estado de §12), `docs/telemetry/capture-verification.md` (nuevo), `memory-bank/progress.md`, `prompts/README.md` (fila del proyecto) y `prompts/telemetry-frontend-capture/`.

---

## 4. Fase 0 — Reconocimiento y línea base

| # | Acción | Commit |
|---|---|---|
| 0.1 | Commitear este plan y el prompt. | `docs: añadir plan por fases y prompt de la captura de telemetría` |
| 0.2 | Añadir la fila del proyecto en `prompts/README.md`. | `docs: registrar el proyecto de captura de telemetría en el índice de prompts` |
| 0.3 | Leer `AGENTS.md`, `uis/backoffice/AGENTS.md`, `memory-bank/projectbrief.md`, `techContext.md`, `progress.md` y `docs/telemetry/telemetry-plan.md` **entero** (en especial §4, §6, §8, §9, §12 y D1–D22). | — |
| 0.4 | Verificar en el código que se cumplen los supuestos de D23–D29: el rewrite `/api/backend` en `next.config.ts`; que `sub` del JWT = id del usuario (`security.py`); que no hay campo `uuid` en usuarios; los `handleSubmit` de inbound/outbound/login; el `stockIndex` de outbound; `handleLogout`; y que `createInboundOrder`/`createOutboundOrder` devuelven el `id`. | — |
| 0.5 | Leer en `uis/backoffice/node_modules/next/dist/docs/` las guías de: error boundaries (`error.tsx`), `useReportWebVitals`, variables `NEXT_PUBLIC_*` y `usePathname`. Anotar en el resumen las rutas leídas y cualquier diferencia con lo que da por hecho este plan. | — |
| 0.6 | Preparar para Marisin los comandos de línea base: `pytest -q` (esperado: 34 passed) y `cd uis/backoffice && npm run typecheck`. | — |
| 0.7 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 0 de captura` |

🛑 **STOP — auditoría de Fase 0** (con la salida de pytest y typecheck de Marisin).

---

## 5. Fase 1 — Stub en FastAPI y modelo `TelemetryEvent`

| # | Acción | Commit |
|---|---|---|
| 1.1 | `services/api/telemetry_schemas.py`. **`TelemetryEvent`** (`extra="forbid"`, `populate_by_name=True`, campos snake_case con alias camelCase del envelope): `event_id: UUID` (alias `eventId`); `timestamp: AwareDatetime`; `session_id: UUID` (`sessionId`); `user_id: str \| None` con `min_length=1` (`userId`); `event_type: str` con patrón `^[a-z]+(_[a-z]+)+$`; `schema_version: str` con patrón semver `^\d+\.\d+\.\d+$` (`schemaVersion`); `request_id: UUID` (`requestId`); `properties: dict[str, Any]`. **`TelemetryBatch`**: `events: list[TelemetryEvent]` con `max_length=50` (D27). Docstring que avise de que el modelo es el contrato que reutilizará el proyecto 3 sin cambios. | `feat: añadir el modelo Pydantic TelemetryEvent del envelope de telemetría` |
| 1.2 | `services/api/routes/telemetry.py`: `router = APIRouter(prefix="/telemetry", tags=["telemetry"])`; `TELEMETRY_ENDPOINT = os.getenv("TELEMETRY_ENDPOINT", "http://localhost:8000/telemetry/events")` a nivel de módulo, con un comentario que diga que solo establece el patrón; `POST /events` que recibe `TelemetryBatch`, hace **un** `logger.info` con el total y la lista de `event_type` (nunca `properties` ni `userId`) y devuelve `{"received": len(batch.events)}`. Sin JWT (D27). Logger propio configurado como `api.timing` en `main.py` (handler solo si no tiene, `propagate=False`). | `feat: añadir el endpoint stub POST /telemetry/events` |
| 1.3 | `main.py`: `app.include_router(telemetry_router)`. | `feat: registrar el router de telemetría en la API` |
| 1.4 | `.env.example`: añadir `TELEMETRY_ENDPOINT=http://localhost:8000/telemetry/events` con un comentario. | `chore: declarar TELEMETRY_ENDPOINT en .env.example` |
| 1.5 | `tests/test_telemetry_stub.py` con `TestClient`: (a) lote válido de 2 eventos → 200 `{"received": 2}`; (b) lote vacío → 200 `{"received": 0}`; (c) evento sin `eventId` → 422; (d) clave extra en el envelope → 422; (e) 51 eventos → 422 (límite del modelo); (f) el log contiene los `event_type` y **no** contiene el valor de una propiedad de prueba (`caplog`); (g) no exige `Authorization`. | `test: cubrir el stub de telemetría y el modelo TelemetryEvent` |
| 1.6 | Preparar para Marisin: `pytest -q tests/test_telemetry_stub.py` y `pytest -q` (esperado: 34 + los nuevos). Y una petición `curl` de ejemplo contra el stub arrancado. | — |
| 1.7 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 1 de captura` |
🛑 **STOP — auditoría de Fase 1.**

---

## 6. Fase 2 — `TelemetryService` en el frontend

| # | Acción | Commit |
|---|---|---|
| 2.1 | `uis/backoffice/.env.example` con `NEXT_PUBLIC_TELEMETRY_ENDPOINT=/api/backend/telemetry/events` y un comentario sobre D23. Dar a Marisin el contenido de su `.env.local`: la misma línea más `NEXT_PUBLIC_INVENTORY_API_URL=http://127.0.0.1:8000`. | `chore: declarar NEXT_PUBLIC_TELEMETRY_ENDPOINT en el backoffice` |
| 2.2 | `src/lib/telemetry-mappers.ts` (funciones puras, sin efectos): `toWarehouse` (`"Los Angeles"→los_angeles`, `"Zaragoza"→zaragoza`, otro → `null`); `toCountry`; `toProductCategory` (D15; `null` si no hay mapeo o si el SKU empieza por `LOAD-`); `toClientId` (slug D11); `toExitType` (D22); `toRouteTemplate(path)` (quita query y fragmento, y sustituye los segmentos numéricos o UUID por `[id]`); `sanitizeErrorMessage` (quita emails, `Bearer …`/JWT y secuencias de 6 o más dígitos; trunca a 200); `toStackFrames` (máx. 10, `archivo:línea` con el patrón de §6); `errorFingerprint` (SHA-256 con `crypto.subtle` → 16 hex de `nombre\nprimer frame`); y `inventoryProperties(product, warehouse, quantity)`, que devuelve las 6 propiedades comunes o `null` si alguna no se puede normalizar (**entonces no se emite**: §12). | `feat: añadir normalizadores y sanitizadores de telemetría` |
| 2.3 | `src/lib/telemetry.ts` — **núcleo**: constante `SCHEMA_VERSION = "1.0.0"`; cola en memoria; `track(eventType, properties): void`, que construye el envelope (`eventId` con `crypto.randomUUID()`, `timestamp` con `new Date().toISOString()`, `sessionId` según D25, `userId` según D24, `requestId` según D26) y encola. `track` **nunca lanza**: todo dentro de `try/catch` y no hace nada en el servidor (`typeof window === "undefined"`). | `feat: crear TelemetryService con cola local y envelope automático` |
| 2.4 | **Batch y debounce:** flush cada 10 s (un solo `setInterval`, creado de forma perezosa en el primer `track`) o en cuanto la cola llega a 20 eventos. El envío es un `fetch` POST con `{"events": [...]}`, `keepalive: true` y `Content-Type: application/json` a `process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT`. Si la variable no existe, `console.warn` una sola vez y se descarta (nunca una URL por defecto). Los lotes son de 20 como máximo. | `feat: enviar la telemetría en lotes cada 10 s o 20 eventos` |
| 2.5 | **Reintentos:** si falla la red o la respuesta no es 2xx, reintentar el **mismo lote** (mismos `eventId`, §10 del plan) hasta 3 veces con esperas de 1 s, 2 s y 4 s. Después se descarta en silencio (un `console.debug`). Mientras hay un lote en vuelo no se lanza otro. | `feat: reintentar los lotes de telemetría con backoff exponencial` |
| 2.6 | **Flush fiable:** en `visibilitychange` con `document.visibilityState === "hidden"` y en `pagehide`, enviar la cola pendiente (y el lote en vuelo, si lo hay) con `navigator.sendBeacon(endpoint, new Blob([json], { type: "application/json" }))`. Si `sendBeacon` devuelve `false`, se recurre a `fetch` con `keepalive`. Listeners registrados una sola vez. | `feat: vaciar la cola de telemetría con sendBeacon al ocultar la pestaña` |
| 2.7 | **Contexto e identidad:** `withRequestId(id, fn)` (D26), `rotateSession()` (D25) y `getUserIdFromToken()` (D24; decodifica en base64url el payload de `getAuthToken()` y devuelve `sub` como string, o `null`). **Exportados únicamente:** `track`, `withRequestId`, `rotateSession` y `SCHEMA_VERSION`. Ninguno de los tres helpers emite eventos. | `feat: añadir correlación por requestId e identidad opaca a la telemetría` |
| 2.8 | **Throttle de §8** dentro del servicio, antes de encolar, con ventanas móviles por `sessionId`: dedupe de `page_viewed` (<1 s por ruta), topes de `frontend_error_captured` (1 por `error_fingerprint` cada 60 s y 10 por minuto) y de `user_login_failed` (20 por minuto). El muestreo de `api_latency_recorded` se hace en `api.ts` (fase 3), porque necesita `status_code` y la duración. | `feat: aplicar los límites de frecuencia del plan antes de encolar` |
| 2.9 | Preparar para Marisin `npm run typecheck` (el agente puede ejecutarlo) y `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 2 de captura` |

**Criterio:** `grep -rn "telemetry/events\|NEXT_PUBLIC_TELEMETRY_ENDPOINT" uis/backoffice/src` solo debe aparecer en `telemetry.ts`.

🛑 **STOP — auditoría de Fase 2.**

---

## 7. Fase 3 — Piso técnico transversal

| # | Acción | Commit |
|---|---|---|
| 3.1 | `src/components/TelemetryProvider.tsx` (client component) montado en `app/layout.tsx` alrededor de `{children}`. Hace dos cosas: **`page_viewed`** con `usePathname()` → `toRouteTemplate`, en la carga inicial y en cada cambio (el dedupe ya lo aplica el servicio); y **errores globales**: `window.addEventListener("error")` y `"unhandledrejection"` → `frontend_error_captured` con `error_source` `window_error` o `unhandled_rejection`, mensaje sanitizado, `stack_frames` y `error_fingerprint`. Los listeners se limpian en el return del `useEffect`. | `feat: capturar vistas de página y errores globales del backoffice` |
| 3.2 | `src/app/error.tsx` (error boundary de Next 16 según la guía leída en 0.5) → `frontend_error_captured` con `error_source: error_boundary`, más una UI mínima con botón de reintentar. | `feat: capturar errores de render con el error boundary del backoffice` |
| 3.3 | `src/lib/api.ts` → `fetchWithAuth`: generar `requestId` y enviarlo como `X-Request-ID`; medir con `performance.now()`. Ante una **respuesta HTTP** → `api_latency_recorded` (`api_endpoint` como plantilla, `http_method`, `status_code`, `duration_ms` y `sample_rate`: 1 si `status ≥ 400` o `duration_ms > 1000`; si no, 0.2 y solo se emite con `Math.random() < 0.2`). **5xx** → `api_request_failed` (`http_5xx` + `status_code`). **Excepción de red** → `api_request_failed` (`network_error`, sin `status_code`) y se relanza el error. **401** en endpoint protegido → `session_expired` **antes** de limpiar el token. **403** → `route_access_denied` (`reason`: `inactive_user` si el `detail` es "Inactive user"; si no, `insufficient_permissions`; el `detail` nunca se envía). Todo dentro de `withRequestId`. `ApiError` gana el campo `requestId`. **La telemetría nunca pasa por `fetchWithAuth`**: el servicio usa su propio `fetch`, para no medirse a sí mismo. | `feat: instrumentar latencia, fallos y accesos en el cliente HTTP` |
| 3.4 | `src/app/inventory/layout.tsx`: al redirigir por falta de token → `route_access_denied` con `reason: no_session` y `route` igual a la plantilla actual, sin `api_endpoint`. | `feat: registrar los accesos a inventario sin sesión` |
| 3.5 | `npm run typecheck` y `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 3 de captura` |

🛑 **STOP — auditoría de Fase 3.**

---

## 8. Fase 4 — Negocio y autenticación

| # | Acción | Commit |
|---|---|---|
| 4.1 | `src/lib/inventory.ts`: extraer `computeStockIndex(orders)` (la misma lógica que el `useMemo` de outbound) y usarla en outbound **dentro del mismo `useMemo`**, sin perder la memoización del proyecto de caching. | `refactor: extraer el cálculo de stock por almacén a un helper compartido` |
| 4.2 | **Outbound** (`orders/outbound/page.tsx`): tras la respuesta 201 → `outbound_order_created` (`order_id` = `id` de la respuesta, `exit_type` con D22, **sin** `tracking_number`). Después, con los movimientos refrescados, comparar el stock antes y después del SKU en ese almacén → `stock_threshold_triggered` solo al cruzar de ≥ 50 a < 50 (`min_threshold: 50`, `threshold_source: global_default`, `trigger_order_id`). Validación local en `handleSubmit`, cuando `isStockExceeded` → `outbound_order_validation_failed` (`client`, `insufficient_stock`) antes del `return`. En el `catch` con `ApiError` 400/404/422 → `validation_source: api` con el mapeo de §12, y `quantity` solo si es entero. | `feat: instrumentar las órdenes de salida y el umbral de stock` |
| 4.3 | **Inbound** (`orders/inbound/page.tsx`): cargar también `getOrders()` y usar `computeStockIndex`. Tras la respuesta 201 → `inbound_order_created`, refrescar los movimientos y, al cruzar de < 50 a ≥ 50, `stock_threshold_cleared`. En el `catch` → `inbound_order_validation_failed` (`api`). | `feat: instrumentar las órdenes de entrada y la reposición de stock` |
| 4.4 | **Formularios** (ambas páginas): `order_form_started` en el primer `onChange` o `onFocus` de un campo (un `ref` evita repetirlo); `order_form_abandoned` en el cleanup del `useEffect` (desmontaje) y al ocultar la pestaña, si hubo `started` y aún no hubo un submit correcto. Propiedades: `last_field_touched` con el enum de §6, `fields_completed` y `time_in_form_ms`. Tras un envío correcto, el estado se reinicia para la siguiente orden. | `feat: medir inicio y abandono de los formularios de órdenes` |
| 4.5 | **Login** (`app/login/page.tsx`): tras `login()` correcto → `rotateSession()`, guardar la hora de login en `sessionStorage` (`tf_telemetry_login_at`) y `user_login_succeeded` (propiedades vacías), **antes** de `router.replace`. En el `catch` → `user_login_failed` (el `userId` sale `null` solo, porque aún no hay token): `ApiError` 401 o 422 → `invalid_credentials`, 403 → `account_locked`, `TypeError` de red → `network_error`. **Nunca** el email. | `feat: instrumentar los inicios de sesión correctos y fallidos` |
| 4.6 | **Logout** (`BackofficeNav.tsx`, `handleLogout`): `user_logged_out` con `session_duration_ms` = ahora − `tf_telemetry_login_at`. El JWT no sirve para esto porque `create_access_token` no incluye `iat`, solo `sub` y `exp`. Si no hay hora de login guardada (sesión anterior a esta versión), no se emite. Todo antes de borrar el token. | `feat: instrumentar el cierre de sesión con su duración` |
| 4.7 | `npm run typecheck` y `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 4 de captura` |
🛑 **STOP — auditoría de Fase 4.**

---

## 9. Fase 5 — Las dos obligatorias que faltaban (D28 y D29)

| # | Acción | Commit |
|---|---|---|
| 5.1 | **Backend:** en `routes/inventory.py`, `PATCH /inventory/products/{product_id}/stock` con `get_current_user`: si el SKU no existe → 404; si existe → **siempre** `HTTPException(405, detail="El stock solo se modifica con órdenes de entrada o salida.")`. Sin tocar ningún modelo, caché ni lógica de stock. Test en `tests/test_telemetry_stub.py` o en uno nuevo `tests/test_direct_stock_edit.py`: con JWT → 405 y el stock sin cambios; sin JWT → 401. | `feat: rechazar explícitamente la edición directa de stock` |
| 5.2 | **Frontend:** en `inventory.ts`, `requestDirectStockEdit(productId, warehouse, quantity)`. En `products/page.tsx`, el control "Ajustar stock" por fila (almacén + cantidad + botón): ante el 405 → `direct_stock_edit_rejected` (`rejection_reason: http_405`, `quantity` = cantidad intentada, `attempted_delta` = cantidad − stock actual de ese almacén si se conoce), más un mensaje con enlaces a "Registrar entrada" y "Registrar salida". | `feat: instrumentar los intentos de edición directa de stock` |
| 5.3 | **Conteo físico:** `app/inventory/counts/page.tsx` con SKU, almacén y cantidad contada (entero ≥ 0). Calcula el stock del sistema con `getOrders()` + `computeStockIndex`. Muestra "Coincide" o "Discrepancia de N unidades" y, si N ≠ 0, emite `inventory_discrepancy_detected` (`system_quantity`, `counted_quantity`, `quantity` = contada − sistema, `detection_source: physical_count`). Enlace "Conteo físico" en `BackofficeNav`. | `feat: añadir el conteo físico e instrumentar las discrepancias de inventario` |
| 5.4 | `telemetry-plan.md`: añadir D23–D29 a la §2.2 y actualizar en §2.1, §3.1 y §12 las filas de `direct_stock_edit_rejected` e `inventory_discrepancy_detected` (de "pendiente" a "implementado", con su punto de captura real), además de `stock_threshold_cleared` (inbound ya calcula el stock). Revalidar `event-schemas.json`, que **no debe cambiar**. | `docs: reflejar en el plan de telemetría las decisiones de implementación` |
| 5.5 | Preparar para Marisin `pytest -q` y `npm run typecheck`, y actualizar `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 5 de captura` |

🛑 **STOP — auditoría de Fase 5.**

---

## 10. Fase 6 — Actividad adicional y verificación de extremo a extremo

| # | Acción | Commit |
|---|---|---|
| 6.1 | **Web Vitals:** `useReportWebVitals` (según la guía de 0.5) dentro de `TelemetryProvider` → `web_vital_recorded` solo para `LCP`, `INP` y `CLS`, con `route` en plantilla y `metric_value`. Se ignoran las demás métricas. | `feat: enviar Web Vitals como eventos de telemetría` |
| 6.2 | `docs/telemetry/capture-verification.md`: tabla con los 20 eventos (obligatorio o identificado, componente o hook que lo captura y cómo provocarlo a mano), los comandos para arrancar todo y un checklist de PII. Es la base de la descripción del PR. | `docs: añadir la guía de verificación de la captura de telemetría` |
| 6.3 | **Verificación (la hace Marisin):** arrancar la API (`python -m uvicorn services.api.main:app --port 8000`) y el backoffice (`cd uis/backoffice && npm run dev`, puerto 3001). Con DevTools → Network filtrado por `telemetry`: login fallido y luego correcto; navegar por productos, entrada, salida, historial y conteo; una entrada; una salida que cruce el umbral; una salida con más stock del disponible; un "Ajustar stock"; un conteo con diferencia; logout. Comprobar: lotes con `{"events": [...]}`, respuesta **200** `{"received": N}`, el log del stub con los `event_type`, y ningún email ni `tracking_number` en los payloads. **Captura de pantalla** del Network con un lote en 200 → `docs/telemetry/evidence/network-batch-200.png`. | `docs: añadir evidencia de lotes de telemetría recibidos por el stub` |
| 6.4 | **Build** (lo ejecuta Marisin): `cd uis/backoffice && npm run build`. Si aparece `SecurityFatalError`, repetirlo en menos de 5 minutos. | — |
| 6.5 | `progress.md` y redactar en el resumen (no en un fichero) la descripción del PR. | `docs: actualizar progress.md con el cierre de la captura de telemetría` |

🛑 **STOP final.** Marisin sube la rama y abre el PR `feat: telemetry event capture` cuando Claude dé el OK.

---

## 11. Plantilla de resumen al cerrar cada fase

```
## Resumen Fase N — <nombre>
**Commits realizados:** (hash corto + mensaje, en orden)
**Ficheros tocados:**
**Qué se hizo:** (3–6 viñetas)
**Guías de Next.js leídas (si aplica):**
**Decisiones tomadas por el agente que no estaban en el plan:**
**Discrepancias con el código real, el plan de telemetría o el BRIEFING:**
**Comandos que debe ejecutar Marisin:** (exactos, en orden)
**Checklist de rúbrica cubierto en esta fase:**
⏸ Esperando "OK fase N, continúa".
```

---

## 12. Checklist de la rúbrica (auditoría final)

- [ ] Existe el stub `POST /telemetry/events` en su propio router; acepta `{events: [...]}` con `TelemetryEvent`, registra en el log el total y los `event_type`, y devuelve `{received: N}`.
- [ ] `TelemetryEvent` refleja el envelope completo (8 campos) y está listo para reutilizarse sin cambios.
- [ ] El frontend lee `NEXT_PUBLIC_TELEMETRY_ENDPOINT`, sin URL hardcodeada, y el backend declara `TELEMETRY_ENDPOINT`.
- [ ] Cola local, lotes de 10 s / 20 eventos, `sendBeacon` en `visibilitychange` y 3 reintentos con backoff.
- [ ] `eventId`, `sessionId`, `userId`, `timestamp`, `schemaVersion` y `requestId` los genera el servicio, no los componentes.
- [ ] Única función pública de emisión: `track()`. Ningún `fetch` de telemetría fuera del servicio.
- [ ] Las 5 obligatorias están instrumentadas, incluidas D28 y D29.
- [ ] Piso técnico: errores (`window`, `unhandledrejection` y boundary), rendimiento (`api_latency_recorded` y Web Vitals) y `page_viewed`.
- [ ] Los `event_type` y las claves salen de `event-schemas.json`, sin propiedades extra.
- [ ] Cero PII: ni email, ni nombre, ni contraseña, ni token, ni `tracking_number`.
- [ ] Captura de DevTools con un lote en 200.
- [ ] Actividad adicional: Web Vitals y autenticación en el login y el logout (nunca en cada página).
- [ ] `pytest` en verde, `typecheck` y `build` OK.
- [ ] PR `feat: telemetry event capture` con la lista de eventos (obligatorio o identificado, y qué componente o hook lo captura), la captura de pantalla y la actividad adicional.
