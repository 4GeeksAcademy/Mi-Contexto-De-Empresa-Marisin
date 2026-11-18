# Verificación de la captura de telemetría (proyecto 2/3)

Guía para comprobar, de extremo a extremo, que el backoffice de TrackFlow captura los eventos del contrato (`docs/telemetry/event-schemas.json`) y los entrega en lotes al stub `POST /telemetry/events`.

## 1. Arranque

| Terminal | Comando (desde la raíz) | Puerto |
|---|---|---|
| API | `source .venv/bin/activate && python -m uvicorn services.api.main:app --port 8000` | 8000 |
| Backoffice | `cd uis/backoffice && npm run dev` | 3000 |

`uis/backoffice/.env.local` debe contener `NEXT_PUBLIC_TELEMETRY_ENDPOINT=/api/backend/telemetry/events` (D23: mismo origen a través del proxy `/api/backend` de `next.config.ts`). Las variables `NEXT_PUBLIC_*` se leen al arrancar `npm run dev`: si se cambian, hay que reiniciarlo.

En el navegador: DevTools → **Network**, filtro `telemetry` y casilla **Keep log** marcada (el login cambia de página).

## 2. Qué comprobar en cada lote

- Petición `events` a `/api/backend/telemetry/events` con estado **200** y respuesta `{"received": N}`. Tipo `fetch` en los envíos periódicos (cada 10 s o 20 eventos) y `ping` en los de `sendBeacon` (al ocultar o cerrar la pestaña).
- **Payload** → `{"events": [...]}` con el envelope completo: `eventId`, `timestamp` (ISO 8601 UTC con milisegundos), `sessionId`, `userId`, `event_type`, `schemaVersion`, `requestId` y `properties`.
- En la terminal de la API: `Received N telemetry events: [...]` con los `event_type`, sin propiedades ni identificadores de usuario.

## 3. Eventos y cómo provocarlos

| # | `event_type` | Origen | Componente o hook que lo captura | Cómo provocarlo |
|---|---|---|---|---|
| 1 | `inbound_order_created` | Obligatorio (BRIEFING) | `app/inventory/orders/inbound/page.tsx` (`handleSubmit`) | Registrar una entrada de un SKU no `LOAD-`. |
| 2 | `outbound_order_created` | Obligatorio (BRIEFING) | `app/inventory/orders/outbound/page.tsx` (`handleSubmit`) | Registrar una salida dentro del stock disponible. |
| 3 | `stock_threshold_triggered` | Obligatorio (BRIEFING) | `orders/outbound/page.tsx`, tras refrescar movimientos | Dejar un SKU en 50 en un almacén y sacar 1 unidad (50 → 49). |
| 4 | `direct_stock_edit_rejected` | Obligatorio (BRIEFING) | `app/inventory/products/page.tsx` (`handleDirectEdit`) | Productos → "Ajustar stock" → Guardar ajuste (la API responde 405). |
| 5 | `inventory_discrepancy_detected` | Obligatorio (BRIEFING) | `app/inventory/counts/page.tsx` (`handleSubmit`) | Conteo físico con una cantidad distinta del stock del sistema. |
| 6 | `inbound_order_validation_failed` | Identificado | `orders/inbound/page.tsx` (`catch`) | Respuesta 404/422 de la API al registrar una entrada. |
| 7 | `outbound_order_validation_failed` | Identificado | `orders/outbound/page.tsx` (validación local y `catch`) | Intentar enviar una salida mayor que el stock disponible. |
| 8 | `order_form_started` | Identificado | `components/TelemetryProvider.tsx` (`useOrderFormTelemetry`) | Primera interacción con un campo de un formulario de orden. |
| 9 | `order_form_abandoned` | Identificado | `useOrderFormTelemetry` (desmontaje y `visibilitychange`) | Empezar un formulario y navegar a otra sección sin enviarlo. |
| 10 | `stock_threshold_cleared` | Identificado | `orders/inbound/page.tsx`, tras refrescar movimientos | Entrada que lleva un SKU de menos de 50 a 50 o más. |
| 11 | `user_login_succeeded` | Identificado | `app/login/page.tsx` | Iniciar sesión con credenciales correctas. |
| 12 | `user_login_failed` | Identificado | `app/login/page.tsx` (`catch`) | Iniciar sesión con una contraseña incorrecta. |
| 13 | `session_expired` | Identificado | `lib/api.ts` (`fetchWithAuth`, 401) | Borrar o invalidar el token y llamar a una ruta protegida. |
| 14 | `user_logged_out` | Identificado | `components/BackofficeNav.tsx` (`handleLogout`) | Pulsar "Cerrar sesión". |
| 15 | `route_access_denied` | Identificado | `lib/api.ts` (403) y `app/inventory/layout.tsx` (sin token) | Abrir `/inventory/products` sin sesión. |
| 16 | `page_viewed` | Identificado | `components/TelemetryProvider.tsx` (`usePathname`) | Navegar entre secciones del backoffice. |
| 17 | `api_latency_recorded` | Identificado | `lib/api.ts` (`fetchWithAuth`) | Cualquier llamada a la API (100 % si es error o tarda más de 1 s; 20 % del resto). |
| 18 | `web_vital_recorded` | Identificado | `components/TelemetryProvider.tsx` (`useReportWebVitals`) | Cargar una página y ocultar la pestaña (LCP, INP y CLS). |
| 19 | `frontend_error_captured` | Identificado | `TelemetryProvider.tsx` (`error`, `unhandledrejection`) y `app/error.tsx` | Un error de JavaScript no capturado o un error de render. |
| 20 | `api_request_failed` | Identificado | `lib/api.ts` (`fetchWithAuth`, 5xx y red) | Parar la API y navegar por el backoffice. |

Los SKUs sintéticos `LOAD-` no emiten eventos de negocio (D15): es el comportamiento esperado.

## 4. Checklist de privacidad

- [ ] Ningún payload contiene email, nombre, contraseña ni token.
- [ ] `outbound_order_created` no lleva `tracking_number` ni datos del destinatario (D14).
- [ ] `user_login_failed` lleva `userId: null` y solo `failure_reason`.
- [ ] `route` y `api_endpoint` son plantillas sin query string (`/inventory/products/[id]`).
- [ ] `frontend_error_captured` usa el mensaje fijo por `error_source` (D30).
- [ ] El log del stub solo muestra el número de eventos y sus `event_type`.

## 5. Evidencias

- `evidence/network-batch-200.png`: DevTools → Network con lotes `events` en 200 y el Payload de un evento de negocio.
- Resultados verificados en navegador el 2026-11-18: las 5 métricas obligatorias (stock de `TF-BOTTLE-001` en Los Ángeles 27 → 50 → 49, ajuste directo rechazado con 405 y conteo con discrepancia de -4), además de `order_form_started`, `order_form_abandoned`, `outbound_order_validation_failed` (`validation_source: client`), `page_viewed`, `api_latency_recorded` y `sendBeacon` en 200.
