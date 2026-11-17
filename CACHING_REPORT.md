# TrackFlow — Informe técnico de caching

Estado: informe de Fase 7; la verificación final de Fase 8 sigue pendiente. Fuente de alcance y avance: [plan del proyecto](memory-bank/history/2026-11-16_caching-optimisation.md).

## 1. Resumen ejecutivo

Se implementaron dos cachés TTL en memoria para respuestas globales, dos componentes con carga diferida y una memoización del stock visual del formulario de salida.

| Decisión | Implementación | Resultado |
|---|---|---|
| B1: listado de productos | Clave global, TTL **30 s**, invalidación tras escrituras de inventario | p50/p95: **155.6 / 189.9 ms** sin caché → **5.6 / 12.9 ms** en HIT |
| B2: resumen de incidencias | Clave global, TTL **60 s**, invalidación tras altas y cambios de estado | p50/p95: **18.0 / 33.0 ms** sin caché → **0.7 / 2.1 ms** en HIT |
| F1: formulario comercial | `next/dynamic` y montaje al aproximarse al viewport o navegar a `#contacto` | Chunk fuera de las solicitudes iniciales de la landing, según capturas de Marisin |
| F2: resultados del análisis | `next/dynamic`, montado solo tras análisis correcto | Chunk solicitado al mostrar resultados, según evidencia de Marisin |
| F3: stock por SKU/almacén | Índice memoizado con `[orders]` y lookup directo | Evita recorrer el historial en cada edición; beneficio de interacción **estimado**, no medido |

Fuentes de latencia: [03 BYPASS](docs/caching/benchmarks/03-after-cache-bypass.md) y [03 caché](docs/caching/benchmarks/03-after-cache.md). Son tiempos del middleware, no latencia de red ni duración de interacción. Productos y órdenes tienen el mismo volumen entre ambos procesos; BYPASS incluye una incidencia adicional creada al probar invalidación. La comparación del resumen no es exactamente al mismo volumen.

Implementación de TTL y claves: [cache.py](services/api/cache.py). Evidencia frontend: [lazy loading](docs/caching/frontend/lazy-loading.md) y [useMemo](docs/caching/frontend/usememo.md). **CLS no medido**; no se certifica ausencia de desplazamientos. No se cachearon respuestas personales, sesiones ni la validación autoritativa del stock.

## 2. Metodología y evidencia

### Instrumentación y condiciones

- [Middleware HTTP](services/api/main.py): usa `time.perf_counter()`, escribe método, ruta con query string, status y duración en el logger `api.timing`, y añade `X-Response-Time-ms`. Su configuración está aislada del logging global.
- [Benchmark](scripts/perf/bench_endpoints.py): cliente `httpx`, primera petición separada y **30 repeticiones** posteriores por endpoint, según las cabeceras de los [benchmarks 01](docs/caching/benchmarks/01-baseline-small.md), [02](docs/caching/benchmarks/02-baseline-load.md) y [03](docs/caching/benchmarks/03-after-cache.md). Calcula percentiles por rango más próximo sobre las repeticiones. Mide seis GET; el login necesario para proveedores no es un benchmark de autenticación.
- El tamaño etiquetado «KB» por el script es `len(response.content) / 1024`: bytes del cuerpo recibido/decodificado, no transferencia comprimida ni peso de una página.
- [Seeder](scripts/perf/seed_load.py): carga sintética reproducible en su generación aleatoria, referencias `LOAD-` y títulos `[LOAD]`; las fechas se anclan al momento de ejecución. Separa PostgreSQL de TinyDB, inserta por lotes y comprueba el stock agregado por SKU/almacén.
- Ejecuciones locales contra `http://127.0.0.1:8000`, con peticiones secuenciales; fechas, volúmenes y resultados completos constan en cada benchmark. Marisin ejecutó carga y mediciones de backend de las fases correspondientes; no se repitieron en Fase 7.
- Skill `performance` utilizada para separar evidencia, hipótesis y beneficio estimado. No hay telemetría de tráfico, perfilado SQL/TLS/TinyDB, pruebas de carga concurrente ni datos de campo de Core Web Vitals.

### Volumen antes y después

| Magnitud | Inicial | Tras carga | Fuente |
|---|---:|---:|---|
| SKUs | 2 | 302 | [Seed](docs/caching/benchmarks/02-seed-output.txt) |
| Entradas | 4 | 8004 | [Seed](docs/caching/benchmarks/02-seed-output.txt) |
| Salidas | 4 | 4004 | [Seed](docs/caching/benchmarks/02-seed-output.txt) |
| Órdenes totales | 8 | 12008 | [01](docs/caching/benchmarks/01-baseline-small.md), [02](docs/caching/benchmarks/02-baseline-load.md) |
| Incidencias | 0 | 3000 | [Seed](docs/caching/benchmarks/02-seed-output.txt) |

