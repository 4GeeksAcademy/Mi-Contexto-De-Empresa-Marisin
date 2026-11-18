# Inventario real de rutas — Fase 0

Inventario obtenido por introspección de la aplicación durante la Fase 0
(2026-11-17), sin ejecutar su startup ni levantar un servidor.
Entorno de esa ejecución: Python 3.14.2 y FastAPI 0.163.1.
Son 30 operaciones HTTP.

La columna auth indica exclusivamente si el árbol de dependencias contiene
`services.api.security.get_current_user`. Un «no» no significa que los datos
sean públicos ni autoriza a cachearlos: autenticación, usuarios y perfiles
quedan excluidos del proyecto.

Existe otro `get_current_user` en `services/api/auth.py`. La introspección
confirmó que ninguna ruta depende de él. Comparar únicamente con esa función
duplicada produciría falsos negativos en todo el inventario.

## Rutas

| Método | Path | Función | Auth |
|---|---|---|---|
| GET | `/suppliers` | `services.api.routes.suppliers.get_suppliers` | sí |
| GET | `/suppliers/{supplier_id}` | `services.api.routes.suppliers.get_supplier_by_id` | sí |
| POST | `/suppliers` | `services.api.routes.suppliers.create_supplier` | sí |
| PATCH | `/suppliers/{supplier_id}/rate` | `services.api.routes.suppliers.update_supplier_rate` | sí |
| PATCH | `/suppliers/{supplier_id}/status` | `services.api.routes.suppliers.update_supplier_status` | sí |
| DELETE | `/suppliers/{supplier_id}` | `services.api.routes.suppliers.delete_supplier` | sí |
| POST | `/users` | `services.api.routes.users.register_user` | no |
| GET | `/users` | `services.api.routes.users.get_users` | sí |
| GET | `/users/{user_id}` | `services.api.routes.users.get_user` | sí |
| PUT | `/users/{user_id}` | `services.api.routes.users.put_user` | sí |
| DELETE | `/users/{user_id}` | `services.api.routes.users.remove_user` | sí |
| POST | `/auth/login` | `services.api.routes.auth.login` | no |
| GET | `/auth/me` | `services.api.routes.auth.read_me` | sí |
| POST | `/auth/forgot-password` | `services.api.routes.auth.forgot_password` | no |
| POST | `/auth/reset-password` | `services.api.routes.auth.reset_password` | no |
| POST | `/auth/change-password` | `services.api.routes.auth.change_password` | sí |
| GET | `/profiles/me` | `services.api.routes.profiles.read_my_profile` | sí |
| PUT | `/profiles/me` | `services.api.routes.profiles.update_my_profile` | sí |
| GET | `/profiles/{profile_id}` | `services.api.routes.profiles.read_profile` | sí |
| GET | `/inventory/products` | `services.api.routes.inventory.list_products` | no |
| POST | `/inventory/products` | `services.api.routes.inventory.create_product` | sí |
| GET | `/inventory/products/{product_id}` | `services.api.routes.inventory.get_product` | no |
| POST | `/inventory/orders/inbound` | `services.api.routes.inventory.create_inbound_order` | sí |
| POST | `/inventory/orders/outbound` | `services.api.routes.inventory.create_outbound_order` | sí |
| GET | `/inventory/orders` | `services.api.routes.inventory.list_orders` | no |
| POST | `/api/incidents` | `services.api.routes.incidents.post_incident` | no |
| GET | `/api/incidents` | `services.api.routes.incidents.get_incidents` | no |
| GET | `/api/incidents/summary` | `services.api.routes.incidents.get_incidents_summary` | no |
| GET | `/api/incidents/{incident_id}` | `services.api.routes.incidents.get_incident_detail` | no |
| PATCH | `/api/incidents/{incident_id}/status` | `services.api.routes.incidents.patch_incident_status` | no |

Las rutas de documentación `/openapi.json`, `/docs`, `/docs/oauth2-redirect`
y `/redoc` son instancias de `Route`, no `APIRoute`; no son operaciones de
negocio y no se incluyen en la tabla.

## Snippet utilizado

La versión instalada de FastAPI expone los routers incluidos como
`_IncludedRouter`, no como instancias directas de `APIRoute` en `app.routes`.
El snippet utilizado recorre sus `effective_candidates()` para conservar
los paths y las dependencias efectivos. Esta API interna depende de la
versión instalada; revisarla si se cambia FastAPI.

```python
from fastapi.routing import APIRoute
from services.api.main import app
from services.api.security import get_current_user


def depends_on_user(dependant):
    if dependant.call is get_current_user:
        return True
    return any(depends_on_user(child) for child in dependant.dependencies)


routes = []
for route in app.routes:
    if isinstance(route, APIRoute):
        routes.append(route)
    elif type(route).__name__ == "_IncludedRouter":
        routes.extend(route.effective_candidates())

for route in routes:
    methods = ",".join(sorted(route.methods or []))
    authenticated = depends_on_user(route.dependant)
    print(
        f"{methods}\t{route.path}\t{route.endpoint.__name__}\t"
        f"{'sí' if authenticated else 'no'}"
    )
print(f"TOTAL\t{len(routes)}")
```

Para comprobar el duplicado se recorrió el mismo árbol comparando también
la identidad con `services.api.auth.get_current_user`: ninguna coincidencia.
Al cerrar la fase, la política organizacional bloqueó la activación del
entorno. No se intentó eludirla ni repetir la introspección: esta tabla
transcribe la salida ya obtenida correctamente en la misma sesión.
