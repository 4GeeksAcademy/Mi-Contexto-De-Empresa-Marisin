"""Utilidades compartidas por los tests del flujo RFP (`data/pipelines/rfp_intake/`).

Los Markdown de `fixtures/rfp/` son la conversión con MarkItDown de los tres PDF
de muestra del BRIEFING (`rfp-requests/trackflow/`): formal (ModaViva, aceptar),
informal (Luna Cosmetics, aceptar) e inválido (pitch de RapidShip, rechazar).
Los PDF no se versionan: se suben por la UI (BRIEFING §4).
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "rfp"

FORMAL = "trackflow-request-1.md"
INFORMAL = "trackflow-request-2.md"
INVALID = "trackflow-request-3.md"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def offline_llm(system: str, user: str) -> str:
    raise RuntimeError("sin LLM en los tests")


class ScriptedLLM:
    """Doble del LLM: responde según el agente que llama (se reconoce por su system prompt)."""

    ROLES = (
        ("agente clasificador", "classifier"),
        ("agente de metadatos", "metadata"),
        ("orquestador", "orchestrator"),
        ("Warehouse Operations de TrackFlow", "warehouse"),
        ("Last Mile and Carrier Management de TrackFlow", "lastmile"),
        ("Reverse Logistics de TrackFlow", "reverse"),
        ("synthesizer", "synthesizer"),
    )

    def __init__(self, **responses):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def role(self, system: str) -> str:
        for marker, role in self.ROLES:
            if marker in system:
                return role
        raise AssertionError(f"system prompt desconocido: {system[:80]}")

    def __call__(self, system: str, user: str) -> str:
        role = self.role(system)
        self.calls.append((role, user))
        response = self.responses.get(role)
        if response is None:
            raise RuntimeError(f"sin respuesta para {role}")
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(user)
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)

    def roles_called(self) -> list[str]:
        return [role for role, _ in self.calls]
