# Candidatos de caching — Fase 2

## Evidencia y límites

Carga y mediciones ejecutadas por Marisin en su terminal; la API quedó parada.
El agente no ejecutó Python, el seeder, la API ni los benchmarks.

- [Seed: volumen antes/después e invariante](benchmarks/02-seed-output.txt).
- [01: volumen inicial](benchmarks/01-baseline-small.md).
- [02: carga realista](benchmarks/02-baseline-load.md).
- [Timing de 02](benchmarks/02-baseline-load-log.txt).
- Estabilidad de [productos](benchmarks/02-stability-products.txt) y
  [resumen](benchmarks/02-stability-summary.txt).
- [Inventario completo de operaciones y autenticación](routes-inventory.md).

Las latencias de las tablas se copian literalmente de los benchmarks:
min/p50/p95/max usan `X-Response-Time-ms` en las repeticiones posteriores a
la primera llamada. Son tiempos del middleware, no latencia de red ni tiempo
de consumo en el navegador; no se ha aislado el coste de SQL, TLS o TinyDB.
No hay telemetría de tráfico: toda frecuencia indicada es una **estimación
basada en consumidores** estáticos, no peticiones por segundo observadas.
«Sin consumidor localizado» no equivale a frecuencia real cero.

## Volumen

| Tabla / magnitud | Antes | Después | Fuente |
|---|---:|---:|---|
| SKUs | 2 | 302 | Seed |
| StockEntry | 4 | 8004 | Seed |
| StockExit | 4 | 4004 | Seed |
| Órdenes totales | 8 | 12008 | Benchmarks 01 y 02 |
| Incidencias | 0 | 3000 | Seed y benchmarks |

El seeder informó «Invariante de stock no negativo: verificado por SKU y
almacén». La comprobación compara **sumas finales**, no saldos históricos:
las fechas de salida se generan independientemente de las de entrada.
No demuestra que cada salida estuviese cubierta en su fecha histórica.
Hay commits por lotes y dos almacenes de datos sin transacción conjunta;
si falla a medias, se debe usar `--purge` antes de repetir. La idempotencia
impide duplicados, pero no reanuda una carga parcial.
La copia de seguridad previa ya la hizo Marisin; no se repitió.

## Comparación 01 frente a 02

| Endpoint | p50 01 ms | p95 01 ms | p50 02 ms | p95 02 ms | KB medios 01 | KB medios 02 |
|---|---:|---:|---:|---:|---:|---:|
| `/inventory/products` (B1) | 133.8 | 165.0 | 156.1 | 186.3 | 0.30 | 47.92 |
| `/api/incidents/summary` (B2) | 0.9 | 2.7 | 22.0 | 41.5 | 0.28 | 0.31 |
| `/inventory/orders` (contraste) | 129.0 | 134.5 | 416.4 | 459.5 | 1.50 | 2366.74 |

Las capturas MD5 contienen una única línea por endpoint:

```text
productos: 20 877916fad4febc937b4a330a49699971
resumen:   20 81d5b629978b993761017c4c9897b8c7
```

Según el procedimiento ejecutado por Marisin, las respuestas fueron idénticas
en las peticiones consecutivas sin escrituras. Esto no demuestra estabilidad
ante escrituras ni sustituye las pruebas futuras de invalidación. Las
capturas no contienen status ni duración; no permiten verificar el coste de
esa ráfaga adicional. El log entregado contiene las llamadas del benchmark
y el acceso adicional a `/`, no la ráfaga de estabilidad. Para coste se
usan exclusivamente los tiempos del benchmark 02:

| Endpoint | Min ms | p50 ms | p95 ms | Max ms |
|---|---:|---:|---:|---:|
| `/inventory/products` | 142.4 | 156.1 | 186.3 | 187.3 |
| `/api/incidents/summary` | 18.1 | 22.0 | 41.5 | 47.5 |

## Consumidores citados

Referencias usadas en la matriz; las rutas son relativas a este documento.
Los endpoints sin consumidor localizado se comprobaron buscando paths y
helpers en los fuentes TypeScript/TSX de `uis/`.

- **INV**: [inventory.ts](../../uis/backoffice/src/lib/inventory.ts):
  `getProducts`, `getOrders`, `getProductById`, `createInboundOrder`,
  `createOutboundOrder`.
- **PRODUCTS**: [products/page.tsx](../../uis/backoffice/src/app/inventory/products/page.tsx),
  `InventoryProductsPage` → `useInventoryData(getProducts)`.
  [useInventoryData](../../uis/backoffice/src/hooks/useInventoryData.ts)
  carga al montar/cambiar la función, sin polling.
- **HISTORY**: [orders/page.tsx](../../uis/backoffice/src/app/inventory/orders/page.tsx),
  `InventoryOrdersHistoryPage` → `useInventoryData(getOrders)`.
