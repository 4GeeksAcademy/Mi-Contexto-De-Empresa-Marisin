# Plan de ejecución — Optimización de rendimiento: Caching (TrackFlow)

- **Proyecto 4Geeks:** Optimización de rendimiento: Caching
- **Fecha del plan:** 2026-11-16
- **Rama de trabajo:** `feature/caching-optimisation` (la crea la desarrolladora; el agente NO crea ramas)
- **Entregable principal:** código + `CACHING_REPORT.md` en la raíz del monorepo
- **Registro de avance del proyecto:** la sección §14 al final de ESTE fichero (tabla de fases + registro). El registro global del monorepo sigue siendo `memory-bank/progress.md`.
- **Prompt de arranque:** `prompts/caching-optimisation/prompt.md`

> Convención de documentación (desde este proyecto): cada proyecto tiene UN fichero en `memory-bank/history/AAAA-MM-DD_<proyecto>.md` con su plan por fases y su propio registro de avance; `memory-bank/progress.md` es el registro global y constante; `prompts/<proyecto>/prompt.md` guarda solo el prompt corto que lanza al agente. La carpeta `prompts/serialization-audit/` es de un proyecto anterior con otra convención y NO se mueve ni se modifica.
- **Ejecutor:** agente del Codespace (GitHub Copilot), fase a fase, con parada obligatoria al final de cada fase

---

## 0. ROL Y PRINCIPIOS

Actúas como **Senior Backend & Frontend Performance Engineer y Tech Lead**. Tu trabajo no es "cachear lo lento", sino tomar **pocas decisiones de caching, medidas y justificadas**, implementarlas sin regresiones y dejar un informe que el equipo de TrackFlow pueda auditar.

Regla de oro del proyecto: **primero medir, luego decidir, luego implementar, luego volver a medir.**

### 0.1 Reglas inquebrantables

1. **Cero invenciones.** Todo nombre de fichero, función, endpoint, componente o cifra que aparezca en el informe debe existir en el repo o en un fichero de resultados generado en este proyecto. Ninguna latencia se escribe "de memoria": cada número del informe sale de un fichero de `docs/caching/benchmarks/`. Si algo no se pudo medir, se escribe **"no medido"** y el motivo.
2. **Las candidaturas de este plan son hipótesis.** Están preseleccionadas tras revisar el código, pero si la medición las contradice (p. ej. un endpoint resulta rápido incluso con carga), lo documentas y propones la alternativa ANTES de implementar. No fuerces una decisión para cuadrar el plan.
3. **Cambios mínimos y localizados.** No reescribas routers, servicios ni páginas enteras. No cambies contratos de respuesta (`response_model`) ni tipos compartidos.
4. **Ningún dato privado en una clave compartida.** Solo se cachean respuestas que son idénticas para cualquier usuario. Prohibido cachear `/auth/*`, `/profiles/*`, `/users/*` o cualquier respuesta que dependa de `get_current_user`.
5. **Nunca cachear la validación de stock.** `_warehouse_balances()` en `services/api/routes/inventory.py` se usa para validar salidas (`create_outbound_order`). Debe seguir consultando la base de datos en cada llamada. Prohibido aplicarle `lru_cache` o cualquier caché: un stock cacheado ahí permitiría sobreventa.
6. **Prohibido `functools.lru_cache` en funciones que reciben `session` o `Request`**, y en cualquier dato sin TTL. Todo valor cacheado tiene expiración.
7. **Áreas protegidas (AGENTS.md §3):** la desarrolladora **autoriza expresamente** en este proyecto: (a) crear ficheros NUEVOS en `scripts/perf/` (sin modificar ficheros existentes de `scripts/`); (b) añadir el módulo nuevo `services/api/cache.py` y el middleware de timing en `services/api/main.py`; (c) los cambios de caching e invalidación descritos en `services/api/routes/inventory.py` y `services/api/routes/incidents.py`. Nada más de `services/`, `infra/`, `.env` o credenciales.
8. **`data/suppliers.json` es la base TinyDB local y ya NO está versionada** (la desarrolladora la sacó de git y la añadió a `.gitignore` en el primer commit de la rama). El seeder de carga escribirá incidencias en ella: si en algún momento vuelve a aparecer en `git status`, PARA y avisa. Aun así, prohibido `git add .` y `git add -A`: haz siempre `git add <rutas explícitas>` y revisa `git status` antes de cada commit.
9. **Commits:** formato convencional con descripción en español (`feat(api): ...`, `perf(inventory): ...`, `docs(caching): ...`). Un cambio lógico por commit y **al menos un commit por fase** (los mensajes exactos están en cada fase). Ninguna fase se da por cerrada con cambios sin commitear.
10. **Git solo en local:** prohibido `git pull`, `git fetch`, `git merge`, `git rebase`, `git push`, `git switch`/`checkout` de rama y abrir el PR. La sincronización con GitHub la hace solo la desarrolladora.
11. **Sin servidores colgados:** valida frontends con `npm run build`. Si necesitas levantar la API para medir, deténla al terminar la fase.
12. **Parada obligatoria** al final de cada fase con el reporte de §12.2. No empieces la siguiente fase sin la confirmación "continúa con la Fase N".

---

## 1. CONTEXTO VERIFICADO DEL REPO (punto de partida)

Comprueba cada punto al empezar (Fase 0). Si alguno ya no es cierto, anótalo en la §14 de este plan y adapta el paso afectado.

### 1.1 Backend (`services/api/`)

- App FastAPI en `services/api/main.py`; routers: `suppliers`, `users`, `auth`, `profiles`, `inventory`, `incidents`. No existe todavía middleware de timing ni ningún mecanismo de caché.
- **Dos almacenes de datos:**
  - **PostgreSQL (Supabase)** vía SQLModel para inventario (`SKU`, `StockEntry`, `StockExit` en `models.py`). `database.py` crea el engine con `poolclass=NullPool` y `sslmode=require`: **cada petición abre una conexión TLS nueva** contra el pooler de Supabase. Es un coste por petición relevante que el informe debe explicar.
  - **TinyDB** (`data/suppliers.json`) para suppliers, users, profiles, tokens e incidencias. TinyDB lee el fichero JSON completo en cada `.all()`.