El invariante verificado por el seeder compara sumas finales; no demuestra saldo histórico no negativo en la fecha de cada salida. La carga no es una transacción conjunta entre almacenes de datos. Si queda incompleta, la idempotencia impide duplicar, pero no reanuda: hay que decidir una limpieza antes de repetir. La copia de seguridad previa ya la hizo Marisin; no se repitió.

### Evolución de latencia

Valores **p50 / p95 en ms**, copiados de las fuentes de cada columna:

| Endpoint | [01, volumen inicial](docs/caching/benchmarks/01-baseline-small.md) | [02, carga sin caché](docs/caching/benchmarks/02-baseline-load.md) | [03, HIT](docs/caching/benchmarks/03-after-cache.md) | [03, BYPASS](docs/caching/benchmarks/03-after-cache-bypass.md) |
|---|---:|---:|---:|---:|
| `/inventory/products` | 133.8 / 165.0 | 156.1 / 186.3 | 5.6 / 12.9 | 155.6 / 189.9 |
| `/api/incidents/summary` | 0.9 / 2.7 | 22.0 / 41.5 | 0.7 / 2.1 | 18.0 / 33.0 |
| `/inventory/orders`, control no cacheado | 129.0 / 134.5 | 416.4 / 459.5 | 416.9 / 589.9 | 418.2 / 465.4 |

La columna «03, HIT» describe los candidatos cacheados; el control no usa caché. Su variación p95 no se atribuye al cambio. La comparación principal es 03 contra BYPASS, no 01 contra 03: 01 tiene otro volumen.

En [03](docs/caching/benchmarks/03-after-cache.md), la primera petición fue MISS: productos **334.4 ms**, resumen **27.0 ms**. Después hubo **30 HIT** por candidato. En [BYPASS](docs/caching/benchmarks/03-after-cache-bypass.md), hubo **30 BYPASS** por candidato. Un HIT no elimina el coste de serialización ni garantiza acelerar una petición fría. Estos recuentos de una ráfaga no representan un hit ratio de producción.

La comparación de incidencias tiene **3000 registros con caché y 3001 en BYPASS**, según [03](docs/caching/benchmarks/03-after-cache.md) y [BYPASS](docs/caching/benchmarks/03-after-cache-bypass.md). La diferencia corresponde al POST de prueba documentado en la [evidencia de invalidación](docs/caching/benchmarks/03-invalidation-evidence.txt); debe considerarse al interpretar B2.

### Estabilidad y corrección

- Las capturas de [productos](docs/caching/benchmarks/02-stability-products.txt) y [resumen](docs/caching/benchmarks/02-stability-summary.txt), contextualizadas en [candidates.md](docs/caching/candidates.md), registran respuestas idénticas en la ráfaga sin escrituras. No contienen status ni latencias de esa ráfaga; no sustituyen el benchmark.
- La [evidencia HTTP de invalidación](docs/caching/benchmarks/03-invalidation-evidence.txt) muestra HIT antes del alta, POST exitoso, MISS después y HIT posterior. El [log de timing](docs/caching/benchmarks/03-after-cache-log.txt) no registra `X-Cache`; no es la fuente de esas cabeceras.
- [Tests de caching](tests/test_caching.py): TTL con reloj falso, expulsión, invalidación, métricas, aislamiento con TinyDB en memoria y SQLite, BYPASS, escrituras y lectores globales sin JWT. La validación de salida consulta saldo fresco incluso con listado cacheado.
- Baseline: **16 passed, 3 warnings**, según [Fase 0](docs/caching/benchmarks/00-phase0-baseline.md). Tras integrar caché: **34 passed, 6 warnings in 5.35s**, según [salida de Marisin](docs/caching/benchmarks/03-pytest.txt). No se repitieron tests para redactar este informe; el cierre final sigue pendiente.

## 3. Inventario de endpoints

La [introspección de rutas](docs/caching/routes-inventory.md) identifica **30 operaciones HTTP**. La siguiente tabla las cubre todas; las rutas de documentación no son operaciones de negocio. La [matriz original](docs/caching/candidates.md) conserva el análisis previo a implementar.

**Coste:** p50/p95 en ms del [benchmark 02](docs/caching/benchmarks/02-baseline-load.md). «No medido» no equivale a coste nulo. **Frecuencia:** estimación estática basada en consumidores, nunca telemetría real. «Sin consumidor localizado» no significa que nadie invoque esa ruta. Las cadencias de escritura reales no se han medido.

Consumidores citados en la tabla:

- **INV:** [helpers](uis/backoffice/src/lib/inventory.ts), `getProducts`, `getOrders`, `getProductById`, `createInboundOrder`, `createOutboundOrder`; [productos](uis/backoffice/src/app/inventory/products/page.tsx) e [historial](uis/backoffice/src/app/inventory/orders/page.tsx) usan [useInventoryData](uis/backoffice/src/hooks/useInventoryData.ts), sin polling.
- **ENT/SAL:** [entrada](uis/backoffice/src/app/inventory/orders/inbound/page.tsx), `InboundOrderPage`, y [salida](uis/backoffice/src/app/inventory/orders/outbound/page.tsx), `OutboundOrderPage`: carga en efecto; escritura en `handleSubmit`; salida recarga el historial tras guardar.
- **SES:** [layout de inventario](uis/backoffice/src/app/inventory/layout.tsx), comprobación de sesión; [login application](uis/application/app/login/page.tsx), [login backoffice](uis/backoffice/src/app/login/page.tsx) y [registro](uis/application/app/register/page.tsx), envío del formulario.
- **PER:** [ProfilePage](uis/application/app/account/profile/page.tsx), `loadProfile` y `handleSubmit`; **PWD:** formularios de [recuperación](uis/application/app/forgot-password/page.tsx), [restablecimiento](uis/application/app/reset-password/page.tsx) y [cambio](uis/application/app/account/change-password/page.tsx), vía [authApi](uis/application/lib/api.ts).
- **PROV:** [SuppliersPage](uis/application/app/suppliers/page.tsx), `loadSuppliers`, al montar.
- **INC:** [IncidentWorkspace](uis/application/components/incidents/IncidentWorkspace.tsx), `loadIncidents`, `loadSummary` y `changeStatus`, vía [helpers de incidencias](uis/application/lib/incidents.ts). **ALTA:** [IncidentForm](uis/application/components/incidents/IncidentForm.tsx), `handleSubmit`.

| Operación | Coste p50/p95 | Frecuencia estimada / consumidor | Cuándo cambia el dato | Privacidad | Decisión final |
|---|---|---|---|---|---|
| GET `/suppliers` | 18.5 / 28.0 | PROV, al montar | Escrituras del proveedor | JWT, directorio comercial | NO: autenticada |
| GET `/suppliers/{supplier_id}` | No medido | Sin consumidor localizado | Escrituras del proveedor | JWT | NO: autenticada |
| POST `/suppliers` | No medido | Sin consumidor localizado | Cada alta | JWT | NO: mutación |
| PATCH `/suppliers/{supplier_id}/rate` | No medido | Sin consumidor localizado | Cada tarifa guardada | JWT | NO: mutación |
| PATCH `/suppliers/{supplier_id}/status` | No medido | Sin consumidor localizado | Cada estado guardado | JWT | NO: mutación |
| DELETE `/suppliers/{supplier_id}` | No medido | Sin consumidor localizado | Cada baja | JWT | NO: mutación |
| POST `/users` | No medido | SES, registro | Cada cuenta creada | Credenciales; sin JWT | NO: personal y mutación |
| GET `/users` | No medido | Sin consumidor localizado | Altas, ediciones, bajas | JWT, cuentas | NO: personal |
| GET `/users/{user_id}` | No medido | Sin consumidor localizado | Cambios de cuenta | JWT, cuenta | NO: personal |
| PUT `/users/{user_id}` | No medido | Sin consumidor localizado | Cada edición | JWT, cuenta | NO: mutación personal |
| DELETE `/users/{user_id}` | No medido | Sin consumidor localizado | Cada baja | JWT, cuenta | NO: mutación personal |
| POST `/auth/login` | No medido | SES, envío o tras registro | Tokens y sesión | Credenciales y tokens | NO: autenticación |
| GET `/auth/me` | No medido | SES/PER, al montar | Cuenta, perfil y sesión | JWT, usuario actual | NO: personal |
| POST `/auth/forgot-password` | No medido | PWD, envío | Solicitud de recuperación | Identidad y tokens | NO: operación sensible |
| POST `/auth/reset-password` | No medido | PWD, envío | Contraseña y consumo del token | Secreto y token | NO: mutación sensible |
| POST `/auth/change-password` | No medido | PWD, envío | Contraseña | JWT y credenciales | NO: mutación sensible |
| GET `/profiles/me` | No medido | Sin GET directo; PER usa `/auth/me` | Edición del perfil | JWT, perfil actual | NO: personal |
| PUT `/profiles/me` | No medido | PER, `handleSubmit` | Cada guardado | JWT, contacto personal | NO: mutación personal |
| GET `/profiles/{profile_id}` | No medido | Sin consumidor localizado | Edición del perfil | JWT, contacto personal | NO: personal |
| GET `/inventory/products` | 156.1 / 186.3 | INV → productos/ENT/SAL, al montar o cambiar SKU inicial en formularios | Alta de producto, entradas, salidas, escrituras externas | Sin JWT; listado global sin identidad de usuario | SÍ B1: TTL e invalidación |
| POST `/inventory/products` | No medido | Sin formulario/helper de alta localizado | Cada alta | JWT | NO: mutación; invalida B1 |
| GET `/inventory/products/{product_id}` | 132.3 / 140.7, solo ID 2 | INV define helper, sin llamadas localizadas | Producto y movimientos | Sin JWT; dato operativo | NO: demanda no localizada |
| POST `/inventory/orders/inbound` | No medido | ENT, envío | Cada entrada | JWT, atribución de usuario | NO: mutación; invalida B1 |
| POST `/inventory/orders/outbound` | No medido | SAL, envío | Cada salida | JWT, atribución de usuario | NO: mutación; valida stock fresco e invalida B1 |
| GET `/inventory/orders` | 416.4 / 459.5 | INV → historial y SAL; SAL recarga tras salida | Entradas y salidas | Sin JWT, pero incluye `user_uuid` e historial | NO: frescura, datos operativos y payload creciente |
| POST `/api/incidents` | No medido | ALTA, envío | Cada alta | Sin JWT; texto libre potencialmente sensible | NO: mutación; invalida B2 |
| GET `/api/incidents` | 25.8 / 44.1, sin filtros | INC, montaje/filtros/reintento | Altas y cambios de estado | Sin JWT; texto libre | NO: sensibilidad y variantes por filtros |
| GET `/api/incidents/summary` | 22.0 / 41.5 | INC, montaje/reintento/tras cambio de estado | Altas, estados, escrituras externas | Sin JWT; recuentos sin detalles individuales | SÍ B2: TTL e invalidación |
| GET `/api/incidents/{incident_id}` | No medido | Sin consumidor localizado | Estado de la incidencia | Sin JWT; texto libre | NO: sensibilidad y demanda no localizada |
| PATCH `/api/incidents/{incident_id}/status` | No medido | INC, acción del operador | Cada transición válida | Sin JWT; mutación de incidencia | NO: mutación; invalida B2 |

