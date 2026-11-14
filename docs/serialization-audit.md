# Auditoría inicial de serialización de la API

**Fecha:** 2026-11-13
**Alcance:** auditoría, implementación y verificación de la serialización; hallazgos de autenticación documentados fuera de alcance.

## 1. Resumen ejecutivo

Se inventariaron **25 endpoints** en cinco routers: **4 ✅**, **18 ⚠️** y **3 ❌** en su estado original.

Riesgos principales:

- `POST /auth/forgot-password`, `POST /auth/reset-password` y `POST /auth/change-password` devuelven diccionarios sin `response_model`.
- El registro (`POST /users`) usa `UserResponse`, que incluye `email`, aunque `uis/application/app/register/page.tsx` solo comprueba el estado HTTP y continúa con el login.
- `MeResponse` anida `Profile`, que incluye `id` y `user_id`; la pantalla de cuenta solo utiliza `name`, `phone` y `address`, además del email del usuario.
- `GET /inventory/orders` devuelve una proyección completa del producto y un objeto `user` con email/nombre. La UI solo lee `product.name`, `product.sku` y `user_uuid`; este último se muestra y debe conservarse.
- Los modelos de perfil y proveedor incluyen claves/timestamps que no consume la UI. `Supplier` hereda de `SupplierCreate`, mezclando actualmente campos de entrada y salida en su definición.
- Los borrados de proveedores y usuarios son respuestas vacías HTTP 204: no serializan un objeto, pero no declaran `response_model`.

El baseline exacto fue `pytest -q`: `no tests ran in 0.05s`, código de salida **5** (0 passed, 0 failed, 0 errors; no se recolectaron tests). En ese momento `tests/` contenía únicamente `__pycache__`, sin ningún `test_*.py`. El baseline real fue cero tests, previo a cualquier cambio.

## 2. Metodología

- Localicé la aplicación en `services/api/main.py` y los routers `auth`, `inventory`, `profiles`, `suppliers` y `users` en `services/api/routes/`.
- Inspeccioné `app.routes`. En el entorno disponible contiene rutas de documentación de Starlette y cinco `_IncludedRouter`, no instancias `APIRoute` directamente. Para recorrer todas las rutas reales, inspeccioné los `APIRoute` de `original_router.routes` de esos routers incluidos y anoté método, path, `response_model` y `endpoint.__module__ + "." + endpoint.__name__`.
- Busqué paths y llamadas de API en `uis/` y comprobé los componentes, clientes y tipos que leen respuestas. “No encontrado” significa que no hallé un consumidor de esa ruta en `uis/`, no que no pueda existir un consumidor externo.
- Revisé `skills/`, `skills/code-review/`, `.agents/skills/`, `.agents/rules/` y `skills-lock.json`. No existe `skills-lock.json` en esta rama. `skills/code-review/` solo contiene `.gitkeep`; no hay una skill de revisión que aplicar. Revisé `.agents/skills/logistics-validator/SKILL.md`, pero no la apliqué: exige `weight_kg` y `destination` para objetos de logística/envíos, campos que no forman parte de los contratos de SKU y movimientos de inventario auditados; añadirlos sería inventar requisitos ajenos al alcance. Revisé `.agents/rules/coding-standards.md`; se aplica a cambios TypeScript/frontend, que no se requieren para conservar los campos leídos por la UI. Por ello, no se aplicó ninguna skill: la inspección de consumidores y schemas se hizo directamente contra el código fuente.
- El Python disponible informó Pydantic **2.13.5**. El activador de `.venv` está restringido por la política de contenido de la organización; no intenté acceder a ese archivo por otro medio. Por tanto, la versión constatada es la del Python disponible, no una afirmación sobre un entorno virtual inaccesible. Para las propuestas Pydantic v2, la sintaxis pertinente es `model_validate` y `ConfigDict(from_attributes=True)` cuando se valide desde atributos ORM.
- Tras la aprobación del usuario, la Fase 2 se ejecutó por router en este orden: auth, users, profiles, suppliers, inventory. La Fase 3 se verificó como se describe a continuación.

## 3. Criterios de clasificación

- **✅ Ya serializado:** tiene `response_model` explícito y la proyección es adecuada al consumidor encontrado.
- **⚠️ Parcialmente serializado:** tiene un modelo incompleto/excesivo o requiere una excepción documentada. Los endpoints 204 sin cuerpo se incluyen aquí: no serializan datos, pero conviene declarar explícitamente la excepción y mantener el 204.
- **❌ Sin serializar:** devuelve un dict sin `response_model`, aunque el contenido actual sea un mensaje.

Las columnas `Estado final` describen el resultado aplicado; los 25 endpoints figuran como ✅ y se mantienen los estados originales sin cambios.

## 4. Inventario por router

### AUTH

El registro se implementa en `services/api/routes/users.py`, función `register_user`, mediante `POST /users`. Se incluye en esta sección por ser el flujo de registro de autenticación; su fila única está en la tabla USERS para evitar duplicar el endpoint. La respuesta implementada es `MessageResponse` y no incluye email.

