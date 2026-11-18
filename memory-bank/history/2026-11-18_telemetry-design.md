# Plan por fases — Telemetría 1/3: Diseño del Plan de Telemetría (TrackFlow)

> **Proyecto 4Geeks:** "Diseño del plan de telemetría de tu compañía" (1 de 3; los otros dos, *Captura en el frontend* y *Almacenamiento*, van aparte y **no** se planifican aquí).
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow). Contexto de empresa en `CONTEXT.md`.
> **Ubicación de este plan:** `memory-bank/history/2026-11-18_telemetry-design.md` (convención de `prompts/README.md`). Prompt de arranque en `prompts/telemetry-design/prompt.md`.
> **Rama de trabajo:** la crea Marisin antes de empezar, desde `main` actualizado (sugerencia: `feature/telemetry-design-plan`).
> **Entregables:** `docs/telemetry/telemetry-plan.md` y `docs/telemetry/event-schemas.json`.
> **PR:** título exacto `docs: telemetry design plan`.
> **Hoy NO se escribe código** en `services/` ni en `uis/`: solo documentación de diseño.

---

## 0. Reglas de ejecución para el agente

1. **Una fase cada vez.** Al terminar una fase, el agente **se detiene**, entrega el resumen con la plantilla de la sección 9 y **no empieza la siguiente** hasta recibir el mensaje explícito `OK fase N, continúa`.
2. **Un commit por acción**, aunque salgan muchos commits por fase. Formato: prefijo convencional + descripción en español (ej. `docs: añadir catálogo de eventos de autenticación al plan de telemetría`).
3. **Git solo en local:** prohibido `git pull`, `git fetch`, `git merge`, `git rebase`, `git push`, cambiar de rama y abrir el PR. La sincronización con GitHub la hace Marisin.
4. **No modificar** nada fuera de `docs/telemetry/`, `memory-bank/progress.md`, `prompts/README.md` (solo la fila de este proyecto) y `prompts/telemetry-design/`. Este plan solo se lee.
4b. Prohibido `git add .` y `git add -A`: añadir rutas explícitas y ejecutar `git status` a solas antes de cada commit. Si aparece el JSON local de TinyDB de proveedores (excluido por `.gitignore`), parar y avisar; nunca escribir su ruta en comandos.
5. Al cerrar cada fase, actualizar `memory-bank/progress.md` con una entrada breve y commitearla aparte (`docs: actualizar progress.md con el cierre de la fase N de telemetría`).
6. Si algo del código real contradice este plan (un endpoint que no existe, una lógica que no está implementada), **no inventar**: documentarlo como "pendiente de implementar" y señalarlo en el resumen de fase.
7. Los nombres de eventos, entidades y propiedades del BRIEFING (sección 1) se copian **exactamente**: mismas mayúsculas/minúsculas, mismos guiones bajos.

---

## 1. Fuente de verdad: BRIEFING de telemetría de TrackFlow

> Resumen fiel del `trackflow-BRIEFING.md` del syllabus (`content/contexts/06-telemetry-data-pipelines/telemetry`). Todo lo de esta sección es **innegociable**.

**Contexto:** TrackFlow hace almacenaje y última milla para marcas de moda, electrónica y cosmética entre Los Ángeles y Zaragoza. El inventario es el núcleo del negocio. La telemetría alimentará más adelante el dashboard de operaciones de **Ana** (Warehouse Ops) y el dashboard ejecutivo de **Thomas**, que compara volumen y SLA entre EE. UU. y España.

**Entidades:** `Product` (SKU de un cliente, con categoría), `InboundOrder` (recepción de mercancía de un cliente en un almacén), `OutboundOrder` (picking y despacho al transportista), `warehouse` (`los_angeles` | `zaragoza`), `client` (la marca dueña del SKU).

**Categorías de producto:** `fashion`, `electronics`, `cosmetics`.

**Métricas obligatorias (`event_type`):**

