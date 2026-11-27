"""ACL de las tools del agente (auditoría OWASP · A01 del carril agente, hallazgo C2).

Las tools de incidencias e inventario devuelven datos **internos** de TrackFlow
(incidencias de todas las sucursales, stock y `client_name` de todas las marcas
B2B). Un cliente (`user`) que habla con el agente no puede usarlas: el nodo
consulta esta política **antes** de cualquier I/O y, si no está permitido, no
llama al servidor MCP.

Roles = frontera de confianza (D8): `user` = cuenta externa; `admin` y
`manager` = personal de TrackFlow. `actor is None` es una ejecución interna sin
HTTP (CLI, evals grabados, scripts): las dos entradas HTTP del agente
(`POST /agent/query` y el gestor de turnos del chat) siempre pasan el usuario
autenticado, así que nunca llegan aquí como `None`.
"""

from __future__ import annotations

from typing import Literal

from ..memory.models import Actor

ToolName = Literal["incidents", "inventory"]

# Mismo conjunto que `services/api/security.STAFF_ROLES`. No se importa de allí
# porque ese módulo exige `JWT_SECRET` al importarse y el grafo también corre
# sin la API (CLI, evals); un test comprueba que ambos coinciden.
STAFF_ROLES = frozenset({"admin", "manager"})

TOOL_ROLES: dict[str, frozenset[str]] = {
    "incidents": STAFF_ROLES,
    "inventory": STAFF_ROLES,
}


def tool_allowed(tool: ToolName, actor: Actor | None) -> bool:
    """¿Puede `actor` usar la tool `tool`? Sin actor = ejecución interna → sí."""
    if actor is None:
        return True
    return actor.role in TOOL_ROLES.get(tool, frozenset())