- Endpoints con más coste aparente:
  - `GET /inventory/products` (`list_products`): 1 query de SKUs + 2 queries `GROUP BY` agregadas (`_warehouse_balances` sobre `stock_entries` y `stock_exits`) + suma en Python. **No requiere JWT**; la respuesta es igual para todos.
  - `GET /api/incidents/summary` (`summary()` en `services/api/services/incidents.py`): recorre todas las incidencias de TinyDB y agrega 4 dimensiones. **No requiere JWT**; respuesta global.
  - `GET /inventory/orders` (`list_orders`): lee todas las entradas, salidas y SKUs, construye y ordena la lista completa en Python. Crece sin límite.
- Escrituras que afectan a esos datos:
  - Inventario: `POST /inventory/products`, `POST /inventory/orders/inbound`, `POST /inventory/orders/outbound`.
  - Incidencias: `POST /api/incidents`, `PATCH /api/incidents/{incident_id}/status`.
- Semillas existentes: `services/seed.py` (inventario relacional, 2 SKUs y 8 movimientos) y `seed_database()` en `database.py` (admin de demo, 2 suppliers). `scripts/seed_incidents.py` solo valida un CSV, no inserta.
- Tests: `tests/test_auth.py`, `tests/test_serialization_contracts.py`. Último resultado conocido: `pytest -q` → 9 passed.

### 1.2 Frontends (`uis/`)

- `uis/website` (Next.js 16, puerto 3000): landing; `app/page.tsx` es Server Component y renderiza `Header`, `Hero`, `ServicesSection`, `CoverageSection`, `BenefitsSection`, **`LeadForm` (350 líneas, client, penúltima sección, fuera del viewport inicial)** y `ContactFooter`.
- `uis/backoffice` (Next.js 16, puerto 3001): inventario. Consume `GET /inventory/products` y `GET /inventory/orders` (`src/lib/inventory.ts`).
  - `src/app/inventory/orders/outbound/page.tsx`: calcula `currentStock` con un `orders.reduce(...)` sobre **todo el historial de órdenes** en cada render. El componente se re-renderiza en cada pulsación de los inputs `quantity` y `trackingNumber`, aunque `orders` no cambie. Con el volumen del seeder (miles de órdenes) es O(n) por tecla.
- `uis/application` (Next.js 16, puerto 3002): consola interna.
  - `app/incidents/analyze/page.tsx` ('use client'): el bloque de resultados (`MetricCard`, `BreakdownCard`, desglose de inválidos) **solo se muestra tras analizar un CSV con éxito** (`uiState === 'success' && result`).
  - `components/incidents/IncidentWorkspace.tsx` consume `GET /api/incidents/summary` al montar y tras cada cambio de estado (`loadSummary()`).
- Ya existen `useMemo` en `uis/application/components/TalentPanel.tsx` y `uis/website/components/LeadForm.tsx`; no cuentan como entregable de este proyecto.
- Builds conocidos que funcionan:
  - website: `NODE_ENV=production npm run build`
  - backoffice: `NODE_ENV=production NEXT_PUBLIC_INVENTORY_API_URL=http://127.0.0.1:8000 npm run build`
  - application: `npm run build`

---

## 2. DECISIONES PRESELECCIONADAS (hipótesis a validar con medición)

| # | Capa | Objetivo | Técnica | Motivo inicial |
|---|------|----------|---------|----------------|
| B1 | Backend | `GET /inventory/products` | Caché TTL en memoria, **TTL 30 s**, clave global | 3 queries + conexión TLS nueva por petición; lo pide cada página del backoffice al montar; los datos solo cambian con escrituras de inventario |
| B2 | Backend | `GET /api/incidents/summary` | Caché TTL en memoria, **TTL 60 s**, clave global | Escaneo completo de TinyDB + agregación de 4 dimensiones; lo pide `IncidentWorkspace` al montar y tras cada cambio de estado |
| F1 | Frontend | `LeadForm` en `uis/website` | `next/dynamic` montado al acercarse al viewport, con placeholder de altura fija | Componente cliente grande, fuera del viewport inicial; su JS no es necesario para el LCP |
| F2 | Frontend | Resultados de `/incidents/analyze` en `uis/application` | Extraer a `AnalysisResults` + `next/dynamic` con `ssr: false` | Solo se necesita tras un análisis con éxito; muchos usuarios nunca llegan a esa vista |
| F3 | Frontend | Stock disponible en `outbound/page.tsx` | `useMemo` para un índice de stock por `sku|warehouse` | Reduce O(n) en cada tecla → índice O(n) solo cuando cambia `orders` + lookup O(1) |

Candidatos explícitamente **descartados** (irán en "Qué no se cacheó y por qué"): ver §8.4.

---

## 3. FASE 0 — Preparación y baseline (sin tocar código)

**Objetivo:** confirmar el entorno, el estado del repo y dejar el baseline registrado.

Pasos:
1. `git branch --show-current` → debe ser `feature/caching-optimisation`. Si no, PARA y avisa.
2. `git status` limpio (salvo este plan si aún no está commiteado). Comprueba que `git ls-files data/suppliers.json` no devuelve nada y que `.gitignore` incluye `data/suppliers.json`; si no es así, PARA y avisa.
3. Lee `AGENTS.md`, `memory-bank/projectbrief.md`, `memory-bank/techContext.md`, `memory-bank/progress.md`, `CONTEXT.md` y este plan completo. Revisa `.agents/skills/performance/` y `.agents/skills/core-web-vitals/`: si aplican, úsalas y cítalas en el informe.
4. Activa el entorno: `source /workspaces/Mi-Contexto-De-Empresa-Marisin/.venv/bin/activate`.
5. Comprueba los puntos de §1. Anota cualquier discrepancia.
6. Inventario real de rutas: ejecuta un snippet que recorra `app.routes` (instancias de `APIRoute`) e imprima método, path, función y si depende de `get_current_user`. Guárdalo en `docs/caching/routes-inventory.md`.
7. Baseline de tests: `pytest -q` → anota el resultado exacto.
8. Baseline de builds de los 3 frontends con los comandos de §1.2 → anota OK/KO. Si la salida de `next build` muestra tamaños de JS por ruta, guárdala en `docs/caching/frontend/build-before-<app>.txt`; si no los muestra, anótalo (se medirá en Network en la Fase 6).
9. Rellena la sección §14 de este plan con el baseline. En `prompts/README.md`: añade una fila (Proyecto: Optimización de rendimiento: Caching · Carpeta `caching-optimisation/` · Rama `feature/caching-optimisation` · Estado En curso) y, debajo de la tabla, una nota breve con la convención de documentación descrita en la cabecera de este plan (sin borrar ni cambiar lo existente).
10. Guarda el prompt de arranque que te dio la desarrolladora en `prompts/caching-optimisation/prompt.md` si no existe ya.