- **INBOUND**: [inbound/page.tsx](../../uis/backoffice/src/app/inventory/orders/inbound/page.tsx),
  `InboundOrderPage` carga productos en `useEffect` y envía la entrada
  en `handleSubmit`.
- **OUTBOUND**: [outbound/page.tsx](../../uis/backoffice/src/app/inventory/orders/outbound/page.tsx),
  `OutboundOrderPage` carga productos e historial en `useEffect`;
  `handleSubmit` envía la salida y vuelve a pedir el historial.
- **LAYOUT**: [inventory/layout.tsx](../../uis/backoffice/src/app/inventory/layout.tsx),
  `InventoryLayout` consulta `/auth/me` al montar su efecto con token.
- **SUPPLIERS**: [suppliers/page.tsx](../../uis/application/app/suppliers/page.tsx),
  `SuppliersPage.loadSuppliers`, dentro del efecto de montaje, mediante
  `protectedFetch`; no usa filtros ni polling en esta página.
- **REGISTER**: [register/page.tsx](../../uis/application/app/register/page.tsx),
  `RegisterPage.handleSubmit` registra y luego inicia sesión.
- **LOGIN**: [application/login](../../uis/application/app/login/page.tsx),
  `LoginPage.handleSubmit` → `authApi.login` en
  [lib/api.ts](../../uis/application/lib/api.ts);
  [backoffice/login](../../uis/backoffice/src/app/login/page.tsx),
  `LoginPage.handleSubmit` → `login` en
  [lib/api.ts](../../uis/backoffice/src/lib/api.ts).
- **PASSWORD**: [forgot-password](../../uis/application/app/forgot-password/page.tsx),
  `ForgotPasswordPage.handleSubmit` → `authApi.forgotPassword`;
  [reset-password](../../uis/application/app/reset-password/page.tsx),
  `ResetPasswordForm.handleSubmit` → `authApi.resetPassword`;
  [change-password](../../uis/application/app/account/change-password/page.tsx),
  `ChangePasswordPage.handleSubmit` → `authApi.changePassword`.
- **PROFILE**: [account/profile](../../uis/application/app/account/profile/page.tsx),
  `ProfilePage.loadProfile` consulta `/auth/me` al montar;
  `ProfilePage.handleSubmit` guarda con `PUT /profiles/me`.
- **INCIDENTS**: [lib/incidents.ts](../../uis/application/lib/incidents.ts),
  `listIncidents`, `getIncidentSummary`, `createIncident`,
  `updateIncidentStatus`, mediante proxy `/backend`.
  [IncidentWorkspace](../../uis/application/components/incidents/IncidentWorkspace.tsx):
  `loadIncidents` al montar/cambiar filtros o reintentar;
  `loadSummary` al montar, reintentar y tras `changeStatus` exitoso;
  `changeStatus` envía el PATCH solo por acción del operador.
- **CREATE-INCIDENT**: [IncidentForm](../../uis/application/components/incidents/IncidentForm.tsx),
  `IncidentForm.handleSubmit` → `createIncident`.

**Detalle de producto:** `getProductById` solo aparece definido en INV.
No se localizó importación ni llamada desde una página o componente de
`uis/`, ni un fetch directo equivalente al detalle. Los enlaces a formularios
con `sku_id` usan el listado, no el endpoint individual. No se asigna una
frecuencia real a un helper sin consumidores.

## Matriz de decisión: todas las operaciones del inventario

Coste = p50/p95 en ms de **02**, sin redondear. «No medido» significa que
no hay benchmark para esa operación; no se extrapola desde otro método o
desde un detalle con distinto identificador. Las decisiones CACHEAR son
candidaturas para fases posteriores, **no caché implementada**.