| event_type | Se dispara cuando | Decisión que habilita |
|---|---|---|
| `inbound_order_created` | Un almacén registra la recepción de mercancía de un cliente | Planificar capacidad y personal del almacén según volumen entrante (Ana) |
| `outbound_order_created` | Un almacén completa el picking y despacho de una orden | Detectar cuellos de botella operativos antes de que afecten al SLA de entrega (Ana) |
| `stock_threshold_triggered` | El stock de un SKU cae por debajo del mínimo configurado para ese cliente | Avisar al cliente y al equipo comercial antes de una rotura de stock (Miguel) |
| `direct_stock_edit_rejected` | Un usuario intenta modificar stock directamente (fuera de una orden) y el sistema lo rechaza | Reforzar formación o permisos en el almacén donde más ocurre |
| `inventory_discrepancy_detected` | Un conteo físico o auditoría detecta diferencia entre stock del sistema y stock real | Priorizar auditorías en los SKUs con mayor tasa de discrepancia (Ana) |

**Propiedades mínimas (además del envelope estándar):** `warehouse`, `client_id`, `product_id` (SKU), `product_category`, `quantity`.

**Privacidad:** prohibidos los datos del consumidor final. Los eventos de inventario **no** llevan datos de transportista ni de destinatario (eso pertenece al proyecto de última milla).

**Diseño:** las métricas deben poder agregarse por **almacén, cliente y país**, y estar documentadas para que otros dependan de ellas sin preguntar.

**Restricciones de negocio:** el stock solo cambia mediante `InboundOrder` u `OutboundOrder`, trazables a un usuario. Cada `product_id` pertenece a un único cliente; nunca se mezcla inventario entre clientes.

---

## 2. Decisiones de diseño ya tomadas (para que el agente no las reinvente)

| # | Decisión | Justificación |
|---|---|---|
| D1 | Añadir la propiedad derivada **`country`** (`US` \| `ES`, ISO 3166-1 alpha-2) a todos los eventos de inventario, derivada de `warehouse` (`los_angeles→US`, `zaragoza→ES`). | El BRIEFING exige agregación por país y no define códigos. Guardarlo explícito evita que cada consulta del dashboard de Thomas repita el mapeo. Es redundante a propósito: si mañana hay un segundo almacén en EE. UU., el dashboard no cambia. |
| D2 | `userId` = UUID interno del usuario autenticado (el mismo `user_uuid` que hoy guardan `StockEntry`/`StockExit`, procedente de TinyDB). **Nunca** email ni nombre. `null` solo en eventos previos a la autenticación (`user_login_failed`, `page_viewed` de `/login`). | Trazabilidad a usuario (restricción de negocio) sin PII directa. |
| D3 | `sessionId` siempre presente: se genera un UUID al cargar la app (sesión pre-auth) y **se rota** en el login correcto. | El envelope es consistente (nunca nulo) y no se pueden unir los intentos fallidos anónimos con la identidad posterior. |
| D4 | `requestId` = UUID. Si el evento nace de una llamada a la API, es el mismo valor que viaja en la cabecera `X-Request-ID` y queda en los logs del backend. Si es un evento puramente de UI, UUID nuevo por evento. | Correlación frontend–backend–logs. |
| D5 | `schemaVersion` en semver, empezando en `"1.0.0"`, constante compartida. Cambio de allowlist = minor; cambio de tipo o eliminación de clave = major. | Evolución de esquemas sin romper consumidores. |
| D6 | `timestamp` en ISO 8601 **UTC** con milisegundos (`2026-11-18T12:34:56.789Z`), momento de captura, no de envío. | Comparar LA y Zaragoza sin líos de zona horaria. |
| D7 | Verbos de la taxonomía en participio pasado y de un conjunto cerrado: `created`, `triggered`, `cleared`, `rejected`, `detected`, `failed`, `succeeded`, `expired`, `started`, `abandoned`, `viewed`, `recorded`, `captured`, `performed`, `denied`, `logged_out`. Regex: `^[a-z]+(_[a-z]+)+$`. | Consistencia de `entidad_acción`. |
| D8 | Cada `properties` se define con `additionalProperties: false` en el JSON Schema. | Así el allowlist se aplica en la propia validación del esquema y no depende de la disciplina de quien instrumente. |
| D9 | "Stream" y "batch" se refieren a **cómo se procesa y consume** el evento, no al transporte: el frontend siempre enviará en micro-lotes (≤10 s). Stream = debe disparar una alerta o aparecer en un panel en ≤1 min; batch = se agrega por ventanas (horaria/diaria). | Evita la confusión con el batching del `TelemetryService` del proyecto 2. |
| D10 | Para cada evento se documentan también `level` sugerido (`info`/`warn`/`error`) y qué propiedad alimentaría un campo numérico `value`. | Deja el contrato listo para el almacenamiento posterior sin tener que rediseñarlo. |
| D11 | `client_id` = slug estable del cliente (minúsculas, `_` en lugar de espacios; ej. `"Nova Beauty"→"nova_beauty"`), mientras no exista una entidad `Client` con id propio. | El modelo `SKU` solo tiene `client_name` (texto libre). El BRIEFING exige `client_id`. Se documenta como mapeo provisional y como discrepancia. |
| D12 | `product_id` = código `sku` (string, ej. `"TF-ELEC-001"`), **no** el `id` entero de la tabla `skus`. | El BRIEFING define `product_id` como SKU. El código de SKU es estable entre entornos; el id autoincremental no lo es. |
| D13 | Normalizar enums desde los valores reales de BD: `warehouse` `"Los Angeles"→los_angeles`, `"Zaragoza"→zaragoza`; `product_category` `"Fashion"/"Electronics"/"Cosmetics"→fashion/electronics/cosmetics`. | La telemetría usa el vocabulario del BRIEFING aunque la BD guarde otras mayúsculas. |
| D14 | `outbound_order_created` **excluye** `tracking_number` (aunque exista en `StockExit`) y no lleva nada del destinatario. Sí lleva `exit_type`. | El BRIEFING prohíbe datos de transportista y destinatario en eventos de inventario. `exit_type` (B2B/B2C) no es PII y explica el volumen. |