**Commit:** `docs(caching): registrar plan, inventario de rutas y baseline del proyecto`
(incluye este plan si no estaba commiteado, `docs/caching/routes-inventory.md`, `prompts/caching-optimisation/prompt.md`, `prompts/README.md`).

**Criterios de aceptación:**
- [ ] Rama verificada.
- [ ] `docs/caching/routes-inventory.md` lista TODAS las rutas reales con su método, path, función y auth.
- [ ] Baseline de pytest y builds anotado en la §14 con resultado literal.

⛔ **STOP — Reporte de Fase 0.**

---

## 4. FASE 1 — Instrumentación: middleware de timing + script de benchmark

**Objetivo:** poder medir con evidencia, no por intuición.

### 1.A Middleware de timing (`services/api/main.py`)
- Añade un middleware HTTP basado en el del enunciado (`time.perf_counter()`), con logger `api.timing`.
- **Importante:** uvicorn no configura loggers propios de la app; si solo haces `logging.getLogger("api.timing")`, los `INFO` no se verán. Configura ese logger concreto (nivel INFO, un `StreamHandler` solo si no tiene handlers, `propagate = False` para no duplicar líneas). No toques la configuración global de logging.
- Formato de línea: `GET /inventory/products → 200 | 312.4ms` (incluye query string si existe: `request.url.path` + `?` + `request.url.query`).
- Añade además la cabecera de respuesta `X-Response-Time-ms` con la duración (la usará el benchmark).
- Debe registrarse **antes** de `include_router` y no interferir con CORS ni con el `exception_handler` existente.

**Commit:** `feat(api): añadir middleware de timing por petición`

### 1.B Script de benchmark (`scripts/perf/bench_endpoints.py`, fichero NUEVO)
- Usa `httpx` (ya está en el grupo dev de `pyproject.toml`). Sin dependencias nuevas.
- Argumentos: `--base-url` (por defecto `http://127.0.0.1:8000`), `--label` (obligatorio, p. ej. `01-baseline-small`), `--runs` (por defecto 30).
- Endpoints a medir (GET):
  - `/inventory/products`, `/inventory/orders`, `/inventory/products/{id}` (id = primer producto de la lista)
  - `/api/incidents`, `/api/incidents/summary`
  - `/suppliers` (requiere JWT: haz login con las credenciales de demostración que crea `seed_database()`; no las imprimas en el informe)
- Por endpoint registra: **primera petición** (fría) aparte; y para las `runs` siguientes, min / p50 / p95 / max en ms, tamaño medio de respuesta en KB y el recuento de valores de la cabecera `X-Cache` (HIT/MISS/BYPASS/ausente).
- Registra también el **volumen de datos**: nº de productos (longitud de `/inventory/products`), nº de órdenes (longitud de `/inventory/orders`), total de incidencias (`total` de `/summary`).
- Salida: tabla Markdown en `docs/caching/benchmarks/<label>.md` con fecha/hora, base-url, runs, volumen y tabla de resultados. También la imprime por consola.

**Commit:** `chore(perf): añadir script de benchmark de endpoints`

### 1.C Primera medición (datos actuales, pocos registros)
- Arranca la API: `python -m uvicorn services.api.main:app --port 8000` (desde la raíz, con el `.env` existente).
- Ejecuta `python scripts/perf/bench_endpoints.py --label 01-baseline-small`.
- Copia 10–15 líneas representativas del log de timing a `docs/caching/benchmarks/01-baseline-small-log.txt`.
- Detén la API.

**Commit:** `docs(caching): registrar medición base con el volumen inicial`

**Criterios de aceptación:**
- [ ] El log muestra una línea por petición con método, ruta, status y ms.
- [ ] `docs/caching/benchmarks/01-baseline-small.md` existe y sus cifras salen del script.
- [ ] `pytest -q` sigue igual que el baseline.

⛔ **STOP — Reporte de Fase 1** (incluye la tabla del benchmark en el reporte).

---

## 5. FASE 2 — Carga realista de datos + segunda medición

**Objetivo:** que la latencia refleje un volumen creíble para TrackFlow (2 almacenes, decenas de clientes marca, miles de movimientos).

### 2.A Seeder de carga (`scripts/perf/seed_load.py`, fichero NUEVO)
- Ejecutable como `python -m scripts.perf.seed_load` desde la raíz (o `python scripts/perf/seed_load.py`; elige lo que funcione con los imports de `services.api` y documéntalo).
- Determinista: `random.Random(42)`.
- **Inventario (PostgreSQL, vía `engine` y modelos de `services/api/models.py`):**
  - ~300 SKUs con prefijo `LOAD-` en `sku` (ej. `LOAD-APP-0001`), repartidos entre ~25 clientes marca ficticios de e-commerce, 6–8 categorías realistas (Apparel, Electronics, Home, Beauty, Sports, Accessories, Packaging, Toys) y referencias únicas.
  - ~12.000 movimientos: ~8.000 `StockEntry` y ~4.000 `StockExit`, repartidos entre `Los Angeles` y `Zaragoza`, con `created_at` distribuido en los últimos 18 meses, `exit_type` variado (`B2C Order`, `B2B Transfer`, `Return / Damaged`), `tracking_number` con formato de transportista (UPS, FedEx, SEUR, MRW, DHL) y `user_uuid = "seed-load"`.
  - **Invariante obligatorio:** para cada (sku, almacén), la suma de salidas nunca supera la de entradas (el stock nunca queda negativo). Verifícalo al final del seed con una query y falla si no se cumple.
  - Inserción por lotes (p. ej. 1.000 filas por commit). Si `engine is None`, aborta con mensaje claro.
- **Incidencias (TinyDB, `incidents_table`):** ~3.000 incidencias con título prefijado `[LOAD]`, valores válidos de `IncidentCategory`, `IncidentStatus`, `IncidentOrigin` e `IncidentBranch` (léelos de `models.py`), descripciones variadas y `created_at`/`updated_at` coherentes. Usa `insert_multiple` (un único volcado al fichero), no inserciones una a una.
- **Idempotencia:** si ya existen SKUs `LOAD-` o incidencias `[LOAD]`, no duplica (informa y sale).
- **Limpieza:** opción `--purge` que elimina solo los datos de carga (SKUs `LOAD-` y sus movimientos; incidencias `[LOAD]`).
- Imprime el resumen: filas antes y después por tabla.