No exigir JWT no convierte un recurso en público. Las rutas que leen caché son exclusivamente los dos agregados globales; las rutas autenticadas de inventario solo invalidan, nunca almacenan su respuesta privada.

## 4. Decisiones en el backend

### Mecanismo común

[TTLCache](services/api/cache.py) usa reloj monotónico y bloqueo para sus operaciones internas. Todas las entradas expiran; rechaza TTL no finito o no positivo, elimina expiradas y expulsa la inserción más antigua al agotar capacidad. Expone invalidación por clave/prefijo, limpieza y estadísticas de hits, misses, invalidaciones explícitas y tamaño. No importa rutas ni sesiones.

`TRACKFLOW_CACHE_ENABLED=0` desactiva las lecturas/escrituras de caché y responde `X-Cache: BYPASS`; activo devuelve HIT o MISS. Se lee al importar: hay que reiniciar el proceso al cambiarlo. No se modificaron variables persistentes, contratos de respuesta ni configuración de infraestructura.

### B1 — Listado de productos

- **Operación:** [list_products](services/api/routes/inventory.py) consulta SKUs y agrega entradas/salidas por almacén con `_warehouse_balances`; suma el stock por SKU. Con carga, coste sin caché **156.1 / 186.3 ms** p50/p95 en [02](docs/caching/benchmarks/02-baseline-load.md).
- **Reutilización prevista:** `getProducts` sirve a listado, entrada y salida. Se pide al entrar en esos flujos; frecuencia real y hit ratio no medidos.
- **Clave:** `inventory:products:list`, TTL **30 s**, definidos en [cache.py](services/api/cache.py). El endpoint no depende de `get_current_user` y devuelve el mismo listado global sin campos de identidad del operador. No implica anonimizar los datos comerciales ni cambiar el control de acceso.
- **HIT:** copia superficial de la lista (`list(cached)`); no consulta los agregados SQL del listado. **MISS:** ejecuta el cálculo existente y almacena el resultado con TTL explícito. No se afirma copia profunda ni eliminación de toda sobrecarga de la dependencia de sesión.
- **Invalidación:** `create_product`, `create_inbound_order` y `create_outbound_order` llaman a `invalidate` inmediatamente después del `session.commit()` exitoso, antes del `refresh`. Errores anteriores al commit no invalidan.
- **Resultado:** [03 caché](docs/caching/benchmarks/03-after-cache.md) frente a [BYPASS](docs/caching/benchmarks/03-after-cache-bypass.md), a igual volumen de productos/órdenes: **5.6 / 12.9 ms** frente a **155.6 / 189.9 ms** p50/p95.