| Método | Ruta | Propósito | Consumidor | Respuesta original | Estado original | Esquema entrada | Esquema salida | Estado final |
|---|---|---|---|---|---|---|---|---|
| POST | `/auth/login` | Autenticar y emitir access token | `uis/application/app/login/page.tsx`, `uis/application/app/register/page.tsx`, `uis/backoffice/src/lib/api.ts`: leen `access_token` | `LoginResponse` (`access_token`, `token_type`) | ✅ | `LoginRequest` | `LoginResponse` | ✅ |
| GET | `/auth/me` | Devolver usuario autenticado y perfil | `uis/application/app/account/profile/page.tsx`: `email`, `profile.name/phone/address`; `uis/backoffice/src/app/inventory/layout.tsx`: solo éxito HTTP | `MeResponse` con `Profile` anidado | ⚠️ | Ninguno (Bearer) | `MeResponse` (`email`, perfil mínimo) | ✅ |
| POST | `/auth/forgot-password` | Solicitar recuperación de contraseña | `uis/application/app/forgot-password/page.tsx`: éxito HTTP; ignora el JSON | Sin modelo; dict `{"message": ...}` | ❌ | `ForgotPasswordRequest` (`extra="forbid"`) | `MessageResponse` | ✅ |
| POST | `/auth/reset-password` | Restablecer contraseña con token | `uis/application/app/reset-password/page.tsx`: éxito HTTP y redirección; ignora el JSON | Sin modelo; dict `{"message": ...}` | ❌ | `ResetPasswordRequest` (`extra="forbid"`) | `MessageResponse` | ✅ |
| POST | `/auth/change-password` | Cambiar contraseña autenticada | `uis/application/app/account/change-password/page.tsx`: lee `message` | Sin modelo; dict `{"message": ...}` | ❌ | `ChangePasswordRequest` (`extra="forbid"`) + Bearer | `MessageResponse` | ✅ |

#### Fichas AUTH

##### `GET /auth/me` — `services.api.routes.auth.read_me`

- **Recibe:** identidad autenticada por dependencia; sin body.
- **Devuelve hoy:** `email`, `role` y `profile` (`id`, `user_id`, `name`, `phone`, `address`).
- **Payload objetivo:** `email`; `profile` opcional con `name`, `phone`, `address`.
- **Sobra/riesgo:** `profile.id`, `profile.user_id` y `role` no los lee la UI actual; `user_id` es una clave de relación. Se conserva `email` porque la pantalla de cuenta la muestra.
- **Mejora / relación:** proyección anidada mínima del perfil; no devolver IDs internos en el objeto anidado.
- **Implementación Fase 2:** `MeResponse` devuelve `email` y `ProfilePublic` (`name`, `phone`, `address`); se valida el dict de TinyDB con `ProfilePublic.model_validate`. Se omitieron `role`, `id` y `user_id`; la búsqueda previa en los consumidores de `uis/` no encontró lectura de `role`.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/auth.py`.

##### `POST /auth/forgot-password` — `services.api.routes.auth.forgot_password`

- **Recibe:** `ForgotPasswordRequest.email`.
- **Devuelve hoy:** dict con `message` genérico; no declara modelo de salida.
- **Payload objetivo:** `message: str`, manteniendo una respuesta idéntica exista o no el email.
- **Sobra/sensible:** la respuesta actual no incluye email, pero su forma no está tipada.
- **Mejora / relación:** `MessageResponse` y `response_model` explícito; sin relaciones.
- **Implementación Fase 2:** `response_model=MessageResponse`, con el mensaje genérico igual para email registrado/no registrado.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/auth.py`.

##### `POST /auth/reset-password` — `services.api.routes.auth.reset_password`

- **Recibe:** `ResetPasswordRequest.token`, `new_password`.
- **Devuelve hoy:** dict con `message`; sin modelo declarado.
- **Payload objetivo:** `message: str`.
- **Sobra/sensible:** no debe devolver token, contraseña ni email; hoy el dict solo contiene mensaje.
- **Mejora / relación:** `MessageResponse` y `response_model`; sin relaciones.
- **Implementación Fase 2:** `response_model=MessageResponse`; no se añaden campos de token, email o contraseña.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/auth.py`.

##### `POST /auth/change-password` — `services.api.routes.auth.change_password`

- **Recibe:** `ChangePasswordRequest.current_password`, `new_password` y Bearer.
- **Devuelve hoy:** dict con `message`; sin modelo declarado.
- **Payload objetivo:** `message: str`, que es el campo leído por la UI.
- **Sobra/sensible:** no devolver ninguna de las contraseñas ni datos del usuario.
- **Mejora / relación:** `MessageResponse` y `response_model`; sin relaciones.
- **Implementación Fase 2:** `response_model=MessageResponse`; el body conserva el único campo leído por la UI.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/auth.py`.

### INVENTORY