**Antes de ejecutarlo:** `cp data/suppliers.json /tmp/suppliers.pre-load.json` (copia de seguridad fuera del repo).

**Commit (solo el script):** `chore(perf): añadir seeder de carga realista para inventario e incidencias`

### 2.B Ejecución y segunda medición
1. Ejecuta el seeder. Guarda su salida (volumen antes/después) en `docs/caching/benchmarks/02-seed-output.txt`.
2. Arranca la API y ejecuta `--label 02-baseline-load`. Guarda 10–15 líneas del log en `02-baseline-load-log.txt`.
3. Lanza además 20 peticiones seguidas a `/inventory/products` y a `/api/incidents/summary` y observa el log: confirma si la latencia es consistente (eje coste) y si la respuesta es idéntica entre llamadas (eje estabilidad).
4. Detén la API.
5. `git status`: `data/suppliers.json` NO debe aparecer (está ignorado). Si aparece, PARA y avisa.

### 2.C Validación de candidatos con evidencia
Escribe en `docs/caching/candidates.md` una tabla con TODOS los endpoints de `routes-inventory.md`:

| Endpoint | Coste medido (p50/p95) | Frecuencia estimada | Frecuencia de cambio de datos | ¿Personal/sensible? | Decisión |

- **Frecuencia estimada:** no hay telemetría real; dedúcela del código de los frontends (qué páginas lo llaman, al montar, tras cada escritura, en qué flujos) y dilo así: "estimación basada en consumidores: …". Cita fichero y función consumidora.
- **Decisión:** CACHEAR / NO CACHEAR, con una frase de motivo.
- Si B1 o B2 NO se sostienen con los datos, PARA y propón alternativa en el reporte antes de seguir.

**Commit:** `docs(caching): medir con carga realista y priorizar candidatos con evidencia`

**Criterios de aceptación:**
- [ ] El seed respeta el invariante de stock no negativo (verificado por el propio script).
- [ ] `02-baseline-load.md` muestra el volumen después del seed y la latencia por endpoint.
- [ ] `candidates.md` cubre todos los endpoints con los 3 ejes + privacidad.
- [ ] `data/suppliers.json` sigue fuera de git (`git ls-files data/suppliers.json` vacío).

⛔ **STOP — Reporte de Fase 2** (incluye volumen antes/después, la comparación 01 vs 02 y la tabla de decisión).

---

## 6. FASE 3 — Módulo de caché TTL en memoria

**Objetivo:** una caché pequeña, explícita, segura con hilos y testeable.

### Diseño (`services/api/cache.py`, fichero NUEVO)
- Clase `TTLCache`:
  - `__init__(self, default_ttl: float, maxsize: int = 128, clock: Callable[[], float] = time.monotonic)` — el `clock` inyectable es para los tests.
  - `get(key) -> tuple[bool, Any]` → `(hit, value)`; si la entrada expiró, la borra y devuelve miss.
  - `set(key, value, ttl: float | None = None)`.
  - `invalidate(key)` e `invalidate_prefix(prefix)`.
  - `clear()` y `stats()` → `{"hits", "misses", "invalidations", "size"}`.
  - Thread-safe con `threading.Lock` (los endpoints `def` de FastAPI corren en un threadpool).
  - Si se supera `maxsize`, expulsa primero las entradas expiradas y después la más antigua.
- Instancia global `api_cache`.
- Interruptor por entorno **solo de lectura**: `TRACKFLOW_CACHE_ENABLED` (por defecto activo; `"0"` lo desactiva). Con la caché desactivada, los endpoints responden `X-Cache: BYPASS`. Sirve para comparar con/sin caché al mismo volumen. **No** modifiques `.env` ni `.env.example`.
- Constantes de claves y TTL en el propio módulo, documentadas con un comentario de una línea cada una:
  - `PRODUCTS_LIST_KEY = "inventory:products:list"` · `PRODUCTS_LIST_TTL = 30`
  - `INCIDENTS_SUMMARY_KEY = "incidents:summary"` · `INCIDENTS_SUMMARY_TTL = 60`
- Por qué no Redis: no está en el stack (`services/requirements.txt`, `docker-compose.yml`). Documenta en el informe que es el siguiente paso si la API se escala a varios workers/instancias.

**Commit:** `feat(api): añadir caché TTL en memoria con invalidación y métricas`

**Criterios de aceptación:**
- [ ] Ninguna entrada se guarda sin TTL.
- [ ] El módulo no importa nada de rutas ni de base de datos (sin dependencias circulares).

⛔ **STOP — Reporte de Fase 3.**

---

## 7. FASE 4 — Caching de endpoints e invalidación

### 4.A `GET /inventory/products` (B1)
- En `list_products`: añade el parámetro `response: Response` y consulta `api_cache` con `PRODUCTS_LIST_KEY`.
  - HIT → devuelve una **copia** de la lista cacheada (`list(cached)`) y `X-Cache: HIT`.
  - MISS → ejecuta la lógica actual sin cambios, guarda el resultado y `X-Cache: MISS`.
- **Invalidación:** llama a `api_cache.invalidate(PRODUCTS_LIST_KEY)` **después de `session.commit()` con éxito** en `create_product`, `create_inbound_order` y `create_outbound_order`. Si la operación falla (404, 400, 409) no se invalida porque no cambió nada.
- **No toques** `_warehouse_balances`, `get_product` ni la validación de stock de `create_outbound_order`.
- Verifica que `list_products` no depende de `get_current_user` y que la respuesta no contiene datos de un usuario concreto → clave global segura. Déjalo comentado en una línea sobre la función.

**Commit:** `perf(inventory): cachear listado de productos con TTL e invalidar en escrituras`

### 4.B `GET /api/incidents/summary` (B2)
- En `get_incidents_summary` (router `services/api/routes/incidents.py`): misma mecánica con `INCIDENTS_SUMMARY_KEY` y cabecera `X-Cache`.
- **Invalidación:** en `post_incident` y `patch_incident_status`, invalida `INCIDENTS_SUMMARY_KEY` después de que el servicio devuelva con éxito (si `update_incident_status` lanza `HTTPException` por transición no permitida, no se invalida).
- Verifica y comenta que el endpoint no usa JWT ni datos por usuario.

