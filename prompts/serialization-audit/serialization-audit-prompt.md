# ROL
Actúa como Principal Backend Engineer y Application Security Architect especializado en FastAPI y Pydantic. Trabajas sobre el monorepo de TrackFlow (logística de última milla, ver CONTEXT.md en la raíz). Tu responsabilidad es llevar la API a estándares de producción sin reescribirla: auditar, corregir con criterio y documentar cada decisión.

# CONTEXTO DEL ENTORNO
- Rama de trabajo: `feature/serialization-audit` (YA CREADA). Antes de empezar, verifica con `git branch --show-current` que estás en ella. No crees ramas nuevas ni trabajes sobre `main`.
- Entorno Python: `source /workspaces/Mi-Contexto-De-Empresa-Marisin/.venv/bin/activate`
- La API corre en el puerto 8000; la documentación interactiva está en `http://localhost:8000/docs`.
- Frontends consumidores: `uis/backoffice` (puerto 3001) y `uis/website` (puerto 3000).
- Lee primero `AGENTS.md`, `CONTEXT.md` y `pyproject.toml`. Revisa la carpeta `skills/` y `skills-lock.json`: si existe alguna skill de backend, FastAPI, API design, seguridad o testing, léela y aplícala, y menciona en el documento de auditoría qué skills usaste.

# OBJETIVO
Que NINGÚN endpoint devuelva objetos de base de datos crudos (ORM, SQLModel, TinyDB `Document`) ni dicts sin tipar; que cada endpoint declare un `response_model` explícito; que no se expongan campos sensibles; y que los payloads de listado contengan solo lo que el consumidor usa.

# REGLAS INQUEBRANTABLES
1. **Cero invenciones.** Toda afirmación del documento de auditoría (rutas, ficheros, funciones, campos, componentes del frontend) debe existir en el código. Cita la ruta real del fichero y el nombre real de la función. Si algo no lo encuentras, escríbelo como "no encontrado", nunca lo supongas.
2. **No reescribas desde cero.** Haz cambios mínimos y localizados. No toques ficheros ajenos a la serialización (frontend de estilos, configuración de build, etc.).
3. **Sin regresiones.** Si quitas un campo de una respuesta, comprueba antes con búsqueda en `uis/` y `packages/` (o `shared/`) que ningún consumidor lo lee. Si se usa, mantenlo y justifícalo en el doc. Si cambias un tipo compartido de TypeScript, actualízalo de forma mínima.
4. **Detecta la versión de Pydantic** (v1 o v2) y usa la sintaxis correcta: `model_config = ConfigDict(from_attributes=True)` / `model_validate` en v2. Para datos de TinyDB (dicts), valida con el esquema en lugar de devolver el dict.
5. **Esquemas de entrada y salida nunca se mezclan.** Un esquema de respuesta jamás se usa como cuerpo de petición, y viceversa.
6. No hagas push ni abras el PR. Haz solo commits locales con formato convencional y descripción en español (p. ej. `feat(auth): añadir esquemas de respuesta explícitos`).
7. El registro de progreso de este proyecto es SOLO `prompts/serialization-audit/progress.md`. No confundir con `memory-bank/progress.md`: si AGENTS.md exige actualizar memory-bank, hazlo además, pero nunca en su lugar.

# FASE 0 — DESCUBRIMIENTO Y BASELINE (antes de modificar nada)
1. Localiza la(s) app(s) FastAPI (`FastAPI(`) y todos los `APIRouter`.
2. Genera el inventario real de rutas recorriendo `app.routes` (instancias de `APIRoute`): método, path, `response_model` actual y `endpoint.__module__.__name__`. Guarda la salida; la usarás en el doc.
3. Ejecuta `pytest -q` y apunta el resultado exacto (passed/failed/errors) como **baseline**. Si ya hay tests fallando antes de tus cambios, documéntalo como preexistente.
4. Para cada endpoint, identifica su consumidor buscando el path en `uis/` (fetch, axios, clientes de API, tipos TS) y anota qué campos lee realmente la UI.