### 2.1 Hallazgos del código (revisado por Claude en `main` @ `6920262`, 18-nov-2026)

El agente debe **confirmarlos** en la Fase 0, no darlos por buenos sin mirar:

- **Una orden = un SKU.** `InboundOrderCreate`/`OutboundOrderCreate` llevan un único `sku_id`, `warehouse` y `quantity`. No hay líneas, así que un evento por orden.
- **Validaciones reales** en `services/api/routes/inventory.py`: `422` (Pydantic `extra="forbid"`, `strict=True`), `404` "SKU no encontrado", `400` "Stock insuficiente" en salidas. Esto define el enum `failure_reason` de `*_order_validation_failed`: `schema_invalid`, `sku_not_found`, `insufficient_stock`.
- **No existe** el mínimo de stock por cliente → `stock_threshold_triggered` y `stock_threshold_cleared` quedan con punto de captura "pendiente de implementar" (requiere añadir un mínimo configurable).
- **No existe** un endpoint de edición directa de stock (el stock se calcula en `_warehouse_balances`). Por tanto `direct_stock_edit_rejected` se captura cuando llega una petición `PUT`/`PATCH`/`POST` a rutas de stock o producto que intenta fijar stock y la API responde `404`/`405`/`422`. El agente propone el punto exacto. Hoy sería un evento de backend.
- **No existe** lógica de conteo físico o auditoría → `inventory_discrepancy_detected` queda "pendiente de implementar".
- **Frontend:** todas las llamadas pasan por `fetchWithAuth` en `uis/backoffice/src/lib/api.ts`. Es el punto único para `requestId` (cabecera `X-Request-ID`), `api_latency_recorded`, `api_request_failed` y `session_expired` (la rama `401` que redirige a `/login`). El token vive en `localStorage`.
- **Páginas del backoffice:** `/login`, `/`, `/inventory/products`, `/inventory/orders`, `/inventory/orders/inbound`, `/inventory/orders/outbound`. Navegación en `components/BackofficeNav.tsx`. Datos en `hooks/useInventoryData.ts`.
- **Backend:** hay un middleware de timing por petición (del proyecto de caching) en `services/api/main.py`. Sirve de referencia para latencia del lado servidor.

---

## 3. Catálogo objetivo de eventos

> El agente lo valida contra el código real en la Fase 0 y lo vuelca en `telemetry-plan.md` en la Fase 1. Puede **añadir** eventos si encuentra secciones del backoffice no previstas; no puede quitar los obligatorios.

### 3.1 Obligatorios (BRIEFING) — esquema completo

