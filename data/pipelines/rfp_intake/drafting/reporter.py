"""Avisos de progreso que emiten los nodos del ciclo generador-evaluador.

Los nodos no tocan la base de datos: llaman a un `Reporter` que el runner
implementa sobre el almacén (`runner.StoreReporter`), así el ticket refleja en
tiempo real cada borrador y cada evaluación aunque los departamentos corran en
paralelo. Igual que el LLM, el reporter se fija en cada nodo con
`build_graph(llm, reporter)` (sin `config` de LangGraph: lección de la Parte 1).
"""

from __future__ import annotations

from typing import Any, Protocol


class Reporter(Protocol):
    def generating(self, department_id: str, iteration: int) -> None: ...
    def drafted(self, department_id: str, draft: dict[str, Any]) -> None: ...
    def evaluated(self, department_id: str, evaluation: dict[str, Any], history_entry: dict[str, Any]) -> None: ...
    def finished(self, department_id: str, section: dict[str, Any]) -> None: ...


class NullReporter:
    def generating(self, department_id, iteration):
        pass

    def drafted(self, department_id, draft):
        pass

    def evaluated(self, department_id, evaluation, history_entry):
        pass

    def finished(self, department_id, section):
        pass


class RecordingReporter(NullReporter):
    """Guarda los avisos en orden (tests y `--demo`)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, Any]] = []

    def generating(self, department_id, iteration):
        self.events.append(("generating", department_id, iteration))

    def drafted(self, department_id, draft):
        self.events.append(("drafted", department_id, draft["iteration"]))

    def evaluated(self, department_id, evaluation, history_entry):
        self.events.append(("evaluated", department_id, evaluation["overall_pass"]))

    def finished(self, department_id, section):
        self.events.append(("finished", department_id, section["draft_status"]))