**Commit:** `perf(incidents): cachear resumen de incidencias con TTL e invalidar en escrituras`

### 4.C Tests (`tests/test_caching.py`, fichero NUEVO)
Mínimo:
1. **Unitarios de `TTLCache`** con reloj falso: miss inicial → hit tras `set` → miss tras superar el TTL; `invalidate` y `invalidate_prefix`; `maxsize` respetado; `stats` coherente.
2. **Integración incidencias** con TinyDB en memoria (`MemoryStorage`) parcheando `incidents_table` donde lo usen servicio y rutas (como en tests anteriores, sin tocar `data/suppliers.json`) y `api_cache.clear()` en cada test:
   - `GET /summary` → `MISS`; segundo `GET` → `HIT`;
   - `POST /api/incidents` → siguiente `GET /summary` es `MISS` y `total` aumenta en 1;
   - `PATCH` con transición inválida → la caché sigue en `HIT`.
3. **Integración inventario** sobrescribiendo `get_db` con SQLite en memoria (`StaticPool`) y `get_current_user` con un usuario falso; **sin** `with TestClient(app)` para no disparar el startup contra Supabase:
   - `GET /inventory/products` → `MISS`, luego `HIT`;
   - `POST /inventory/orders/inbound` → siguiente `GET` es `MISS` y el `current_stock` refleja la entrada;
   - `POST /inventory/orders/outbound` con cantidad mayor que el stock → 400 y la validación usa datos frescos aunque el listado esté en caché.
   - Si SQLite no soporta alguna construcción, documéntalo y marca solo esa prueba con `pytest.mark.skip` y motivo; no la elimines.
4. **Test de privacidad:** recorre `app.routes` y comprueba que ninguna ruta que dependa de `get_current_user` usa `api_cache` (por ejemplo, comprobando que las únicas funciones que leen de la caché son `list_products` y `get_incidents_summary`).

Ejecuta `pytest -q`: el baseline + los nuevos deben pasar.

**Commit:** `test(cache): cubrir TTL, invalidación y aislamiento de datos privados`

### 4.D Tercera medición
1. API con caché activa → `--label 03-after-cache`.
2. API con `TRACKFLOW_CACHE_ENABLED=0` → `--label 03-after-cache-bypass` (mismo volumen, sin caché; es la comparación justa).
3. Guarda líneas del log en `03-after-cache-log.txt` mostrando un MISS seguido de HITs y, tras un `POST`, un MISS por invalidación.

**Commit:** `docs(caching): medir latencia con y sin caché tras la implementación`

**Criterios de aceptación (rúbrica):**
- [ ] 2 endpoints cacheados con expiración TTL.
- [ ] Invalidación implementada y probada en escrituras.
- [ ] Ningún dato privado o de sesión en clave compartida (test de privacidad en verde).
- [ ] `pytest -q` en verde.
- [ ] Mejora cuantificada con datos de `03-after-cache.md` frente a `03-after-cache-bypass.md`.

⛔ **STOP — Reporte de Fase 4** (incluye la comparación de p50/p95 con y sin caché).

---

## 8. FASE 5 — Frontend: Lazy Loading (2 casos)

### 5.A `uis/website` — `LeadForm` (F1)
- `app/page.tsx` es Server Component: allí no se puede usar `ssr: false`. Crea un wrapper cliente NUEVO `components/LazyLeadForm.tsx` (`"use client"`) que:
  - Renderiza un placeholder con **la misma altura aproximada que el formulario** (mide la altura renderizada actual y fíjala con `min-h-[...]`) para **no introducir CLS** (en el proyecto de auditoría anterior se trabajó el CLS: no lo empeores).
  - Usa `IntersectionObserver` (`rootMargin` ~ `300px`) para montar, al acercarse al viewport, `dynamic(() => import("./LeadForm").then(m => m.LeadForm), { ssr: false, loading: <placeholder> })`.
  - Mantiene el `id`/ancla de la sección si algún enlace del `Header` o del `Hero` apunta al formulario (compruébalo con búsqueda; si existe, al pulsar el enlace el formulario debe montarse).
- Si `LeadForm` contiene títulos o texto de valor SEO, deja ese encabezado estático en el wrapper (renderizado en servidor) y difiere solo el formulario.
- Sustituye `LeadForm` por `LazyLeadForm` en `app/page.tsx`. No toques las validaciones del formulario.
- Build de website OK.

**Commit:** `perf(website): cargar LeadForm de forma diferida al acercarse al viewport`

### 5.B `uis/application` — resultados de `/incidents/analyze` (F2)
- Extrae el bloque de resultados (sección renderizada con `uiState === 'success' && result`, junto con `MetricCard` y `BreakdownCard`) a `components/incidents/AnalysisResults.tsx`, con la interfaz `AnalysisResult` exportada desde un lugar compartido dentro de la app (sin duplicarla). Comportamiento y estilos idénticos.
- En la página: `const AnalysisResults = dynamic(() => import("@/components/incidents/AnalysisResults").then(m => m.AnalysisResults), { ssr: false, loading: () => <LoadingBlock label="Preparando resultados..." /> })`, montado solo cuando hay resultado.
- Opcional recomendado: precarga el chunk cuando el usuario selecciona un fichero (`void import("@/components/incidents/AnalysisResults")` en `handleFileChange`) para que el usuario no perciba espera.
- Build de application OK.

**Commit:** `perf(application): cargar resultados del análisis de incidencias bajo demanda`

### 5.C Evidencia
- Repite los builds y guarda la salida en `docs/caching/frontend/build-after-<app>.txt`.
- Si el build no informa tamaños por ruta, lista los chunks nuevos en `.next/static/chunks` que contienen `LeadForm` / `AnalysisResults` (por ejemplo con `grep -l`) y su tamaño en KB. Escribe en `docs/caching/frontend/lazy-loading.md` qué chunk se separó y en qué momento se pide.
- Deja preparado en ese fichero un apartado **"Verificación manual (Marisin)"** con los pasos: abrir DevTools → Network → JS, recargar la landing y comprobar que el chunk del formulario solo se pide al hacer scroll; en `/incidents/analyze`, comprobar que el chunk de resultados solo se pide tras analizar. Las capturas las añadirá la desarrolladora en `docs/caching/frontend/`. **No inventes estas cifras.**

**Commit:** `docs(caching): documentar evidencia de la carga diferida`