| event_type | Categoría | Propiedades clave además de las mínimas | Entrega |
|---|---|---|---|
| `inbound_order_created` | Negocio/inventario | `order_id`, `country` | Batch (horario) |
| `outbound_order_created` | Negocio/inventario | `order_id`, `exit_type`, `country` | **Stream** |
| `stock_threshold_triggered` | Negocio/inventario | `min_threshold`, `trigger_order_id`, `country` | **Stream** |
| `direct_stock_edit_rejected` | Negocio/seguridad | `rejection_reason`, `attempted_delta`, `country` | Batch (diario) |
| `inventory_discrepancy_detected` | Negocio/inventario | `system_quantity`, `counted_quantity`, `detection_source`, `country` | Batch (diario) |

**Semántica obligatoria de `quantity`** (debe quedar escrita en el plan, una por evento):
- `inbound_order_created` / `outbound_order_created`: unidades de la orden (cada orden es de un único SKU, ver §2.1). Si en el futuro hubiera órdenes con varias líneas, se emitiría un evento por línea con el mismo `order_id`.
- `stock_threshold_triggered`: stock resultante tras la orden que lo provocó.
- `direct_stock_edit_rejected`: cantidad que se intentó fijar (o el delta en `attempted_delta`).
- `inventory_discrepancy_detected`: `counted_quantity - system_quantity` (con signo).

### 3.2 Oportunidades identificadas — esquema completo (mínimo exigido: 8; aquí 16, en 6 categorías)

| event_type | Categoría | Hipótesis → decisión (resumen) | Entrega |
|---|---|---|---|
| `inbound_order_validation_failed` | Negocio/calidad de datos | Qué SKUs/clientes acumulan más errores de validación → corregir maestros de producto o formar al cliente | Batch (diario) |
| `outbound_order_validation_failed` | Negocio/calidad de datos | Ídem en salida, incluye `insufficient_stock` → detectar SKUs que se intentan despachar sin stock | Batch (diario) |
| `order_form_started` | UX/flujos | Base para medir abandono de formularios de orden | Batch (diario) |
| `order_form_abandoned` | UX/flujos | En qué paso se abandonan las órdenes → simplificar ese paso del formulario | Batch (diario) |
| `stock_threshold_cleared` | Negocio/inventario | Cuánto tarda un SKU en reponerse tras la alerta → SLA de reposición con cada cliente | **Stream** (cierra la alerta) |
| `inventory_search_performed` | Navegación/UX | Búsquedas sin resultados → mejorar buscador o maestros de SKU | Batch (diario) |
| `user_login_succeeded` | Autenticación | Adopción real del backoffice por almacén → formación donde no se usa | Batch (diario) |
| `user_login_failed` | Autenticación/seguridad | Picos de fallos → posible fuerza bruta o problema de credenciales | **Stream** |
| `session_expired` | Autenticación | Si las sesiones caducan a mitad de una orden → ajustar TTL de sesión | Batch (diario) |
| `user_logged_out` | Autenticación | Duración de sesión → dimensionar turnos y TTL | Batch (diario) |
| `route_access_denied` | Seguridad/permisos | Usuarios que intentan entrar en secciones sin permiso → revisar roles | **Stream** |
| `page_viewed` | Navegación | Secciones más/menos usadas por operadores → priorizar mejoras del backoffice | Batch (diario) |
| `api_latency_recorded` | Rendimiento | Endpoints lentos (p95) por almacén → optimizar o cachear | Batch (ventanas de 5 min) |
| `web_vital_recorded` | Rendimiento | LCP/INP/CLS por ruta → priorizar optimización frontend | Batch (diario) |
| `frontend_error_captured` | Errores | Errores JS no capturados tras un despliegue → rollback o hotfix | **Stream** |
| `api_request_failed` | Errores | 5xx o fallos de red desde el backoffice → incidencia antes de que llegue el ticket | **Stream** |

### 3.3 Oportunidades solo de catálogo (hipótesis + decisión, esquema en una versión futura)

`product_min_threshold_updated` (auditar quién cambia los mínimos), `product_created`, `order_list_filtered`, `inventory_export_downloaded`, `warehouse_view_switched`, `telemetry_batch_discarded` (lotes perdidos tras 3 reintentos, enviado en el siguiente flush correcto). El agente confirma en la Fase 0 cuáles tienen una pantalla o endpoint real; los que no, se quedan como "futuro".

---

## 4. Fase 0 — Reconocimiento del monorepo (sin escribir docs todavía)