### B2 — Resumen de incidencias

- **Operación:** [summary](services/api/services/incidents.py) recorre las incidencias y agrega estado, categoría, origen y sede. El tiempo sin caché creció de **0.9 / 2.7 ms** en [01](docs/caching/benchmarks/01-baseline-small.md) a **22.0 / 41.5 ms** en [02](docs/caching/benchmarks/02-baseline-load.md). No se asume una lectura física de disco por cada `.all()` sin perfilar el almacenamiento de TinyDB.
- **Reutilización prevista:** `IncidentWorkspace.loadSummary` al montar, reintentar y después de un cambio de estado correcto. Son consumidores estáticos, no tráfico observado.
- **Límite del flujo de un operador:** en la secuencia `changeStatus` correcto → `loadSummary`, sin otra lectura intercalada, esta llamada será siempre MISS: el PATCH acaba de invalidar la clave. Los HIT se esperan al montar o reintentar si la clave sigue válida, y entre varios operadores o pestañas dentro del TTL; una lectura concurrente también podría rellenar la clave antes de ese `loadSummary`. Por ello, el beneficio del flujo de un solo operador es menor que el sugerido por las **30 repeticiones** consecutivas sin escrituras del [benchmark 03](docs/caching/benchmarks/03-after-cache.md).
- **Clave:** `incidents:summary`, TTL **60 s**, definidos en [cache.py](services/api/cache.py). [get_incidents_summary](services/api/routes/incidents.py) no tiene JWT y comparte solo contadores globales, sin identidad, título ni descripción.
- **HIT:** copia superficial del diccionario (`dict(cached)`). **MISS:** calcula el agregado y lo guarda con TTL explícito.
- **Invalidación:** `post_incident` y `patch_incident_status`, después de que el servicio de creación/actualización retorne correctamente. Una transición rechazada lanza la excepción antes de invalidar; los tests comprueban que se conserva el HIT.
- **Resultado:** **0.7 / 2.1 ms** en [03 caché](docs/caching/benchmarks/03-after-cache.md), frente a **18.0 / 33.0 ms** en [BYPASS](docs/caching/benchmarks/03-after-cache-bypass.md). Ahorro absoluto moderado; existe la diferencia de volumen ya documentada. No demuestra un cuello de botella percibido por los usuarios.

**Hipótesis sobre el volumen compartido de TinyDB:** `/suppliers` pasó de **1.0 ms** p50 en [01](docs/caching/benchmarks/01-baseline-small.md) a **18.5 ms** en [02](docs/caching/benchmarks/02-baseline-load.md), sin que el [seeder de carga](scripts/perf/seed_load.py) añada proveedores, mientras las incidencias pasaban de **0 a 3000**, según esos benchmarks. [database.py](services/api/database.py) define suppliers, users e incidencias como tablas del mismo fichero JSON de TinyDB. Esto sugiere que el volumen de incidencias podría encarecer las lecturas de todas esas tablas, incluido el acceso de B2, no solo el recorrido y la agregación del resumen. Es una hipótesis: no se aisló el coste de lectura del fichero ni se controlaron por separado otras fuentes de variación.

No se introdujo Redis: no forma parte del stack registrado para este proyecto. La solución es deliberadamente local al proceso; compartir caché e invalidación entre workers requerirá otro mecanismo.

## 5. Decisiones en el frontend

### F1 — LeadForm fuera del viewport inicial

[LazyLeadForm](uis/website/components/LazyLeadForm.tsx) conserva título, texto y ancla de contacto en el wrapper, y difiere [LeadForm](uis/website/components/LeadForm.tsx) con `next/dynamic` y `ssr: false`. Usa `IntersectionObserver`, anticipándose al viewport, y atiende la navegación al ancla. No se cambiaron validaciones del formulario.

La [evidencia de Marisin](docs/caching/frontend/lazy-loading.md) enlaza nombres/tamaños de chunks, medición de altura y capturas de Network. Confirma la ausencia del chunk de formulario en la carga inicial y su solicitud al hacer scroll. Son observaciones de esas sesiones, no bytes ahorrados por ruta ni tiempos de carga medidos.

Las clases `min-h-[82rem] md:min-h-[50.5rem]` sustituyen estimaciones por las alturas que Marisin midió en la [captura de consola](docs/caching/frontend/form-height-console.png), descritas en [lazy-loading.md](docs/caching/frontend/lazy-loading.md). No se reproducen aquí cifras frontend como si proviniesen de un benchmark de backend. **CLS no medido**; no hay una traza que permita afirmar que no se añadió. Las capturas preceden al ajuste final de altura; después se repitió el build, no el navegador.