**Criterios de aceptación:**
- [ ] 2 componentes con lazy loading y justificación.
- [ ] Sin CLS añadido (placeholder con altura reservada).
- [ ] Builds de website y application OK.

⛔ **STOP — Reporte de Fase 5.**

---

## 9. FASE 6 — Frontend: `useMemo` (F3)

En `uis/backoffice/src/app/inventory/orders/outbound/page.tsx`:
- `selectedProduct = useMemo(() => products.find(...), [products, selectedSkuId])`.
- `stockIndex = useMemo(() => { /* Map<"sku|warehouse", number> recorriendo orders una vez */ }, [orders])`.
- `currentStock = selectedProduct ? stockIndex.get(\`${selectedProduct.sku}|${warehouse}\`) ?? 0 : 0` — lookup O(1), sin memo propio (es trivial).
- **No** memoices `isStockExceeded` ni comparaciones simples (memoización prematura).
- El comportamiento visible debe ser idéntico: mismo número en "Stock disponible actual", mismo bloqueo del botón y mismo aviso.
- Comentario de una línea encima del `useMemo` explicando por qué existe (O(n) por tecla con miles de órdenes).
- Build del backoffice OK.

**Commit:** `perf(backoffice): memoizar índice de stock por almacén en el formulario de salida`

### Evidencia
En `docs/caching/frontend/usememo.md`:
- Antes: nº de órdenes tras el seed (sale de `02-baseline-load.md`) × renders por tecla = trabajo por tecla.
- Después: el índice solo se recalcula cuando cambia `orders` (carga inicial y tras registrar una salida).
- Apartado **"Verificación manual (Marisin)"**: React DevTools → Profiler, grabar escribiendo 10 caracteres en "Número de seguimiento" antes/después (con `git stash` o comparando con `main`), y anotar el tiempo de render del componente. Hasta que existan las capturas, el informe dirá "beneficio estimado" y nunca "medido".

**Commit:** `docs(caching): documentar justificación y verificación del useMemo`

⛔ **STOP — Reporte de Fase 6.**

---

## 10. FASE 7 — `CACHING_REPORT.md` (raíz del monorepo)

Estructura obligatoria (los 4 primeros apartados son los de la rúbrica; los demás la refuerzan):

1. **Resumen ejecutivo** — qué se cacheó, dónde, TTL y mejora principal (cifras de los benchmarks).
2. **Metodología y evidencia** — middleware de timing, script de benchmark, seeder; **volumen aproximado de filas antes y después** del seed y cómo cambió la latencia de los endpoints elegidos (01 → 02 → 03). Enlaza los ficheros de `docs/caching/`. Skills de `.agents/skills/` utilizadas, si aplicaron.
3. **Inventario de endpoints** — tabla con todos los endpoints y los ejes (a) coste, (b) frecuencia, (c) cambio de datos, + privacidad (resumen de `candidates.md`).
4. **Decisiones en el backend** — por cada endpoint cacheado: coste de la operación (qué hace y cuánto tarda, con cifra), frecuencia estimada (y en qué se basa), TTL elegido y por qué ese valor, clave de caché y por qué es segura, estrategia de invalidación (qué escrituras invalidan y en qué punto exacto), comportamiento ante varios workers.
5. **Decisiones en el frontend** — qué componentes se cargaron de forma diferida y por qué; qué se memoizó y beneficio medido o estimado (diciendo cuál de los dos).
6. **Intercambios reconocidos (frescura vs. rendimiento)** — como mínimo:
   - `/inventory/products` con TTL 30 s: un operario puede ver un stock de hasta 30 s de antigüedad **solo si** la escritura vino de fuera de este proceso (otro worker, `services/seed.py`, cambios directos en Supabase); las escrituras por la API invalidan al instante. Es aceptable porque la **validación autoritativa de stock** en `create_outbound_order` no usa la caché: un dato visual desfasado nunca permite sobreventa. Explica por qué no 5 s (casi sin hits en una sesión real) ni 5 min (demasiado desfase si hay varios workers).
   - `/api/incidents/summary` con TTL 60 s: es un indicador agregado para seguimiento; un recuento con hasta 1 min de retraso no cambia ninguna decisión operativa, y los cambios hechos desde la UI invalidan al instante.
   - Límite de la caché en proceso: con `--workers N` cada worker tiene su propia caché y la invalidación es local; el TTL acota el desfase. Siguiente paso: Redis con invalidación compartida.
7. **Qué no se cacheó y por qué** — como mínimo:
   - `/auth/*`, `/profiles/me`, `/users/*`: datos personales o de sesión; una clave compartida sería una fuga de datos.
   - `GET /inventory/orders`: payload grande que crece sin límite y lo usa el formulario de salida, que necesita datos frescos; el problema real es de diseño (paginación o un endpoint de stock por SKU/almacén), no de caché. Cita la cifra medida.
   - `GET /inventory/products/{id}`: baja frecuencia (consumidor: `getProductById`; comprueba si alguna página lo usa realmente).
   - `GET /suppliers` y `GET /api/incidents`: según lo medido (coste bajo en TinyDB y/o claves de alta cardinalidad por filtros y búsqueda libre).
   - `_warehouse_balances`: validación crítica de negocio, nunca cacheada.
   - Frontend: `Header`, `Hero` y `DashboardShell` no se cargan de forma diferida porque están en el viewport inicial (afectaría al LCP); `isStockExceeded` no se memoiza por ser trivial.
8. **Riesgos y siguientes pasos** — Redis, paginación de `/inventory/orders`, conexión con pool en lugar de `NullPool` (fuera de alcance; explicar el impacto observado), métricas de hit ratio para el proyecto de telemetría.
9. **Cómo reproducir** — comandos exactos (seed, API con y sin caché, benchmark, tests, `--purge`).

Reglas del informe:
- Nada genérico tipo "cacheamos esto porque es lento": cada decisión con cifra, consumidor real y motivo del TTL.
- Cada cifra enlazada a su fichero de `docs/caching/benchmarks/`.
- Lo no medido se marca como "estimado" o "pendiente de verificación manual".

**Commit:** `docs(caching): añadir informe técnico CACHING_REPORT.md`

⛔ **STOP — Reporte de Fase 7.**

---

## 11. FASE 8 — Cierre