| Método | Ruta | Propósito | Consumidor | Respuesta original | Estado original | Esquema entrada | Esquema salida | Estado final |
|---|---|---|---|---|---|---|---|---|
| GET | `/inventory/products` | Listar productos y stock calculado | `uis/backoffice/src/app/inventory/products/page.tsx`, órdenes inbound/outbound: `id`, `sku`, `name`, `client_name`, `category`, `reference`, `current_stock` | `list[ProductResponse]` | ✅ | Ninguno | `ProductResponse[]` | ✅ |
| POST | `/inventory/products` | Crear SKU | No encontrado en `uis/` | `ProductResponse` | ✅ | `ProductCreate` (`extra="forbid"`) | `ProductResponse` | ✅ |
| GET | `/inventory/products/{product_id}` | Obtener SKU por ID | No encontrado; `getProductById` solo aparece definido en `uis/backoffice/src/lib/inventory.ts` | `ProductResponse` | ✅ | Path `product_id: int` | `ProductResponse` | ✅ |
| POST | `/inventory/orders/inbound` | Registrar entrada de stock | `uis/backoffice/src/app/inventory/orders/inbound/page.tsx`: espera el éxito, ignora el JSON | `InboundOrderResponse` | ⚠️ | `InboundOrderCreate` (`extra="forbid"`) | `InboundOrderResponse` | ✅ |
| POST | `/inventory/orders/outbound` | Registrar salida de stock | `uis/backoffice/src/app/inventory/orders/outbound/page.tsx`: espera el éxito, ignora el JSON | `OutboundOrderResponse` | ⚠️ | `OutboundOrderCreate` (`extra="forbid"`) | `OutboundOrderResponse` | ✅ |
| GET | `/inventory/orders` | Listar entradas y salidas | `uis/backoffice/src/app/inventory/orders/page.tsx`: `id`, `order_type`, `product.name/sku`, `warehouse`, `quantity`, `created_at`, `user_uuid` | `list[InventoryOrderResponse]` | ⚠️ | Ninguno | `InventoryOrderListItem[]` | ✅ |

#### Fichas INVENTORY

##### `POST /inventory/orders/inbound` — `services.api.routes.inventory.create_inbound_order`

- **Recibe:** `sku_id`, `warehouse`, `quantity` (`InboundOrderCreate`).
- **Devuelve hoy:** `id`, `sku_id`, `warehouse`, `quantity`, `created_at`, `user_uuid`.
- **Payload objetivo:** `id`, `sku_id`, `warehouse`, `quantity`, `created_at`.
- **Sobra/sensible:** la página no lee el body de respuesta; `user_uuid` es un identificador interno y no se consume en esta respuesta.
- **Mejora / relación:** proyección de confirmación de entrada; conservar `sku_id` como referencia escalar, sin anidar el SKU.
- **Implementación Fase 2:** `InboundOrderCreate` prohíbe extras; `InboundOrderResponse` valida atributos ORM y omite `user_uuid`, que no consume el cliente de esta respuesta.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/inventory.py`.

##### `POST /inventory/orders/outbound` — `services.api.routes.inventory.create_outbound_order`

- **Recibe:** `sku_id`, `warehouse`, `quantity`, `exit_type`, `tracking_number` (`OutboundOrderCreate`).
- **Devuelve hoy:** `id`, `sku_id`, `warehouse`, `quantity`, `exit_type`, `tracking_number`, `created_at`, `user_uuid`.
- **Payload objetivo:** `id`, `sku_id`, `warehouse`, `quantity`, `exit_type`, `tracking_number`, `created_at`.
- **Sobra/sensible:** la página ignora el JSON; `user_uuid` no se consume en esta respuesta.
- **Mejora / relación:** proyección de confirmación de salida; mantener `sku_id` escalar, sin objeto de producto.
- **Implementación Fase 2:** `OutboundOrderCreate` prohíbe extras; `OutboundOrderResponse` valida atributos ORM y omite `user_uuid`, que no consume el cliente de esta respuesta.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/inventory.py`.

##### `GET /inventory/orders` — `services.api.routes.inventory.list_orders`

- **Recibe:** sin body.
- **Devuelve hoy:** `id`, `order_type`, `product` (`id`, `sku`, `name`, `client_name`, `category`, `reference`), `warehouse`, `quantity`, `created_at`, `user_uuid` y `user` opcional (`user_uuid`, `email`, `name`).
- **Payload objetivo:** `id`, `order_type`, `product` (`name`, `sku`), `warehouse`, `quantity`, `created_at`, `user_uuid`.
- **Sobra/sensible:** la UI no lee campos del producto salvo `name` y `sku`, ni el objeto `user`; el email tampoco es necesario para la vista. `user_uuid` sí se muestra y debe mantenerse.
- **Mejora / relación:** esquema ligero `InventoryOrderListItem`; producto como proyección anidada `{name, sku}`; no hay objeto `user`; se conserva `user_uuid` porque la UI lo muestra.
- **Implementación Fase 2:** la ruta ya no consulta usuarios/perfiles para crear una relación no consumida; devuelve `InventoryOrderListItem` con los siete campos objetivo.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/inventory.py`, `uis/backoffice/src/lib/inventory.ts` (tipo ajustado a la proyección `{sku, name}`; no se modificaron vistas ni estilos).

### PROFILES

| Método | Ruta | Propósito | Consumidor | Respuesta original | Estado original | Esquema entrada | Esquema salida | Estado final |
|---|---|---|---|---|---|---|---|---|
| GET | `/profiles/me` | Leer perfil propio | No encontrado como llamada directa; la pantalla carga perfil a través de `/auth/me` | `Profile` | ⚠️ | Ninguno (Bearer) | `ProfilePublic` | ✅ |
| PUT | `/profiles/me` | Actualizar perfil propio | `uis/application/app/account/profile/page.tsx`: envía y lee `name`, `phone`, `address` | `Profile` | ⚠️ | `ProfileCreate` (`extra="forbid"`) | `ProfilePublic` | ✅ |
| GET | `/profiles/{profile_id}` | Leer perfil por ID con control de acceso | No encontrado en `uis/` | `Profile` | ⚠️ | Path `profile_id: int` + Bearer | `ProfileDetail` | ✅ |

#### Fichas PROFILES

##### `GET /profiles/me` — `services.api.routes.profiles.read_my_profile`

- **Recibe:** identidad autenticada; sin body.
- **Devuelve hoy:** `id`, `user_id`, `name`, `phone`, `address`.
- **Payload objetivo:** `name`, `phone`, `address`.
- **Sobra/riesgo:** IDs no leídos por un consumidor directo; `user_id` es clave foránea. La UI actual obtiene estos datos desde `/auth/me`.
- **Mejora / relación:** salida pública mínima, sin anidar ni devolver el usuario.
- **Implementación Fase 2:** `ProfilePublic.model_validate` valida el dict TinyDB y devuelve `name`, `phone`, `address`; omite IDs.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/profiles.py`.