# FASE 1 — AUDITORÍA → `docs/serialization-audit.md`
Crea el documento ANTES de implementar, con esta estructura:

1. **Resumen ejecutivo:** número de endpoints, cuántos ✅/⚠️/❌ originalmente, riesgos principales detectados.
2. **Metodología:** cómo inventariaste las rutas, cómo identificaste consumidores y qué skills aplicaste.
3. **Criterios de clasificación:**
   - ✅ Ya serializado: tiene `response_model` explícito y el esquema es adecuado.
   - ⚠️ Parcialmente serializado: tiene response model pero está incompleto, expone campos innecesarios o no coincide con lo que necesita el cliente.
   - ❌ Sin serializar: devuelve un objeto ORM/TinyDB crudo o un dict sin tipar.
4. **Sección AUTH primero** (registro, login, forgot/reset password, `/auth/me`, refresh/logout si existen), luego el resto agrupado por router.
5. **Tabla de inventario** con columnas: `Método | Ruta | Propósito | Consumidor | Respuesta original | Estado original | Esquema entrada | Esquema salida | Estado final`.
6. **Ficha por cada endpoint ⚠️ o ❌**, con:
   - Qué recibe, qué debería devolver y qué devuelve hoy (los tres niveles).
   - Qué campos sobran o son sensibles, y por qué.
   - **Payload objetivo campo por campo** (lista explícita de atributos de salida).
   - Tipo de mejora necesaria (filtrado de campos, esquema de listado ligero, aplanado de relación, separación entrada/salida, eliminación de dato sensible) y el porqué.
   - **Decisión sobre relaciones:** objeto anidado completo, solo ID relacionado o proyección plana, con justificación basada en el consumidor.
   - Ficheros modificados (rutas reales).

**CHECKPOINT:** al terminar la Fase 1, detente y muéstrame un resumen de la tabla y la lista de cambios propuestos. No implementes hasta que yo confirme.

# FASE 2 — IMPLEMENTACIÓN
1. Crea o actualiza los esquemas Pydantic de cada endpoint ⚠️/❌, ubicados según la convención existente del repo (si hay carpeta `schemas/`, úsala).
2. Usa esta convención de nombres (adaptada a la existente si ya hay una):
   - Entrada: `XCreate`, `XUpdate` (PATCH con campos opcionales).
   - Salida detalle: `XPublic` o `XDetail`.
   - Salida listado: `XListItem` (más ligero, sin relaciones anidadas salvo justificación).
   - Para listados paginados, si el endpoint ya pagina, usa un envoltorio tipado (p. ej. `Page[XListItem]` o `XListResponse`).
3. Esquemas de entrada: declara solo los campos escribibles por el cliente y usa `extra="forbid"`. Nunca aceptes `id`, timestamps de auditoría, flags internos, `hashed_password` ni claves de propietario que deban salir del token.
4. Esquemas de salida: **lista explícita de atributos**, sin heredar ciegamente del modelo de BD. Excluye siempre: `hashed_password`/`password`, tokens internos, secretos, flags de borrado lógico, timestamps de auditoría que la UI no use y claves foráneas en bruto cuando ya se expone el objeto relacionado.
5. Declara `response_model=...` en el decorador de TODAS las rutas, incluidos health checks (`HealthResponse`) y respuestas de confirmación (`MessageResponse`). Si un endpoint responde 204 sin cuerpo y cambiarlo rompería tests o frontend, mantén el 204 y documenta la excepción explícitamente en el doc.
6. **Reglas de auth:**
   - Registro: no devuelve contraseña ni email. Devuelve un mensaje de confirmación o una proyección segura sin credenciales (p. ej. `id`, `display_name`), según lo que use el frontend.
   - Login: devuelve solo lo necesario para continuar (p. ej. `access_token`, `token_type`, y si la UI lo requiere, una proyección mínima sin email).
   - Forgot password: respuesta genérica idéntica exista o no el email (evita la enumeración de usuarios).
   - Reset password: mensaje genérico de confirmación.
   - `GET /auth/me`: SÍ puede devolver el `email` del usuario autenticado (lo necesita la vista de perfil), pero nunca la contraseña.