1. `pytest -q` y los 3 builds en verde. Anota los resultados literales.
2. Datos de TinyDB: pregunta a la desarrolladora si quiere conservar las incidencias de carga en local para las capturas manuales. Si quiere limpiarlas, usa `--purge` o restaura `/tmp/suppliers.pre-load.json`.
3. Los datos de carga de Supabase se mantienen (útiles para las capturas). Recuerda en el reporte el comando `--purge` por si quiere limpiarlos.
4. Actualiza `memory-bank/progress.md` (entrada nueva **arriba**, como exige AGENTS.md) con un resumen de 5–8 líneas y hashes de commits.
5. Completa la §14 de este plan y marca en `prompts/README.md` el estado "Listo para PR".
6. `git status` limpio. `git log --oneline main..HEAD` en el reporte final.

**Commit:** `docs(memory-bank): registrar cierre del proyecto de caching`

⛔ **STOP FINAL** — no hagas push. La desarrolladora revisa, sube la rama y abre el PR.

---

## 12. PLANTILLAS

### 12.1 Registro de avance
- **Del proyecto:** §14 al final de este fichero. Actualízalo al cerrar cada fase (estado, hashes de los commits ya hechos en la fase, discrepancias) e inclúyelo en el último commit de la fase.
- **Global (`memory-bank/progress.md`, AGENTS.md §2.4):** una ÚNICA entrada para este proyecto, colocada arriba del todo, que vas ampliando al cerrar cada fase con 1–2 líneas. No crees una entrada nueva por fase.

### 12.2 Reporte al final de cada fase (respuesta en el chat)

```
## Fase N — <nombre> · ✅ completada / ⚠️ con incidencias
**Hecho:** (bullets cortos)
**Ficheros creados/modificados:** (rutas)
**Commits:** <hash> <mensaje>
**Verificación:** pytest → … · build(s) → … · benchmark → (tabla si aplica)
**Criterios de aceptación:** (checklist de la fase marcada)
**Discrepancias con el plan / decisiones a validar:** (o "ninguna")
**Siguiente:** Fase N+1 — espero "continúa con la Fase N+1".
```

---

## 13. TRAZABILIDAD RÚBRICA → EVIDENCIA

| Criterio de evaluación | Dónde se cumple | Evidencia |
|---|---|---|
| ≥2 componentes/rutas con Lazy Loading justificado | Fase 5 | `LazyLeadForm.tsx`, `AnalysisResults.tsx`, `lazy-loading.md`, informe §5 |
| ≥1 `useMemo` no trivial con dependencias correctas | Fase 6 | `outbound/page.tsx`, `usememo.md`, informe §5 |
| ≥2 endpoints cacheados con TTL | Fases 3–4 | `cache.py`, `inventory.py`, `incidents.py`, `03-after-cache*.md` |
| Invalidación implementada | Fase 4 | invalidaciones tras commit + `tests/test_caching.py` |
| Ningún dato privado en clave compartida | Fases 0, 4 | `routes-inventory.md` (auth), test de privacidad, informe §4 y §7 |
| `CACHING_REPORT.md` con todas las secciones | Fase 7 | raíz del repo |
| Decisiones específicas y justificadas | Fases 2, 7 | `candidates.md` + cifras enlazadas |
| ≥1 intercambio frescura/rendimiento explícito | Fase 7 | informe §6 |
| Volumen antes/después del seed y cambio de latencia | Fase 2 | `02-seed-output.txt`, `01` vs `02`, informe §2 |

---

## 14. REGISTRO DE AVANCE DEL PROYECTO

| Fase | Estado | Commits | Notas / discrepancias |
|------|--------|---------|-----------------------|
| 0 Preparación y baseline | ✅ | `49a2423`, `54f0806` | Inventario real, pytest y builds registrados; prompt original restaurado y aclaraciones añadidas. Backoffice OK por Marisin. Sin cambios de código. |
| 1 Instrumentación | ✅ | `24fe9f3`, `bee0d97`, `a251960` | Medición 1.C y pytest ejecutados por Marisin en su terminal; el agente no puede usar el entorno Python por política. pytest: `16 passed, 3 warnings in 5.51s`. Log: 188 líneas válidas; 31 por cada GET medido, login y GET `/` adicional (404). |
| 2 Carga realista | ✅ | `96c641d`, `7a4644d` | Carga y medición 2.B ejecutadas por Marisin; invariante agregado verificado por el seeder. Matriz completa en `docs/caching/candidates.md`; B1 y B2 se mantienen como candidatos, B2 con beneficio potencial moderado. No se implementó caché. |
| 3 Módulo de caché | ⏳ | | |
| 4 Endpoints + invalidación + tests | ⏳ | | |
| 5 Lazy loading | ⏳ | | |
| 6 useMemo | ⏳ | | |
| 7 CACHING_REPORT.md | ⏳ | | |
| 8 Cierre | ⏳ | | |