### F2 — Resultados del análisis bajo demanda

[AnalysisResults](uis/application/components/incidents/AnalysisResults.tsx) contiene el bloque extraído de [analyze/page.tsx](uis/application/app/incidents/analyze/page.tsx). Se carga dinámicamente, con placeholder, solo cuando hay resultado y `uiState === 'success'`; seleccionar el archivo no activa una precarga. `AnalysisResult` se comparte desde [lib/incidents.ts](uis/application/lib/incidents.ts), sin duplicarlo.

La [captura de application](docs/caching/frontend/network-application.png), contextualizada en [lazy-loading.md](docs/caching/frontend/lazy-loading.md), muestra la solicitud del chunk al ejecutar el análisis y presentar resultados. No se deduce una mejora de INP o LCP de esa captura.

### F3 — Memoización no trivial del stock

[OutboundOrderPage](uis/backoffice/src/app/inventory/orders/outbound/page.tsx) memoiza la búsqueda del producto con `[products, selectedSkuId]` y un `Map` de stock por `sku|warehouse` con `[orders]`. Construcción O(n) cuando cambia el historial, lookup O(1) esperado durante las ediciones; memoria O(k) para las combinaciones presentes.

Antes se recorrían las **12008 órdenes** del [benchmark 02](docs/caching/benchmarks/02-baseline-load.md) en cada render con producto seleccionado. El volumen procede de aquel benchmark, no de una nueva lectura de datos en esta fase. Después el índice se reutiliza al editar cantidad/seguimiento o cambiar producto/almacén, y se reconstruye al recibir el historial inicial o tras una salida.

Se conservan cálculo de signos, agrupación, mensaje, bloqueo y recarga del historial. `currentStock` e `isStockExceeded` no tienen memo propio. [usememo.md](docs/caching/frontend/usememo.md) explica el modelo de trabajo y la comparación con React Profiler. **Beneficio estimado**: no hay tiempos de render medidos ni verificación visual posterior.

### Builds conservados

[Website](docs/caching/frontend/build-after-website.txt) y [application](docs/caching/frontend/build-after-application.txt): compilación y TypeScript OK. [Backoffice](docs/caching/frontend/build-after-backoffice.txt): OK en el reintento; el [primer intento](docs/caching/frontend/build-after-backoffice-intento1.txt) terminó por el aviso de seguridad después de compilar. Estos resultados no sustituyen métricas de navegador. No se repitieron builds en esta fase documental.

## 6. Intercambios reconocidos: frescura frente a rendimiento

### Productos y seguridad del stock

El TTL **30 s** limita la vigencia de cada entrada de B1. Un listado puede quedar desfasado si cambian datos fuera del proceso: otro worker, [services/seed.py](services/seed.py), el seeder de carga o escrituras directas a la base. Las escrituras normales de esta API invalidan localmente tras commit, sin esperar al TTL.

Se eligió como compromiso provisional: **5 s** podría dejar pocos HIT entre navegaciones y **5 min** ampliaría demasiado la ventana de desfase. No se midieron intervalos reales entre visitas ni tolerancia operativa; esas alternativas y el TTL elegido son decisiones de diseño que deben revisarse con telemetría, no conclusiones del benchmark.

La validación autoritativa en `create_outbound_order` sigue llamando a `_warehouse_balances` sobre la base de datos. Un stock visual cacheado no se usa para autorizar una salida. El [test de saldo fresco](tests/test_caching.py) cubre el rechazo cuando el saldo real es inferior al listado cacheado. Esto no es una demostración de ausencia de carreras entre salidas concurrentes; ese problema transaccional no se midió ni se cambió.

### Resumen y tolerancia provisional

El TTL **60 s** de B2 corresponde a un indicador agregado de seguimiento, no a una validación de negocio. Se asume tolerable una vigencia de hasta ese TTL para cambios externos; no hay una validación empírica de esa tolerancia por operadores. Altas y cambios de estado que pasan por el mismo proceso invalidan al retornar con éxito; no se espera al TTL.

### Workers y concurrencia

Cada worker/instancia mantiene su propia caché. Reiniciar la API la pierde; una invalidación no se propaga. El TTL limita cuánto permanece una entrada desde que se inserta, pero no sincroniza los procesos.

El bloqueo protege las operaciones del contenedor, no toda la secuencia «MISS → consulta → set». No hay deduplicación de consultas simultáneas. Una consulta en curso podría guardar una versión anterior después de una invalidación; la entrada volvería a expirar por TTL. Por tanto, la invalidación inmediata describe la llamada local tras la escritura y las pruebas secuenciales, no consistencia fuerte ante carreras. No se hicieron mediciones concurrentes; si se necesita esa garantía, habrá que diseñar protección de rellenos e invalidación compartida.