7. Haz commits atómicos con prefijo convencional y descripción en español. Ejemplos:
   - `feat(auth): añadir esquemas de respuesta explícitos`
   - `feat(<router>): añadir esquema ligero para listados`
   - `test: añadir tests de contrato de serialización`
   - `docs: añadir auditoría de serialización`

# FASE 3 — VERIFICACIÓN
1. Añade un test de contrato (p. ej. `tests/test_serialization_contracts.py`) que:
   - Recorra `app.routes` y falle si alguna `APIRoute` no tiene `response_model` (salvo las excepciones 204 documentadas).
   - Compruebe que las respuestas de registro, login, forgot y reset no contienen las claves `password`, `hashed_password` ni `email`.
   - Compruebe que `GET /auth/me` no contiene `password` ni `hashed_password`.
   - Compruebe que al menos un endpoint de escritura rechaza (422) un campo no permitido.
2. Ejecuta `pytest -q` y compara con el baseline. Todos los tests que pasaban deben seguir pasando.
3. Levanta la API y prueba manualmente en `/docs` al menos 3 endpoints (uno de auth, un listado y uno de escritura). Para cada uno, anota en el doc la petición, el shape real de la respuesta y la confirmación de que coincide con el esquema.
4. Actualiza `docs/serialization-audit.md`:
   - Columna "Estado final" con todos los endpoints en ✅.
   - Mantén la columna "Estado original" intacta (el evaluador necesita ver el antes y el después).
   - Añade una sección **Verificación** con el resultado de pytest antes/después, la tabla de pruebas manuales y espacio para las capturas.

# CRITERIOS DE ACEPTACIÓN (comprueba cada uno antes de terminar)
- [ ] Estoy en la rama `feature/serialization-audit`.
- [ ] Todas las rutas de la app tienen `response_model` explícito (verificado por test automático).
- [ ] Ningún endpoint devuelve objetos ORM/TinyDB crudos ni dicts sin tipar.
- [ ] Los esquemas de entrada y salida están separados; ningún esquema de respuesta se usa como body.
- [ ] Los endpoints de escritura aceptan solo los campos permitidos (`extra="forbid"`).
- [ ] Los listados usan un esquema ligero propio, sin anidado innecesario ni over-fetching.
- [ ] Ninguna respuesta expone `password`, `hashed_password` ni tokens internos.
- [ ] Registro, login, forgot y reset no devuelven el email; `GET /auth/me` sí puede.
- [ ] Forgot password responde igual exista o no el usuario.
- [ ] Cada decisión sobre relaciones (anidado, ID o plano) está documentada.
- [ ] `docs/serialization-audit.md` lista todos los endpoints, con estado original, cambios aplicados, estado final ✅ y la sección de verificación.
- [ ] Todo fichero, función o componente citado en el doc existe realmente en el repo.
- [ ] `pytest` pasa al menos los mismos tests que el baseline, más los nuevos de contrato.
- [ ] El frontend no pierde ningún campo que realmente lea.

# ENTREGA FINAL DEL AGENTE
Al terminar, muéstrame:
1. La lista de ficheros creados y modificados.
2. El resultado de pytest antes y después.
3. Los criterios de aceptación marcados.
4. Un borrador de descripción para el PR con título `feat: serialization audit and implementation`.

# REGISTRO DE PROGRESO (obligatorio)
Mantén actualizado `prompts/serialization-audit/progress.md`.
Tras completar cada paso, márcalo y anota: fecha, qué hiciste, ficheros tocados y hash del commit.
Antes de empezar cualquier sesión:
1. Lee este prompt completo.
2. Lee el registro de progreso.
3. Ejecuta `git branch --show-current`, `git status` y `git log --oneline -10`.
4. Continúa desde la primera tarea pendiente. No repitas tareas ya marcadas salvo que el registro indique que quedaron a medias.