| Endpoint | Coste medido (p50/p95 ms) | Frecuencia estimada | Frecuencia de cambio de datos | ¿Personal/sensible? | Decisión |
|---|---|---|---|---|---|
| GET `/suppliers` | 18.5 / 28.0 | Estimación basada en consumidores: SUPPLIERS, al montar. | Altas, tarifas, estado y bajas de proveedores; cadencia real no medida. | Sí: depende de `get_current_user`; directorio comercial. | NO CACHEAR: ruta autenticada excluida, aunque su coste aumentó con el JSON de carga. |
| GET `/suppliers/{supplier_id}` | No medido | Estimación basada en consumidores: sin consumidor de detalle localizado. | Escrituras del proveedor. | Sí: depende de `get_current_user`. | NO CACHEAR: autenticada y sin demanda frontend localizada. |
| POST `/suppliers` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Cada alta efectiva. | Sí: depende de `get_current_user`. | NO CACHEAR: mutación. |
| PATCH `/suppliers/{supplier_id}/rate` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Cada cambio efectivo de tarifa. | Sí: depende de `get_current_user`. | NO CACHEAR: mutación. |
| PATCH `/suppliers/{supplier_id}/status` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Cada cambio efectivo de estado. | Sí: depende de `get_current_user`. | NO CACHEAR: mutación. |
| DELETE `/suppliers/{supplier_id}` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Cada baja efectiva. | Sí: depende de `get_current_user`. | NO CACHEAR: mutación. |
| POST `/users` | No medido | Estimación basada en consumidores: REGISTER, al enviar registro. | Cada cuenta creada. | Sí: credenciales y datos personales, aunque no exige JWT. | NO CACHEAR: registro y mutación sensible. |
| GET `/users` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Altas, modificaciones y bajas de cuentas. | Sí: usuarios y JWT. | NO CACHEAR: datos personales y prohibición del proyecto. |
| GET `/users/{user_id}` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Cambios de la cuenta. | Sí: usuario y JWT. | NO CACHEAR: datos personales. |
| PUT `/users/{user_id}` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Cada modificación efectiva. | Sí: usuario y JWT. | NO CACHEAR: mutación sensible. |
| DELETE `/users/{user_id}` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Cada baja efectiva. | Sí: usuario y JWT. | NO CACHEAR: mutación sensible. |
| POST `/auth/login` | No medido | Estimación basada en consumidores: LOGIN y REGISTER, envío manual o tras registro. | Tokens por sesión; validez depende de cuenta/credenciales. | Sí: contraseñas y tokens. | NO CACHEAR: autenticación; el timing del login en el log no es un p50/p95. |
| GET `/auth/me` | No medido | Estimación basada en consumidores: LAYOUT y PROFILE, al montar/verificar sesión. | Cambios de cuenta/perfil y sesión. | Sí: respuesta del usuario actual. | NO CACHEAR: datos privados dependientes de JWT. |
| POST `/auth/forgot-password` | No medido | Estimación basada en consumidores: PASSWORD, envío del formulario de recuperación. | Solicitud de recuperación/tokens. | Sí: identidad y recuperación de acceso. | NO CACHEAR: operación sensible con efectos. |
| POST `/auth/reset-password` | No medido | Estimación basada en consumidores: PASSWORD, envío de nueva contraseña con token. | Contraseña y consumo del token. | Sí: secreto y token. | NO CACHEAR: mutación sensible. |
| POST `/auth/change-password` | No medido | Estimación basada en consumidores: PASSWORD, envío autenticado del formulario. | Cada cambio de contraseña. | Sí: credenciales y JWT. | NO CACHEAR: mutación sensible. |
| GET `/profiles/me` | No medido | Estimación basada en consumidores: sin GET directo localizado; PROFILE lee el perfil mediante `/auth/me`. | Registro/edición del perfil. | Sí: perfil del usuario actual. | NO CACHEAR: personal, sin consumidor GET directo. |
| PUT `/profiles/me` | No medido | Estimación basada en consumidores: PROFILE, `handleSubmit`. | Cada guardado efectivo del perfil. | Sí: contacto personal y JWT. | NO CACHEAR: mutación sensible. |
| GET `/profiles/{profile_id}` | No medido | Estimación basada en consumidores: sin consumidor localizado. | Ediciones del perfil. | Sí: contacto personal y JWT. | NO CACHEAR: datos personales. |
| GET `/inventory/products` | 156.1 / 186.3 | Estimación basada en consumidores: INV → PRODUCTS, INBOUND y OUTBOUND, al montar o cambiar `initialSkuId` en formularios. | POST producto, entrada y salida; también scripts o escrituras externas. Cadencia real no medida. | No hay JWT ni campos por usuario en este listado; incluye datos operativos comerciales globales. | CACHEAR (B1): coste repetido SQL/TLS y listado estable; TTL 30 s propuesto con invalidación tras escrituras exitosas. |
| POST `/inventory/products` | No medido | Estimación basada en consumidores: sin formulario/helper de alta localizado. | Cada alta efectiva. | Sí: depende de `get_current_user`. | NO CACHEAR: mutación; debe invalidar el listado en la fase correspondiente. |
| GET `/inventory/products/{product_id}` | 132.3 / 140.7 (solo ID 2) | Estimación basada en consumidores: `getProductById` en INV sin llamadas localizadas en páginas. | Producto y movimientos del SKU. | No exige JWT; información operativa del producto. | NO CACHEAR: coste medido pero sin demanda frontend localizada; no generalizar este detalle a todos los SKU. |
| POST `/inventory/orders/inbound` | No medido | Estimación basada en consumidores: INBOUND, `handleSubmit`. | Cada entrada efectiva. | Sí: depende de `get_current_user`, atribuye usuario. | NO CACHEAR: mutación; invalidar listado tras commit exitoso. |
| POST `/inventory/orders/outbound` | No medido | Estimación basada en consumidores: OUTBOUND, `handleSubmit`. | Cada salida efectiva. | Sí: depende de `get_current_user`, atribuye usuario. | NO CACHEAR: mutación y validación autoritativa de stock siempre fresca. |
| GET `/inventory/orders` | 416.4 / 459.5 | Estimación basada en consumidores: INV → HISTORY al montar y OUTBOUND al montar/cambiar SKU inicial y tras salida exitosa. | Entradas y salidas; también seed externo. | No exige JWT, pero expone `user_uuid` e historial operativo; no tratarlo como dato público. | NO CACHEAR: payload 2366.74 KB sin paginación y stock visual por almacén calculado desde el historial; proponer paginación y endpoint de saldos, fuera de alcance. |
| POST `/api/incidents` | No medido | Estimación basada en consumidores: CREATE-INCIDENT, `handleSubmit`. | Cada incidencia creada. | Sin JWT, pero título/descripción pueden contener información sensible. | NO CACHEAR: mutación; invalidar agregado tras éxito. |
| GET `/api/incidents` | 25.8 / 44.1 (sin filtros) | Estimación basada en consumidores: INCIDENTS, `loadIncidents` al montar/cambiar filtros/reintentar. | Altas y cambios de estado. | Sin JWT, pero incluye títulos y descripciones libres; no asumir anonimización. | NO CACHEAR: filas potencialmente sensibles, variantes por filtros y payload 929.27 KB; coste medido solo sin filtros. |
| GET `/api/incidents/summary` | 22.0 / 41.5 | Estimación basada en consumidores: INCIDENTS, `loadSummary` al montar, reintentar y después de `changeStatus` exitoso. | Altas y cambios de estado, también seed externo. | Sin JWT; recuentos globales sin identidad, título ni descripción. | CACHEAR (B2): agregación repetible y estable con carga; TTL 60 s propuesto e invalidación tras alta/PATCH exitoso; beneficio absoluto moderado. |
| GET `/api/incidents/{incident_id}` | No medido | Estimación basada en consumidores: sin helper/página de detalle localizado; Workspace usa filas del listado. | Cambio de estado de esa incidencia. | Sin JWT, pero detalle con texto libre potencialmente sensible. | NO CACHEAR: sin demanda localizada y posible información sensible. |
| PATCH `/api/incidents/{incident_id}/status` | No medido | Estimación basada en consumidores: INCIDENTS, `changeStatus` por acción del operador. | Cada transición válida. | Sin JWT; modifica una incidencia. | NO CACHEAR: mutación; invalidar agregado solo si tiene éxito. |