## 7. Qué no se cacheó y por qué

- **Autenticación, usuarios y perfiles:** contraseñas, tokens, sesión y contacto personal. Ninguna clave compartida es admisible para estas respuestas; no se cachea ni siquiera el registro sin JWT.
- **GET `/inventory/orders`:** historial creciente con `user_uuid`; sin paginación y utilizado por el stock visual de salida. En [02](docs/caching/benchmarks/02-baseline-load.md), **2366.74 KB**, p50/p95 **416.4 / 459.5 ms**. Cachearlo no reduce el payload, oculta la necesidad de paginar y arriesga usar historia desfasada. Paginación y un endpoint de saldos por SKU/almacén son mejores siguientes pasos coordinados con el consumidor.
- **GET `/inventory/products/{product_id}`:** el detalle medido corresponde solo al identificador de [02](docs/caching/benchmarks/02-baseline-load.md), con **132.3 / 140.7 ms** p50/p95. La búsqueda de usos solo localiza la definición de `getProductById` en [inventory.ts](uis/backoffice/src/lib/inventory.ts), no llamadas desde páginas/componentes; no se presupone demanda real cero, pero no se justifica otra caché.
- **GET `/suppliers`:** depende de `get_current_user`, por lo que queda excluido aunque sea un directorio. En [02](docs/caching/benchmarks/02-baseline-load.md) costó **18.5 / 28.0 ms** p50/p95; no se presenta como «siempre barato» ni se atribuye su coste únicamente a TinyDB sin perfilar.
- **Hipótesis compartida de TinyDB:** suppliers, users e incidencias usan el mismo fichero JSON, según [database.py](services/api/database.py). Sin añadir proveedores mediante el seeder, el p50 de `/suppliers` creció de **1.0 ms** en [01](docs/caching/benchmarks/01-baseline-small.md) a **18.5 ms** en [02](docs/caching/benchmarks/02-baseline-load.md), al pasar las incidencias de **0 a 3000**. Sugiere un coste de lectura compartido que podría afectar a todas las tablas, incluido B2; no demuestra la causa ni justifica cachear respuestas autenticadas.
- **GET `/api/incidents`:** texto libre potencialmente sensible, variantes por filtros y payload de **929.27 KB**, p50/p95 **25.8 / 44.1 ms** sin filtros en [02](docs/caching/benchmarks/02-baseline-load.md). El coste de otras combinaciones no se midió; una caché multiplicaría claves y datos retenidos.
- **Detalles de incidencias y resto de lecturas personales:** sin demanda localizada que justifique cachear detalles y con contenido potencialmente sensible. No se extrapola el benchmark de un listado a sus detalles.
- **Mutaciones:** no se cachean respuestas de altas, actualizaciones ni bajas. Solo invalidan los agregados afectados cuando corresponde.
- **`_warehouse_balances`:** parte de la validación crítica del stock, nunca cacheada. Tampoco se utiliza `lru_cache` sobre sesiones, requests o datos sin TTL.
- **Frontend inicial:** [Header](uis/website/components/Header.tsx), [Hero](uis/website/components/Hero.tsx) y [DashboardShell](uis/application/components/DashboardShell.tsx) siguen disponibles en el render inicial. Diferir estructura visible introduciría una espera que podría perjudicar el LCP; es un riesgo de diseño, no una regresión medida. `isStockExceeded` no se memoiza por ser una comparación trivial.

## 8. Riesgos y siguientes pasos