##### `PUT /profiles/me` — `services.api.routes.profiles.update_my_profile`

- **Recibe:** `ProfileCreate.name`, `phone`, `address`.
- **Devuelve hoy:** `id`, `user_id`, `name`, `phone`, `address`.
- **Payload objetivo:** `name`, `phone`, `address`, que son los campos que la UI aplica al formulario actualizado.
- **Sobra/riesgo:** `id` y `user_id` no los lee el consumidor; el segundo expone una relación interna.
- **Mejora / relación:** respuesta de actualización con campos del perfil usados; sin objeto anidado.
- **Implementación Fase 2:** `ProfileCreate` prohíbe extras; la salida validada `ProfilePublic` contiene solo `name`, `phone`, `address`.
- **Archivos:** `services/api/models.py`, `services/api/schemas.py`, `services/api/routes/profiles.py`.

##### `GET /profiles/{profile_id}` — `services.api.routes.profiles.read_profile`

- **Recibe:** `profile_id` y Bearer.
- **Devuelve hoy:** `id`, `user_id`, `name`, `phone`, `address`.
- **Payload objetivo:** `id`, `name`, `phone`, `address`.
- **Sobra/riesgo:** no se encontró consumidor en `uis/`; `user_id` revela la clave de propietario sin una necesidad comprobada.
- **Mejora / relación:** respuesta de detalle identificada por `id`; omitir la clave foránea, sin anidar el usuario.
- **Implementación Fase 2:** `ProfileDetail.model_validate` valida dict TinyDB y devuelve `id`, `name`, `phone`, `address`; omite `user_id`.
- **Archivos:** `services/api/schemas.py`, `services/api/routes/profiles.py`.

### SUPPLIERS

| Método | Ruta | Propósito | Consumidor | Respuesta original | Estado original | Esquema entrada | Esquema salida | Estado final |
|---|---|---|---|---|---|---|---|---|
| GET | `/suppliers` | Listar proveedores con filtros opcionales | `uis/application/app/suppliers/page.tsx`: `id`, `name`, `country`, `categories`, `rate_usd`, `status` | `List[Supplier]` | ⚠️ | Query: `country`, `category`, `status`, `search` | `SupplierListItem[]` | ✅ |
| GET | `/suppliers/{supplier_id}` | Obtener proveedor por ID | No encontrado en `uis/` | `Supplier` | ⚠️ | Path `supplier_id: int` | `SupplierPublic` | ✅ |
| POST | `/suppliers` | Crear proveedor | No encontrado en `uis/` | `Supplier` | ⚠️ | `SupplierCreate` (`extra="forbid"`) | `SupplierPublic` | ✅ |
| PATCH | `/suppliers/{supplier_id}/rate` | Actualizar tarifa | No encontrado en `uis/` | `Supplier` | ⚠️ | Path + `SupplierUpdateRate` (`extra="forbid"`) | `SupplierPublic` | ✅ |
| PATCH | `/suppliers/{supplier_id}/status` | Actualizar estado | No encontrado en `uis/` | `Supplier` | ⚠️ | Path + `SupplierUpdateStatus` (`extra="forbid"`) | `SupplierPublic` | ✅ |
| DELETE | `/suppliers/{supplier_id}` | Eliminar proveedor | No encontrado en `uis/` | Sin body, HTTP 204; sin `response_model` | ⚠️ | Path `supplier_id: int` | Ninguno (204) | ✅ Excepción: HTTP 204 sin cuerpo, `response_model=None` |

#### Fichas SUPPLIERS

##### `GET /suppliers` — `services.api.routes.suppliers.get_suppliers`

- **Recibe:** filtros opcionales `country`, `category`, `status`, `search`; identidad autenticada.
- **Devuelve hoy:** lista con `id`, `name`, `country`, `categories`, `rate_usd`, `status`, `updated_at`.
- **Payload objetivo:** `id`, `name`, `country`, `categories`, `rate_usd`, `status`.
- **Sobra/riesgo:** `updated_at` es un timestamp de auditoría que la tabla no lee.
- **Mejora / relación:** esquema ligero propio para listado; no hay relaciones anidadas.
- **Implementación Fase 2:** cada TinyDB dict se valida con `SupplierListItem`; salida: `id`, `name`, `country`, `categories`, `rate_usd`, `status`.
- **Archivos:** `services/api/models.py`, `services/api/routes/suppliers.py`.