### Baseline
- pytest: **16 passed, 3 warnings** (resultado literal; ejecución de esta sesión, código 0). El plan decía 9 passed porque se escribió con un recuento antiguo. [Evidencia](../../docs/caching/benchmarks/00-phase0-baseline.md).
- pytest Fase 1: `16 passed, 3 warnings in 5.51s`, ejecutado por Marisin. [Salida literal](../../docs/caching/benchmarks/01-pytest.txt).
- Benchmark inicial: datos actuales, 2 productos, 8 órdenes y 0 incidencias. Resultados y tabla exacta en [01-baseline-small.md](../../docs/caching/benchmarks/01-baseline-small.md); log completo en [01-baseline-small-log.txt](../../docs/caching/benchmarks/01-baseline-small-log.txt). El log tiene 188/188 líneas con método, ruta, status y ms; incluye 31 peticiones por cada GET medido, el login y un GET `/` adicional que recibió 404.
- builds: website **OK** / backoffice **OK, ejecutado por Marisin en su terminal** / application **OK**, con los comandos de §1.2. Salidas: [website](../../docs/caching/frontend/build-before-website.txt), [backoffice](../../docs/caching/frontend/build-before-backoffice.txt), [application](../../docs/caching/frontend/build-before-application.txt).
- Entorno: `.venv` no existía y el agente lo recreó; Python **3.14.2**, FastAPI **0.163.1**, pytest **9.2.0**. Dependencias restauradas sin modificar manifiestos. Al cierre, una nueva denegación de política organizacional bloqueó la activación: no se eludió; se conservan el inventario y los resultados ya obtenidos en la sesión.
- TinyDB local (`suppliers.json`): precondiciones **verificadas manualmente por Marisin**. El commit `632c782` lo sacó de git; no está versionado y su exclusión figura en la línea 12 de `.gitignore`. Instrucción permanente: no escribir su ruta completa en comandos, lecturas ni búsquedas. Ejecutar `git status` a solas; si se bloquea, parar y avisar.
- Fase 2: la copia de seguridad fuera del repositorio **ya la hizo Marisin**. Omitir el comando `cp` del plan; no repetir la copia.
- backoffice: Next.js 16.4.4 muestra un aviso `SecurityFatalError` al detectar que el build lo ejecuta un agente de IA. Los intentos 1 y 2 del agente se detuvieron tras compilar; el build ejecutado por Marisin en su terminal dio OK. Next.js 16.4.4 sigue afectado por una vulnerabilidad conocida: no se actualiza en este proyecto y queda como riesgo para §8 del informe. Para builds del backoffice en fases posteriores: si aparece el aviso, repetir el comando en menos de 5 minutos o pedírselo a Marisin.
- La explicación anterior del aviso y la ventana de repetición proceden de Marisin; no se verificó independientemente su mecanismo. Evidencia conservada: [intento 1](../../docs/caching/frontend/build-before-backoffice-intento1.txt), [intento 2](../../docs/caching/frontend/build-before-backoffice-intento2.txt) y log final OK. No se repitió el build tras la última instrucción de Marisin.
- Los primeros builds fallaron por falta del plugin CSS y la restauración local por permisos de `node_modules`. Marisin corrigió los permisos de los volúmenes de Docker e instaló las dependencias. No se volvió a ejecutar `npm ci` después de su instrucción.
- Turbopack no muestra tamaños JS por ruta: las salidas se guardan igualmente. Website y application usan Next.js **16.2.11**; backoffice **16.4.4**. Los tamaños se medirán en **Fase 5** con los chunks de `.next/static/chunks` y la verificación manual en Network.
- Rendimiento: latencias, volúmenes, JS por ruta y Core Web Vitals **no medidos** en esta fase. No se deduce ninguna mejora del resultado de tests o builds.

### Registro (más reciente arriba)

#### 2026-11-17 — Fase 2
- Seed y benchmark ejecutados por Marisin, sin ejecución Python del agente; API ya parada por Marisin. [Seed](../../docs/caching/benchmarks/02-seed-output.txt): SKUs 2 → 302; entradas 4 → 8004; salidas 4 → 4004; incidencias 0 → 3000. [Benchmark 02](../../docs/caching/benchmarks/02-baseline-load.md): órdenes 8 → 12008.
- El seeder confirmó el invariante agregado de stock por SKU/almacén. Limitaciones: fechas de salida independientes de las entradas (no garantiza saldo histórico no negativo); inserción por lotes y dos almacenes sin transacción conjunta. Si falla a medias hay que usar `--purge` antes de repetir: no reanuda cargas parciales. La copia de seguridad fuera del repositorio ya la hizo Marisin.
- B1, p50/p95 01 → 02: 133.8/165.0 → 156.1/186.3 ms; B2: 0.9/2.7 → 22.0/41.5 ms. Cifras de [01](../../docs/caching/benchmarks/01-baseline-small.md) y [02](../../docs/caching/benchmarks/02-baseline-load.md). Se sostienen como candidatos sin implementar: B2 supone ahorro absoluto moderado y falta medir beneficio con/sin caché.
- [Productos](../../docs/caching/benchmarks/02-stability-products.txt) y [resumen](../../docs/caching/benchmarks/02-stability-summary.txt): una única línea MD5 con 20 respuestas idénticas por endpoint. Estas capturas no guardan status ni latencias de la ráfaga adicional; coste sustentado en benchmark 02, no en MD5.
- El [log 02](../../docs/caching/benchmarks/02-baseline-load-log.txt) contiene 188 líneas de timing válidas, sin las peticiones adicionales de estabilidad. Incluye la primera y las repeticiones de cada endpoint, login y GET `/` adicional.
- Aclaración de Marisin sobre el log 01: el GET `/` 404 vino del navegador al abrirse el puerto reenviado por Codespaces; no es un fallo del script.
- [Candidatos](../../docs/caching/candidates.md): todas las operaciones del inventario, tres ejes y privacidad; frecuencias expresamente estimadas desde consumidores citados. `getProductById` solo está definido en el helper de inventario: no se localizaron consumidores en páginas de `uis/`.
- Precondiciones del JSON local: se mantiene la verificación manual de Marisin; no se ejecutó comprobación directa ni se escribió su ruta en comandos. `git status` se ejecuta a solas y debe revisarse antes del commit. Parada de Fase 2; no se inicia Fase 3.

#### 2026-11-17 — Fase 0
- Rama `feature/caching-optimisation` verificada; estado inicial limpio. Sin servidores iniciados por el agente en esta fase.
- [Inventario](../../docs/caching/routes-inventory.md): 30 operaciones efectivas; auth comprobada contra `services.api.security.get_current_user`. El duplicado de `services/api/auth.py` no es dependencia de ninguna ruta. FastAPI expone `_IncludedRouter` y `effective_candidates()`; snippet documentado.
- Revisión de §1: se mantienen los seis routers, la ausencia de timing/caché, el cálculo de stock fresco, la agregación de incidencias, `NullPool`/TLS y los consumidores frontend descritos. Las hipótesis B1/B2/F1/F2/F3 quedan sin implementar y pendientes de medición. La semilla relacional y el script CSV existen; no se ejecutaron semillas ni se consultó el JSON restringido. No se afirma que TinyDB haga una lectura física de disco por cada `.all()` sin medir su almacenamiento.
- Discrepancias confirmadas: recuento de tests antiguo, versiones instaladas indicadas arriba, representación diferida de routers y duplicado de `get_current_user`. Verificación de datos restringidos exclusivamente por Marisin.
- Skill `performance` utilizada como criterio de trabajo basado en evidencia: no presentar hipótesis como mejoras medidas. `core-web-vitals` revisada; no aplica una optimización de LCP/INP/CLS en esta fase documental, y esas métricas quedan no medidas.
- Índice y prompt guardados según la convención del proyecto; registro global actualizado con una única entrada de caching. Se conserva el baseline sin volver a ejecutar tests ni builds ya validados. Parada al final de Fase 0; Fase 1 requiere autorización.