- **Seguridad de dependencias:** Next.js **16.4.4** del backoffice advierte de una vulnerabilidad conocida en los [logs de build](docs/caching/frontend/build-after-backoffice-intento1.txt). Se recomienda actualizar a una versión corregida en un trabajo separado. No se diagnosticó aquí el alcance de la vulnerabilidad ni se cambiaron dependencias.
- **Escalado y carreras:** evaluar Redis con TTL e invalidación compartida antes de escalar workers; diseñar además protección frente a rellenos concurrentes. Redis por sí solo no hace atómica una secuencia de consulta e invalidación.
- **Historial:** paginar y trasladar el cálculo autoritativo de saldos a un endpoint específico; adaptar conjuntamente el consumidor para no calcular stock sobre una página parcial.
- **Conexiones:** [database.py](services/api/database.py) usa `NullPool` y TLS requerido. Sin reutilización de conexiones en el proceso, las consultas pueden pagar establecimiento de conexión. El coste fijo observado incluso con poco volumen es compatible con esa hipótesis, pero no se aisló su contribución frente a SQL, serialización o red. Evaluar pooling compatible con Supabase y medirlo por separado; fuera de alcance.
- **Evidencia del posible coste fijo:** en [01-baseline-small.md](docs/caching/benchmarks/01-baseline-small.md), el detalle de un solo producto (`/inventory/products/2`) tiene p50 de **128.8 ms**, frente a **133.8 ms** del listado. Que un solo registro cueste casi lo mismo que el listado apoya la hipótesis de un coste dominante fijo por petición, por ejemplo establecer la conexión con `NullPool` y TLS. No se aisló ese coste: estos tiempos no permiten atribuirlo exclusivamente a la conexión.
- **Credenciales de demostración en el benchmark:** [bench_endpoints.py](scripts/perf/bench_endpoints.py) contiene escritas las credenciales de la cuenta de demostración que crea `seed_database()` en [database.py](services/api/database.py). Son solo de demo, pero conviene leerlas de variables de entorno antes de exponer el proyecto. No se reproducen sus valores ni se modifica el script en esta corrección documental.
- **Telemetría:** medir tasa de HIT/MISS/BYPASS, expiración e invalidación, cadencia de escrituras, intervalos entre lecturas y latencias por endpoint. `stats()` es local al proceso y no se expone como servicio de métricas; las ráfagas del benchmark no describen tráfico real.
- **Frontend:** completar React Profiler, comprobar visualmente stock/avisos y medir CLS antes de certificar el criterio pendiente de Fase 5. No hay LCP/INP de campo ni comparaciones temporales de interacción.
- **Evidencia local:** semilla sintética, peticiones secuenciales y resumen con distinto volumen entre 03/BYPASS. Repetir a volumen idéntico si se necesita una comparación estricta de B2; no se modificaron evidencias anteriores.
- **Cierre pendiente:** en Fase 8 corresponde ejecutar las validaciones finales, preguntar a Marisin por los datos de carga y completar registros. No se limpiaron datos, no se inició esa fase ni se hizo push.

## 9. Cómo reproducir

Comandos de referencia para Marisin, desde la raíz salvo indicación. **No se ejecutaron en Fase 7.** Requieren el entorno Python y las dependencias ya preparados, la configuración local existente y acceso autorizado a los datos. No imprimir tokens, modificar credenciales ni repetir la copia de seguridad ya realizada.

### Preparar datos, solo si corresponde

La carga escribe en PostgreSQL y TinyDB; confirmar el destino antes de ejecutarla. Si ya hay datos de carga, el seeder no los duplica. No sirve para recrear automáticamente el benchmark de volumen inicial.

```sh
python -m scripts.perf.seed_load
```

### API con caché y medición

Terminal A, proceso en primer plano:

```sh
TRACKFLOW_CACHE_ENABLED=1 python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Terminal B:

```sh
python scripts/perf/bench_endpoints.py --label repro-cache --runs 30
```

El script usa las credenciales de demostración existentes para medir proveedores sin imprimirlas. Produce `docs/caching/benchmarks/repro-cache.md`. No sobrescribir los ficheros originales de evidencia. Detener A con Ctrl+C antes de la siguiente ejecución.

### API sin caché, mismo volumen

Terminal A:

```sh
TRACKFLOW_CACHE_ENABLED=0 python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Terminal B:

```sh
python scripts/perf/bench_endpoints.py --label repro-bypass --runs 30
```

No hacer escrituras entre las dos mediciones si se quiere comparar exactamente el mismo volumen. Revisar los volúmenes guardados y `X-Cache`, además de los percentiles. Detener A con Ctrl+C al terminar.

### Tests y builds

Suite utilizada por el proyecto para su cierre final:

```sh
pytest -q
```

Builds, cada uno desde la carpeta indicada:

```sh
# uis/website
NODE_ENV=production npm run build

# uis/backoffice
NODE_ENV=production NEXT_PUBLIC_INVENTORY_API_URL=http://127.0.0.1:8000 npm run build

# uis/application
npm run build
```

La comprobación de navegador se reproduce con los pasos de [lazy-loading.md](docs/caching/frontend/lazy-loading.md) y [usememo.md](docs/caching/frontend/usememo.md). Conservar las condiciones de comparación y cerrar los servidores cuando dejen de ser necesarios.

### Limpieza opcional, solo con autorización

El siguiente comando elimina los SKUs con prefijo `LOAD-`, sus movimientos y las incidencias tituladas con prefijo `[LOAD]`. Afecta ambos almacenes de datos; **no ejecutarlo si se quieren conservar para capturas**, ni confundirlo con una limpieza de caché.

```sh
python -m scripts.perf.seed_load --purge
```

La decisión de conservar o limpiar sigue reservada a Marisin en Fase 8. No se ejecutó este comando ni se restauraron datos durante la redacción del informe.