##### `GET /suppliers/{supplier_id}` — `services.api.routes.suppliers.get_supplier_by_id`

- **Recibe:** `supplier_id`; identidad autenticada.
- **Devuelve hoy:** `id`, `name`, `country`, `categories`, `rate_usd`, `status`, `updated_at`.
- **Payload objetivo:** `id`, `name`, `country`, `categories`, `rate_usd`, `status`.
- **Sobra/riesgo:** no se halló consumidor en `uis/`; `updated_at` no tiene uso comprobado.
- **Mejora / relación:** proyección explícita de detalle; sin relaciones.
- **Implementación Fase 2:** `SupplierPublic.model_validate` valida el dict TinyDB; salida: `id`, `name`, `country`, `categories`, `rate_usd`, `status`.
- **Archivos:** `services/api/models.py`, `services/api/routes/suppliers.py`.

##### `POST /suppliers` — `services.api.routes.suppliers.create_supplier`

- **Recibe:** `SupplierCreate.name`, `country`, `categories`, `rate_usd`, `status`; identidad autenticada.
- **Devuelve hoy:** los campos de creación más `id` y `updated_at`.
- **Payload objetivo:** `id`, `name`, `country`, `categories`, `rate_usd`, `status`.
- **Sobra/riesgo:** `updated_at` no tiene consumidor encontrado; `Supplier` hereda los campos de `SupplierCreate`, acoplando entrada y salida.
- **Mejora / relación:** esquema de salida independiente, sin timestamp no utilizado; sin relaciones.
- **Implementación Fase 2:** `SupplierCreate` rechaza extras; la salida se valida como `SupplierPublic` sin `updated_at`.
- **Archivos:** `services/api/models.py`, `services/api/routes/suppliers.py`.

##### `PATCH /suppliers/{supplier_id}/rate` — `services.api.routes.suppliers.update_supplier_rate`

- **Recibe:** `supplier_id`, `SupplierUpdateRate.rate_usd`; identidad autenticada.
- **Devuelve hoy:** proveedor completo, incluidos `id` y `updated_at`.
- **Payload objetivo:** `id`, `name`, `country`, `categories`, `rate_usd`, `status`.
- **Sobra/riesgo:** no se encontró consumidor; `updated_at` no se usa en `uis/`.
- **Mejora / relación:** proyección de salida independiente del body de actualización; sin relaciones.
- **Implementación Fase 2:** `SupplierUpdateRate` rechaza extras; salida TinyDB validada por `SupplierPublic`, omite `updated_at`.
- **Archivos:** `services/api/models.py`, `services/api/routes/suppliers.py`.

##### `PATCH /suppliers/{supplier_id}/status` — `services.api.routes.suppliers.update_supplier_status`

- **Recibe:** `supplier_id`, `SupplierUpdateStatus.status`; identidad autenticada.
- **Devuelve hoy:** proveedor completo, incluidos `id` y `updated_at`.
- **Payload objetivo:** `id`, `name`, `country`, `categories`, `rate_usd`, `status`.
- **Sobra/riesgo:** no se encontró consumidor; `updated_at` no se usa en `uis/`.
- **Mejora / relación:** proyección de salida independiente del body de actualización; sin relaciones.
- **Implementación Fase 2:** `SupplierUpdateStatus` rechaza extras; salida TinyDB validada por `SupplierPublic`, omite `updated_at`.
- **Archivos:** `services/api/models.py`, `services/api/routes/suppliers.py`.

##### `DELETE /suppliers/{supplier_id}` — `services.api.routes.suppliers.delete_supplier`

- **Recibe:** `supplier_id` e identidad autenticada; sin body.
- **Devuelve hoy:** `None`, HTTP 204; no hay objeto para serializar ni `response_model`.
- **Payload objetivo:** ninguno; conservar 204.
- **Sobra/riesgo:** no se encontró consumidor en `uis/`; no debe añadirse un cuerpo que cambie el contrato 204.
- **Mejora / relación:** excepción explícita documentada para respuesta sin cuerpo; sin relaciones.
- **Implementación Fase 2:** `response_model=None` explícito; se mantiene HTTP 204 sin cuerpo como excepción justificada.
- **Archivos:** `services/api/routes/suppliers.py`, `docs/serialization-audit.md`.

### USERS

| Método | Ruta | Propósito | Consumidor | Respuesta original | Estado original | Esquema entrada | Esquema salida | Estado final |
|---|---|---|---|---|---|---|---|---|
| POST | `/users` | Registrar usuario y perfil | `uis/application/app/register/page.tsx`: solo comprueba `response.ok`, no lee JSON | `UserResponse` | ⚠️ | `UserCreate` (`extra="forbid"`) | `MessageResponse` | ✅ |
| GET | `/users` | Listar usuarios autenticados | No encontrado en `uis/` | `list[UserResponse]` | ⚠️ | Ninguno (Bearer) | `UserListItem[]` | ✅ |
| GET | `/users/{user_id}` | Obtener usuario por ID | No encontrado en `uis/` | `UserResponse` | ⚠️ | Path `user_id: int` + Bearer | `UserPublic` | ✅ |
| PUT | `/users/{user_id}` | Actualizar usuario | No encontrado en `uis/` | `UserResponse` | ⚠️ | Path + `UserUpdate` (`extra="forbid"`) + Bearer | `UserPublic` | ✅ |
| DELETE | `/users/{user_id}` | Eliminar usuario | No encontrado en `uis/` | Sin body, HTTP 204; sin `response_model` | ⚠️ | Path `user_id: int` + Bearer | Ninguno (204) | ✅ Excepción: HTTP 204 sin cuerpo, `response_model=None` |

