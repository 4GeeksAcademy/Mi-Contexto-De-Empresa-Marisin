"""Declaración y validación estructural del grafo, sin depender de LangGraph.

`StateGraph.compile()` de LangGraph 1.2 rechaza aristas hacia nodos que no
existen y grafos sin punto de entrada, pero **acepta** nodos a los que nunca se
llega y nodos que nunca llegan a `END`. `validate_structure()` cubre esos
huecos antes de compilar y reúne todos los problemas en un único
`GraphStructureError` legible, para que el fallo ocurra al arrancar la API y no
en una petición en producción.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints

# Mismos valores que `langgraph.graph.START` / `END` (lo comprueba un test).
START = "__start__"
END = "__end__"


class GraphStructureError(ValueError):
    """El grafo del agente no se puede compilar tal como está declarado."""


@dataclass(frozen=True)
class ConditionalEdge:
    """Arista condicional: `router(state)` devuelve una etiqueta de `targets`."""

    router: Callable[..., str]
    targets: dict[str, str]


@dataclass(frozen=True)
class GraphSpec:
    """El grafo como datos: estado, nodos, aristas fijas y aristas condicionales."""

    state_schema: type
    nodes: dict[str, Callable[..., Any]]
    edges: tuple[tuple[str, str], ...] = ()
    conditional: dict[str, ConditionalEdge] = field(default_factory=dict)


def successors(spec: GraphSpec) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {name: set() for name in [START, *spec.nodes, END]}
    for source, target in spec.edges:
        graph.setdefault(source, set()).add(target)
    for source, edge in spec.conditional.items():
        graph.setdefault(source, set()).update(edge.targets.values())
    return graph


def _reachable(graph: dict[str, set[str]], origin: str) -> set[str]:
    seen, pending = {origin}, deque([origin])
    while pending:
        for nxt in graph.get(pending.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                pending.append(nxt)
    return seen


def _state_errors(spec: GraphSpec) -> list[str]:
    try:
        keys = set(get_type_hints(spec.state_schema))
    except Exception as exc:  # anotaciones irresolubles, tipo no válido…
        return [f"El estado {spec.state_schema!r} no tiene anotaciones válidas: {exc}"]
    if not keys:
        return [f"El estado {getattr(spec.state_schema, '__name__', spec.state_schema)} no declara ninguna clave."]
    clashes = sorted(keys & set(spec.nodes))
    return [f"Los nodos {clashes} se llaman igual que claves del estado."] if clashes else []


def validate_structure(spec: GraphSpec) -> None:
    """Lanza `GraphStructureError` con todos los problemas encontrados."""
    errors = _state_errors(spec)
    nodes = set(spec.nodes)

    if not nodes:
        errors.append("El grafo no tiene nodos.")
    for name, action in spec.nodes.items():
        if name in (START, END):
            errors.append(f"'{name}' es un nombre reservado de LangGraph.")
        if not callable(action):
            errors.append(f"El nodo '{name}' no es invocable.")

    for source, target in spec.edges:
        if source == END or (source not in nodes and source != START):
            errors.append(f"Arista '{source}' → '{target}': el origen no es un nodo.")
        if target == START or (target not in nodes and target != END):
            errors.append(f"Arista '{source}' → '{target}': el destino no es un nodo.")

    fixed_sources = {source for source, _ in spec.edges}
    for source, edge in spec.conditional.items():
        if source not in nodes:
            errors.append(f"Arista condicional desde '{source}': el origen no es un nodo.")
        if source in fixed_sources:
            errors.append(f"'{source}' tiene a la vez una arista fija y una condicional.")
        if not callable(edge.router):
            errors.append(f"El router de '{source}' no es invocable.")
        if not edge.targets:
            errors.append(f"La arista condicional desde '{source}' no tiene destinos.")
        for label, target in edge.targets.items():
            if target not in nodes and target != END:
                errors.append(f"Arista condicional '{source}' --{label}--> '{target}': el destino no es un nodo.")

    entry_points = [target for source, target in spec.edges if source == START]
    if len(entry_points) != 1:
        errors.append(f"Debe haber exactamente una arista desde START (hay {len(entry_points)}).")

    graph = successors(spec)
    unreachable = sorted(nodes - _reachable(graph, START))
    if unreachable:
        errors.append(f"Nodos sin conexión desde START (nunca se ejecutarían): {unreachable}.")

    predecessors: dict[str, set[str]] = {name: set() for name in graph}
    for source, targets in graph.items():
        for target in targets:
            predecessors.setdefault(target, set()).add(source)
    dead_ends = sorted(nodes - _reachable(predecessors, END))
    if dead_ends:
        errors.append(f"Nodos desde los que no se llega a END (la corrida no terminaría): {dead_ends}.")

    if errors:
        raise GraphStructureError("Estructura del grafo inválida:\n- " + "\n- ".join(errors))