## Validación de B1 y B2

- **B1 se sostiene como candidato**, no como mejora demostrada. Ya tenía coste
  apreciable con pocos registros y lo mantiene con carga; los consumidores
  solicitan el mismo listado al entrar en distintos flujos. El coste fijo
  podría estar relacionado con conexiones `NullPool`/TLS, pero no se ha
  perfilado ni cuantificado esa contribución por separado.
- **B2 se sostiene de forma más modesta**: el coste absoluto sigue siendo
  bajo, pero aumenta con el volumen y el agregado estable evita repetir
  trabajo de lectura/agregación. No hay un umbral de latencia acordado que
  lo invalide. No se afirma un cuello de botella percibido por usuarios ni
  se promete hit ratio: deben medirse con/sin caché en la fase prevista.
- Alternativa si el ahorro posterior no compensa la complejidad: no cachear
  B2 y estudiar lecturas/agregación de TinyDB; sustituirlo por otra caché
  requiere nueva evidencia y autorización. `GET /suppliers` no es alternativa:
  depende de autenticación y está expresamente excluido.
- Los TTL propuestos siguen siendo hipótesis de frescura, no deducciones de
  las mediciones. Las escrituras de la API deben invalidar al instante; las
  externas y varios workers solo quedan acotados por TTL.
- `_warehouse_balances` nunca se cacheará: valida las salidas. Ni la
  estabilidad observada ni el coste del listado justifican cambiarlo.

## Límites de la decisión

No se implementó caché ni se ejecutaron scripts adicionales. La semilla es
sintética, el volumen no prueba tráfico real y las observaciones son locales.
No hay tiempos del navegador, concurrencia ni perfilado SQL/TinyDB.
El crecimiento de `/suppliers` respecto a 01 impide seguir llamándolo
«siempre barato»; no demuestra por sí solo la causa del aumento.
El GET `/` 404 del log 01 fue provocado por el navegador al abrir el puerto
reenviado de Codespaces, según confirmó Marisin; no es un fallo del benchmark.