#### Fichas USERS

##### `POST /users` — `services.api.routes.users.register_user`

- **Recibe:** `UserCreate.email`, `password`, `name`, `phone`, `address`.
- **Devuelve hoy:** `id`, `email`, `is_active`, `role`, `created_at`; `UserResponse` no incluye `hashed_password`.
- **Payload objetivo:** `message: str`; la UI solo depende del éxito HTTP y después inicia sesión.
- **Sobra/sensible:** el email está expresamente excluido por la regla de respuesta de registro; `created_at`, `is_active` y `role` no se leen en el flujo.
- **Mejora / relación:** `MessageResponse`; no devolver credenciales ni datos del usuario.
- **Implementación Fase 2:** `register_user` crea el usuario y devuelve `MessageResponse(message="Cuenta creada correctamente")`; email, password y hashes no están en la respuesta. `UserCreate` prohíbe campos extra.
- **Archivos:** `services/api/models.py`, `services/api/routes/users.py`, `services/api/schemas.py`.

##### `GET /users` — `services.api.routes.users.get_users`

- **Recibe:** identidad autenticada; sin body.
- **Devuelve hoy:** lista de `id`, `email`, `is_active`, `role`, `created_at`.
- **Payload objetivo propuesto:** `id`, `email`, `is_active`, `role`; `created_at` se omite como timestamp de auditoría sin uso encontrado. No se halló consumidor en `uis/`; confirmar cualquier consumidor externo antes de retirar campos adicionales.
- **Sobra/sensible:** `created_at` no tiene uso comprobado; el email no lo consume una UI actual, pero se conserva provisionalmente como identificador de cuenta del recurso.
- **Mejora / relación:** modelo ligero de listado con campos explícitos; sin relaciones.
- **Implementación Fase 2:** `UserListItem` valida cada dict de TinyDB; incluye `id`, `email`, `is_active`, `role` y omite `created_at`/hash.
- **Archivos:** `services/api/models.py`, `services/api/routes/users.py`.

##### `GET /users/{user_id}` — `services.api.routes.users.get_user`

- **Recibe:** `user_id` e identidad autenticada; sin body.
- **Devuelve hoy:** `id`, `email`, `is_active`, `role`, `created_at`.
- **Payload objetivo propuesto:** `id`, `email`, `is_active`, `role`; omitir `created_at`. No se encontró consumidor de UI; comprobar consumidores externos antes de retirar el email.
- **Sobra/sensible:** timestamp de auditoría no usado; email no aparece en consumidores `uis/`.
- **Mejora / relación:** esquema de detalle explícito; sin relaciones.
- **Implementación Fase 2:** `UserPublic.model_validate` valida el dict de TinyDB y devuelve `id`, `email`, `is_active`, `role`; omite timestamp/hash.
- **Archivos:** `services/api/models.py`, `services/api/routes/users.py`.

##### `PUT /users/{user_id}` — `services.api.routes.users.put_user`

- **Recibe:** `user_id`, campos opcionales `email`, `password`, `role` (`UserUpdate`) e identidad autenticada.
- **Devuelve hoy:** `id`, `email`, `is_active`, `role`, `created_at`.
- **Payload objetivo propuesto:** `id`, `email`, `is_active`, `role`; omitir `created_at`. El email se mantiene provisionalmente para reflejar una actualización de email; no hay consumidor encontrado en `uis/`.
- **Sobra/sensible:** `created_at` no tiene uso comprobado. La respuesta no incluye `hashed_password`.
- **Mejora / relación:** salida independiente y explícita; endurecer el esquema de entrada con `extra="forbid"` sin mezclarlo con la salida.
- **Implementación Fase 2:** `UserUpdate` rechaza claves desconocidas; `UserPublic.model_validate` devuelve `id`, `email`, `is_active`, `role` y filtra timestamp/hash.
- **Archivos:** `services/api/models.py`, `services/api/routes/users.py`.

##### `DELETE /users/{user_id}` — `services.api.routes.users.remove_user`

- **Recibe:** `user_id` e identidad autenticada; sin body.
- **Devuelve hoy:** sin cuerpo, HTTP 204; no hay objeto que serializar ni `response_model`.
- **Payload objetivo:** ninguno; conservar 204.
- **Sobra/riesgo:** no se encontró consumidor en `uis/`; añadir un body alteraría el contrato actual.
- **Mejora / relación:** documentar explícitamente la excepción 204 sin cuerpo; sin relaciones.
- **Implementación Fase 2:** `response_model=None` explícito; se mantiene HTTP 204 sin cuerpo como excepción justificada.
- **Archivos:** `services/api/routes/users.py`, `docs/serialization-audit.md`.