**Objetivo:** saber exactamente dónde ocurre cada evento en el código real, para que el plan sea implementable sin preguntas.

| # | Acción | Commit |
|---|---|---|
| 0.1 | Commitear este plan (`memory-bank/history/2026-11-18_telemetry-design.md`) y el prompt (`prompts/telemetry-design/prompt.md`) si Marisin los dejó sin commitear. | `docs: añadir plan por fases y prompt del diseño de telemetría` |
| 0.1b | En `prompts/README.md`: añadir la fila de este proyecto y marcar caching como mergeado (PR #15). | `docs: registrar el proyecto de diseño de telemetría en el índice de prompts` |
| 0.2 | Leer `AGENTS.md`, `CONTEXT.md`, `memory-bank/projectbrief.md`, `memory-bank/techContext.md` y `memory-bank/progress.md`, y comprobar si el BRIEFING de telemetría está en el repo. | — |
| 0.3 | Mapear el backend `services/`: routers de productos, órdenes de entrada/salida, stock, auth; modelos/tablas de Supabase; dónde se rechaza la edición directa de stock (status code y cuerpo de error); dónde se evalúa el mínimo de stock; si existe lógica de conteo/auditoría para discrepancias; si hay middleware de `X-Request-ID`. | — |
| 0.4 | Mapear el frontend `uis/backoffice/`: rutas/páginas, formularios de orden y sus pasos, hook/contexto de auth, cliente HTTP compartido, Error Boundary existente, si hay `reportWebVitals`. | — |
| 0.4b | Confirmar o corregir punto por punto los hallazgos de §2.1. | — |
| 0.5 | Verificar nombres reales de campos (`client_id`, `product_id`/`sku`, `category`, `warehouse`…) y anotar cualquier diferencia con el BRIEFING. **El BRIEFING manda en la telemetría**; la diferencia se documenta como mapeo. | — |
| 0.6 | Crear `docs/telemetry/` con un `telemetry-plan.md` que solo tenga el índice de secciones (sección 6 de este plan) y un `event-schemas.json` mínimo válido (`{}` con `$schema`). | `docs: crear estructura de docs/telemetry para el plan de telemetría` |
| 0.7 | Actualizar `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 0 de telemetría` |

**Resumen de fase 0 debe incluir:** tabla `evento → archivo/componente/endpoint donde se capturaría → existe hoy (sí/no/parcial)`, lista de discrepancias de nombres, y lista de eventos que dependen de lógica no implementada (p. ej. si no hay conteo físico, `inventory_discrepancy_detected` queda como "punto de captura pendiente de implementar", pero **sigue en el plan** porque es obligatorio).

🛑 **STOP — auditoría de Fase 0.**

---

## 5. Fase 1 — Catálogo exhaustivo y flujo de inventario

**Rúbrica cubierta:** métricas obligatorias presentes; cobertura técnica + negocio amplia; hipótesis y decisión por evento; clasificación obligatorio/oportunidad.

| # | Acción (en `telemetry-plan.md`) | Commit |
|---|---|---|
| 1.1 | §1 Contexto y alcance: respuesta al RFI, consumidores (Ana, Thomas, Miguel, Tecnología/Andrés), dimensiones de agregación (almacén, cliente, país, SKU, categoría). | `docs: añadir contexto y alcance al plan de telemetría` |
| 1.2 | §2 Flujo de inventario: diagrama Mermaid desde login → navegación → formulario de orden → validación → creación → recálculo de stock → umbral. Marcar **≥5 puntos de instrumentación** con su `event_type`, incluyendo intento de edición directa rechazado, validación fallida y umbral mínimo. Cada punto con su archivo/componente real de la Fase 0. | `docs: añadir mapa del flujo de inventario con puntos de instrumentación` |
| 1.3 | §3.1 Catálogo de obligatorios: tabla con `event_type`, categoría, **origen = Obligatorio (BRIEFING)**, punto de captura y la frase de la regla de oro completa: *"Capturamos `X` porque necesitamos saber `Y`, lo que nos permite tomar la decisión `Z`."* | `docs: añadir catálogo de métricas obligatorias del BRIEFING` |
| 1.4 | §3.2 Oportunidades de negocio/inventario y UX (validaciones, formularios, reposición, búsqueda), con origen = **Oportunidad identificada** y frase de la regla de oro. | `docs: añadir oportunidades de negocio y UX al catálogo de telemetría` |
| 1.5 | §3.2 Oportunidades de autenticación y seguridad. | `docs: añadir oportunidades de autenticación y permisos al catálogo` |
| 1.6 | §3.2 Oportunidades de rendimiento, errores y navegación. | `docs: añadir oportunidades técnicas de rendimiento, errores y navegación` |
| 1.7 | §3.3 Oportunidades solo de catálogo (futuro) con su frase de la regla de oro. | `docs: añadir oportunidades de catálogo para versiones futuras` |
| 1.8 | §3.4 Tabla resumen: total de eventos, obligatorios vs. identificados, conteo por categoría. | `docs: añadir resumen cuantitativo del catálogo de eventos` |
| 1.9 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 1 de telemetría` |

**Criterio de aceptación:** ningún evento sin frase de la regla de oro completa; si no se puede completar, el evento pasa a la sección de descartados (Fase 3).

🛑 **STOP — auditoría de Fase 1.**

---

## 6. Fase 2 — Event Envelope, allowlists y `event-schemas.json`

**Rúbrica cubierta:** envelope consistente con los 8 campos; allowlist por evento; propiedades con tipo/obligatoriedad/descripción; PII identificada; JSON válido y coherente con el Markdown.

| # | Acción | Commit |
|---|---|---|
| 2.1 | §4 Event Envelope en `telemetry-plan.md`: tabla con `eventId`, `timestamp`, `sessionId`, `userId`, `event_type`, `schemaVersion`, `requestId`, `properties` → tipo, formato, obligatorio, quién lo genera (servicio de telemetría, **nunca** el componente), reglas D2–D7. Incluir un ejemplo JSON completo de un evento. | `docs: definir el Event Envelope estándar de TrackFlow` |
| 2.2 | §5 Convenciones: taxonomía `entidad_acción` y verbos (D7), enums compartidos (`warehouse`, `country`, `product_category`), tipos (`client_id`/`product_id` como string, cantidades como integer), regla de allowlist (D8), versionado (D5). | `docs: documentar convenciones de nombres, enums y versionado` |
| 2.3 | §6 Esquemas de los 5 obligatorios: por evento → descripción, cuándo se dispara, tabla de `properties` (nombre, tipo, obligatorio/opcional, descripción, ejemplo), **allowlist explícito** como lista, PII (sí/no + tratamiento), `level` y `value` (D10). | `docs: añadir esquemas detallados de las métricas obligatorias` |
| 2.4 | §6 Esquemas de las 16 oportunidades, mismo formato. Puntos de PII a tratar sí o sí: `user_login_failed` (solo `failure_reason` ∈ `invalid_credentials`/`session_expired`/`network_error`/`account_locked`, **nunca** email ni contraseña ni hash), `frontend_error_captured` (mensaje sanitizado: quitar emails, tokens y secuencias numéricas largas, truncar a 200 caracteres; stack reducido a `archivo:línea` sin query strings), `page_viewed`/`api_latency_recorded` (ruta como **plantilla**, p. ej. `/inventory/products/[id]`, sin query params), `inventory_search_performed` (solo `query_length` y `results_count`, nunca el texto buscado). | `docs: añadir esquemas detallados de las oportunidades identificadas` |
| 2.5 | `event-schemas.json` en JSON Schema draft-07: `definitions.envelope`, enums en `definitions`, un schema por evento con `allOf: [envelope]`, `event_type` como `const`, `properties` con `required` y `additionalProperties: false`; anotaciones `x-category`, `x-origin` (`mandatory`/`opportunity`), `x-delivery` (`stream`/`batch`), `x-pii`, `x-level`, `x-value-property`. Raíz con `oneOf` de todos los eventos. | `docs: añadir event-schemas.json con esquemas JSON Schema draft-07` |
| 2.6 | Añadir `examples` (1 evento válido por esquema) dentro del JSON. | `docs: añadir eventos de ejemplo a event-schemas.json` |
| 2.7 | Validar **sin commitear scripts**: `python -m json.tool docs/telemetry/event-schemas.json`; si `jsonschema` está instalado, validar el metaschema draft-07 y que cada `example` pase su esquema y que un ejemplo con una clave extra **falle**. Si falta el paquete, no instalar nada: decirlo en el resumen. Pegar la salida en el resumen. | — (solo si hubo que corregir: `fix: corregir errores de validación en event-schemas.json`) |
| 2.8 | Comprobación cruzada md ↔ json: mismos eventos, mismas claves, mismos tipos, mismos obligatorios. | `docs: alinear telemetry-plan.md con event-schemas.json` (solo si hubo cambios) |
| 2.9 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 2 de telemetría` |

**Criterio de aceptación:** los 5 obligatorios llevan **todas** las propiedades mínimas del BRIEFING (`warehouse`, `client_id`, `product_id`, `product_category`, `quantity`) como `required`, más `country`. Ningún evento de inventario lleva claves de transportista, destinatario ni consumidor final.

🛑 **STOP — auditoría de Fase 2.**

---

## 7. Fase 3 — Estrategia de entrega, throttle/debounce, riesgos y exclusiones

**Rúbrica cubierta:** stream/batch justificado por urgencia de negocio; throttle/debounce; riesgos y exclusiones con pensamiento crítico.

| # | Acción (en `telemetry-plan.md`) | Commit |
|---|---|---|
| 3.1 | §7 Definición operativa de stream vs. batch (D9) y tabla de **todos** los eventos con esquema: entrega, ventana de agregación, quién consume y **por qué esa urgencia** (en términos de la decisión, no de tecnología). Argumento de las decisiones difíciles: `direct_stock_edit_rejected` es batch porque su decisión (formación/permisos) se toma por semanas, no por minutos; los intentos sospechosos en ráfaga ya los cubren `route_access_denied` y `user_login_failed` en stream. | `docs: añadir estrategia stream/batch justificada por urgencia de negocio` |
| 3.2 | §8 Throttle/debounce de alta frecuencia: `api_latency_recorded` (100 % si `status_code ≥ 400` o `duration_ms > 1000`, muestreo del 20 % en el resto, con la propiedad `sample_rate` para reponderar); `page_viewed` (deduplicar misma ruta en <1 s); `frontend_error_captured` (máx. 1 por `error_fingerprint` y sesión cada 60 s, y tope de 10 por sesión y minuto); `inventory_search_performed` (debounce de 800 ms tras dejar de teclear); `web_vital_recorded` (1 por métrica y carga de página); `user_login_failed` **sin muestreo** (seguridad), con tope de 20 por sesión y minuto. | `docs: documentar estrategia de throttle y debounce para eventos de alta frecuencia` |
| 3.3 | §9 Privacidad y PII: tabla consolidada campo → riesgo → tratamiento (eliminar, truncar, plantillar, enum cerrado). Separación perfil/uso: nombre, rol y preferencias del usuario viven en la BD principal, no en telemetría. | `docs: añadir sección de privacidad y tratamiento de PII` |
| 3.4 | §10 Riesgos y exclusiones: **eventos descartados con su razón** (p. ej. `stock_level_viewed`: el stock es estado, ya está en la BD; `form_field_changed`: ruido sin decisión; `mouse_moved`/session replay: coste y privacidad; `product_price_viewed`: dato comercial sensible sin decisión asociada; `carrier_assigned` y datos del destinatario: pertenecen al proyecto de última milla, prohibido por el BRIEFING); **datos que no se capturan** (IP, user agent completo, texto libre de búsquedas, query strings, email en login fallido, precios/costes); **riesgos** (doble conteo si el frontend reintenta → deduplicar por `eventId`; desfase de reloj del cliente; eventos de backend capturados desde el frontend que se pierden si se cierra la pestaña → recomendar emisión desde backend en el futuro; deriva de esquemas → versionado D5; cardinalidad de `route`). | `docs: añadir riesgos, eventos descartados y exclusiones de datos` |
| 3.5 | §11 Mapeo previsto a almacenamiento (breve, sin diseñar la tabla): qué irá a columnas fijas (`timestamp`, `event_type`, `level`, `value`) y que `properties` + `eventId`, `sessionId`, `userId`, `schemaVersion`, `requestId` irían en `tags`, preservando `warehouse`, `client_id`, `country`. | `docs: documentar el mapeo previsto del envelope al almacenamiento` |
| 3.6 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 3 de telemetría` |

🛑 **STOP — auditoría de Fase 3.**

---

## 8. Fase 4 — Revisión final contra la rúbrica y texto del PR

| # | Acción | Commit |
|---|---|---|
| 4.1 | §12 "Guía para quien instrumente": por evento, una línea `event_type → componente/hook o endpoint → condición exacta de disparo`. Es la prueba de que otro desarrollador puede instrumentar sin preguntar. | `docs: añadir guía de instrumentación por evento` |
| 4.2 | Repasar el checklist de la sección 10 punto por punto y corregir lo que falte. | `docs: ajustes finales del plan de telemetría tras revisión de rúbrica` (si aplica) |
| 4.3 | Revalidar `event-schemas.json` (como en 2.7) y la coherencia md↔json. | — |
| 4.4 | Redactar en el resumen (no en un fichero del repo) la descripción del PR con: total de eventos con esquema, cuántos son obligatorios vs. identificados, categorías cubiertas y la frase de la decisión más difícil (propuesta: *"La más difícil fue aceptar procesar `direct_stock_edit_rejected` en batch y no en stream: su decisión es de formación y permisos, que se toma por semanas, y los patrones sospechosos en tiempo real ya los cubren `route_access_denied` y `user_login_failed`."*). | — |
| 4.5 | `progress.md` con el cierre del proyecto 1/3. | `docs: actualizar progress.md con el cierre del diseño de telemetría` |

🛑 **STOP final.** Marisin sube la rama y abre el PR `docs: telemetry design plan`.

---

## 9. Plantilla de resumen al cerrar cada fase

```
## Resumen Fase N — <nombre>
**Commits realizados:** (hash corto + mensaje, en orden)
**Ficheros tocados:**
**Qué se hizo:** (3–6 viñetas)
**Decisiones tomadas por el agente que no estaban en el plan:**
**Discrepancias con el código real o con el BRIEFING:**
**Pendiente / dudas para auditoría:**
**Checklist de rúbrica cubierto en esta fase:** (ítems de la sección 10)
⏸ Esperando "OK fase N, continúa".
```

---

## 10. Checklist de la rúbrica (auditoría final)

- [ ] Las 5 métricas obligatorias están con su nombre exacto, origen "Obligatorio (BRIEFING)" y las 5 propiedades mínimas como `required`.
- [ ] Entidades e identificadores coinciden con el BRIEFING (`warehouse` en minúscula, `los_angeles`/`zaragoza`, `fashion`/`electronics`/`cosmetics`).
- [ ] Las métricas son agregables por almacén, cliente y país (`country`).
- [ ] Flujo de inventario mapeado con ≥5 puntos (incluye edición directa rechazada, validación fallida y umbral).
- [ ] Catálogo amplio: técnico (auth, rendimiento, errores, navegación) **y** negocio; ≥8 oportunidades con esquema en ≥3 categorías (plan: 16 en 6).
- [ ] Cada evento tiene la frase de la regla de oro completa.
- [ ] Clasificación obligatorio / oportunidad visible en el catálogo y en el JSON (`x-origin`).
- [ ] Envelope idéntico en todos los eventos con los 8 campos; `timestamp` ISO 8601; `event_type` `entidad_acción`.
- [ ] Allowlist explícito por evento (lista en md + `additionalProperties: false` en JSON).
- [ ] Cada propiedad con nombre, tipo, obligatorio/opcional y descripción.
- [ ] PII identificada y con tratamiento; ningún email, nombre, contraseña, dato de consumidor final, transportista o destinatario.
- [ ] `event-schemas.json` es JSON válido, draft-07, y coherente con el md.
- [ ] Stream/batch justificado por urgencia de la decisión, no por preferencia técnica.
- [ ] Throttle/debounce documentado para los eventos de alta frecuencia.
- [ ] Riesgos y exclusiones con eventos descartados razonados y datos no capturados.
- [ ] Guía de instrumentación: otro dev puede implementarlo sin preguntar.
- [ ] Ningún cambio fuera de `docs/telemetry/`, `memory-bank/progress.md`, `prompts/README.md` y `prompts/telemetry-design/`.
- [ ] Las discrepancias BRIEFING ↔ código (D11–D14, §2.1) están documentadas en el plan como mapeos o puntos pendientes, no ocultas.
- [ ] PR `docs: telemetry design plan` con total de eventos, obligatorios vs. identificados, categorías y decisión más difícil.