## 5. Cambios realizados en la Fase 2

1. Añadí `MessageResponse` y response models explícitos a forgot/reset/change password; forgot password conserva mensaje genérico y no devuelve email.
2. Separé los modelos de entrada y salida, con `extra="forbid"` en inputs de auth, usuarios, perfiles, proveedores y productos/órdenes de inventario.
3. `/auth/me` devuelve email y perfil limitado a `name`, `phone`, `address`.
4. Las órdenes de inventario omiten `user_uuid` en las confirmaciones y usan una proyección de listado con producto `{name, sku}`; conservan `user_uuid` en el listado por uso de la UI.
5. Los perfiles devuelven proyecciones sin `user_id`.
6. Los proveedores usan modelos de salida explícitos sin `updated_at`, manteniendo los seis campos usados por la tabla.
7. El registro devuelve confirmación sin email; las salidas de usuario excluyen `created_at` y hashes.
8. Las eliminaciones mantienen HTTP 204 sin cuerpo y declaran `response_model=None`; ambas excepciones están documentadas.
9. Se actualizó únicamente `uis/backoffice/src/lib/inventory.ts` para tipar el producto anidado con los dos campos que realmente devuelve y consume la UI; no se modificaron vistas ni estilos.

## CHECKPOINT

Fases 0, 1 y 2 completadas y documentadas; los estados originales permanecen intactos y todos los estados finales están en ✅. La verificación posterior y sus límites se detallan abajo.

## Verificación

### Pruebas automatizadas

| Ejecución | Resultado |
|---|---|
| Baseline, antes de implementar | `pytest -q`: `no tests ran in 0.05s`, código de salida 5; 0 passed, 0 failed, 0 errors. `tests/` no contenía archivos `test_*.py` (solo `__pycache__`). |
| Fase 3, después de añadir contratos | `pytest -q`: 7 passed, 3 warnings, código de salida 0. Los warnings son deprecaciones de `TestClient`/httpx y `FastAPI.on_event`. Se configuró `pythonpath = ["."]` en `pyproject.toml` para que pytest encuentre el paquete `services` desde la raíz del repositorio. |
| Repetición 2026-11-14 | `pytest -q`: **7 passed, 3 warnings in 5.92s**, código de salida 0, con el Python disponible. |

`tests/test_serialization_contracts.py` comprueba los response models (con excepción limitada a los DELETE 204 documentados), las respuestas de registro/login/forgot/reset sin email ni claves de contraseña, respuestas protegidas de auth sin email, rechazo de campos extra, contratos PATCH de proveedores y la proyección `InventoryOrderListItem.product` limitada a `sku` y `name`. Los datos TinyDB son temporales en memoria; inventory se valida inspeccionando los esquemas, sin conexión a Supabase.

**Límite:** el test automatizado consulta `/auth/me` sin autenticar, no comprueba su respuesta autenticada. Esta última se verificó manualmente con curl, pero falta la comprobación automatizada solicitada en la Fase 3.

### Typecheck y arranque del backoffice

Se eliminó la caché generada `uis/backoffice/.next` y se repitió `npm --prefix uis/backoffice run typecheck`: terminó con código 0 y sin diagnósticos. Los errores anteriores estaban en tipos generados dentro de `.next/types/validator.ts` y no reaparecieron tras limpiar ese artefacto; no se detectaron errores de TypeScript en los archivos modificados.

Tras limpiar la caché, `npm --prefix uis/backoffice run dev` quedó listo y `GET /inventory/orders` respondió HTTP 200. No se reprodujo el `SyntaxError` observado durante la Fase 2; la evidencia apunta a un problema transitorio asociado al estado generado anterior, pero no permite atribuirle una causa más específica. La página `uis/backoffice/src/app/inventory/orders/page.tsx` sigue accediendo únicamente a `product.name` y `product.sku`, ambos incluidos en `Pick<SKUProduct, "sku" | "name">`; el typecheck completo pasó.

El 2026-11-14 se repitió `npm --prefix uis/backoffice run typecheck` sin errores y se arrancó el backoffice en un puerto local temporal: `GET /inventory/orders` respondió HTTP 200. El proceso iniciado para la prueba se detuvo.

### Pruebas manuales

Pruebas realizadas por el usuario. Las contraseñas de prueba se ocultaron en las capturas antes de incorporarlas al repositorio; el token de login ya estaba oculto.

| Endpoint y medio | Petición | Respuesta observada | Esquema | Captura |
|---|---|---|---|---|
| `POST /users`, `/docs` | Registro | 201, solo `{"message": ...}`, sin email ni contraseña | `MessageResponse` | [Registro](evidence/01-registro-201.png) |
| `POST /users`, `/docs` | Registro con `"role": "admin"` adicional | 422 `extra_forbidden` en `body.role`; la validación impide crear el usuario | `UserCreate` prohíbe extras | [Campo extra](evidence/02-registro-extra-422.png) |
| `POST /auth/login`, `/docs` | Login JSON | 200 con `access_token` y `token_type: "bearer"`, sin email; token oculto | `LoginResponse` | [Login](evidence/03-login-200.png) |
| `POST /auth/forgot-password`, `/docs` | Email existente | 200, mensaje genérico, `content-length: 89` | `MessageResponse` | [Email existente](evidence/04a-forgot-existe.png) |
| `POST /auth/forgot-password`, `/docs` | Email inexistente | 200, mensaje idéntico y `content-length: 89`; no revela si existe la cuenta mediante la respuesta | `MessageResponse` | [Email inexistente](evidence/04b-forgot-no-existe.png) |
| `GET /auth/me` y `GET /suppliers`, curl con Bearer | Consultas desde terminal | `/auth/me`: `email`, `profile {name, phone, address}`, sin `password`, `id`, `user_id` ni `role`. `/suppliers`: `id`, `name`, `country`, `categories`, `rate_usd`, `status`, sin `updated_at` | `MeResponse` y `SupplierListItem[]` | [Consultas autenticadas](evidence/05-pruebas-token-terminal.png) |

Los endpoints autenticados se probaron por curl debido al hallazgo 1. Por tanto, el listado se verificó por curl, no mediante `/docs`. Según el usuario, el usuario de prueba se eliminó después con `git restore data/suppliers.json`.

## Hallazgos fuera de alcance

1. **Authorize de Swagger y login JSON:** `services/api/security.py` configura `OAuth2PasswordBearer(tokenUrl="/auth/login")`, cuyo flujo password envía formulario; `services/api/routes/auth.py`, función `login`, recibe `LoginRequest` en JSON. Una petición de formulario a `/auth/login` respondió 422. Es preexistente: en `main`, `login(credentials: LoginRequest)` y la configuración OAuth2 ya eran iguales. Recomendación, sin implementar: usar `HTTPBearer` en Swagger o proporcionar un endpoint de token compatible con OAuth2 form.
2. **Lecturas de inventory sin JWT:** OpenAPI no exige autenticación para `GET /inventory/products`, `GET /inventory/products/{product_id}` ni `GET /inventory/orders`, aunque `memory-bank/progress.md` afirma que se protegieron el 2026-11-02. La comparación `git diff main -- services/api/routes/inventory.py` no elimina ningún `Depends(get_current_user)`; las tres funciones tampoco lo declaran en `main`. Es preexistente, no una regresión de esta rama. Riesgo: exposición no autenticada de productos, stock e historial de órdenes. Recomendación, sin implementar: validar el requisito de acceso y proteger las tres lecturas con `Depends(get_current_user)` y pruebas de autorización.

## Criterios de aceptación

Revisados el 2026-11-14; las excepciones documentadas no alteran la columna de clasificación de los endpoints.

- [x] Rama `feature/serialization-audit`: `git branch --show-current`.
- [x] Response models explícitos: `tests/test_serialization_contracts.py`, `test_every_api_route_declares_a_response_model_or_documented_204`; excepciones explícitas en los dos DELETE 204.
- [x] Sin respuestas ORM/TinyDB crudas ni dicts sin tipar: los response models de las tablas de inventario y los esquemas de `services/api/models.py` y `services/api/schemas.py` filtran o validan las respuestas; las excepciones 204 no tienen cuerpo.
- [x] Entrada y salida separadas: inspección de OpenAPI sin esquemas JSON de body reutilizados como respuesta; definiciones en `services/api/models.py` y `services/api/schemas.py`.
- [x] Escrituras restringidas: los 13 esquemas JSON de body en OpenAPI declaran `additionalProperties: false`; rechazo 422 en [registro con campo extra](evidence/02-registro-extra-422.png) y en `tests/test_serialization_contracts.py`.
- [ ] Listados con esquema ligero **propio**: `SupplierListItem`, `UserListItem` e `InventoryOrderListItem` existen, pero `GET /inventory/products` comparte `ProductResponse` con el detalle. Sus siete campos son consumidos por la UI, pero no tiene esquema de listado propio; no se afirma cumplido literalmente el criterio.
- [x] Sin `password`, `hashed_password` ni tokens internos en las respuestas: esquemas de salida en `services/api/models.py` y `services/api/schemas.py`; pruebas de auth en `tests/test_serialization_contracts.py`. El `access_token` de login es el token de acceso requerido por el cliente, no un token interno.
- [x] Registro, login, forgot y reset sin email; `/auth/me` puede devolverlo: `test_auth_responses_do_not_expose_credentials_or_email` y [consulta autenticada](evidence/05-pruebas-token-terminal.png).
- [x] Forgot responde igual exista o no el usuario: [existente](evidence/04a-forgot-existe.png) y [no existente](evidence/04b-forgot-no-existe.png), mismo cuerpo y longitud 89.
- [x] Decisiones sobre relaciones documentadas: fichas AUTH, INVENTORY, PROFILES, SUPPLIERS y USERS de este documento.
- [x] Inventario, estados y verificación documentados: 25 filas con estado final ✅; se conservaron los estados originales.
- [x] Rutas de ficheros citadas comprobadas en el repositorio; funciones y componentes identificados en las tablas y fichas de este documento.
- [x] Pytest supera el baseline: 7 passed frente a 0 tests recolectados; ver tabla de pruebas automatizadas.
- [x] Campos usados por frontend conservados: consumidores identificados en las tablas, `uis/backoffice/src/lib/inventory.ts` y typecheck del backoffice sin errores.
