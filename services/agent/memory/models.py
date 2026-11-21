"""Contratos de la memoria del agente.

Tres categorías, las únicas que el company-BRIEFING de TrackFlow considera
memorizables, cada una con su **ámbito** (slot) de consolidación:

| Categoría               | Slot                                   | Clave del hecho en el slot |
|-------------------------|----------------------------------------|----------------------------|
| `carrier_rule`          | `carrier_rule:<CARRIER>:<PAÍS>`        | zona (o `general`)         |
| `known_incident`        | `known_incident:<PAÍS>:<zona>`         | carrier (o `general`)      |
| `b2b_report_preference` | `b2b_report_preference:<cliente B2B>`  | `report`                   |

Consolidar por carrier + país (sugerencia del BRIEFING) evita que las reglas de
asignación queden repartidas en decenas de entradas sueltas: una corrección
sobre la misma zona **sustituye** a la anterior en lugar de sumarse.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Utilidades de texto
# --------------------------------------------------------------------------- #


def fold(text: str | None) -> str:
    """Minúsculas y sin tildes («Zaragoza» = «zaragoza», «envío» = «envio»)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn"
    )


def slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-") or "general"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Vocabulario de TrackFlow
# --------------------------------------------------------------------------- #


class MemoryCategory(str, Enum):
    carrier_rule = "carrier_rule"
    known_incident = "known_incident"
    b2b_report_preference = "b2b_report_preference"


class Country(str, Enum):
    US = "US"
    ES = "ES"


Carrier = Literal["UPS", "FEDEX", "DHL", "MRW", "SEUR", "LOCAL"]

# Los 8 transportistas de CONTEXT.md: UPS, FedEx y DHL en EE. UU.; MRW, SEUR y DHL
# en España; más dos locales (uno por país, sin nombre en el briefing).
CARRIERS_BY_COUNTRY: dict[str, set[str]] = {
    "US": {"UPS", "FEDEX", "DHL", "LOCAL"},
    "ES": {"MRW", "SEUR", "DHL", "LOCAL"},
}
# Cómo aparece cada carrier en un mensaje (texto plegado).
CARRIER_ALIASES: dict[str, tuple[str, ...]] = {
    "UPS": ("ups",),
    "FEDEX": ("fedex", "fed ex"),
    "DHL": ("dhl",),
    "MRW": ("mrw",),
    "SEUR": ("seur",),
    "LOCAL": ("carrier local", "transportista local", "mensajeria local", "local carrier"),
}

CATEGORY_LABELS = {
    MemoryCategory.carrier_rule: "regla de asignación de carrier",
    MemoryCategory.known_incident: "incidente conocido y recurrente",
    MemoryCategory.b2b_report_preference: "preferencia de reporte de cliente B2B",
}


# --------------------------------------------------------------------------- #
# Actor y propuesta
# --------------------------------------------------------------------------- #


class Actor(BaseModel):
    """Quién habla con el agente (del JWT de la API). Sin nombre ni email: solo id y rol."""

    model_config = ConfigDict(extra="ignore")

    user_id: int
    role: str = "user"

    @classmethod
    def from_user(cls, user: dict[str, Any] | None) -> "Actor | None":
        if not user or user.get("id") is None:
            return None
        return cls(user_id=int(user["id"]), role=str(user.get("role") or "user"))


class MemoryDraft(BaseModel):
    """`memory_proposal`: lo que el modelo propone recordar (campo de su salida estructurada)."""

    model_config = ConfigDict(extra="forbid")

    category: MemoryCategory
    fact: str = Field(min_length=10, max_length=280, description="El hecho, en una frase.")
    carrier: Carrier | None = None
    country: Country | None = None
    zone: str | None = Field(default=None, max_length=60)
    client: str | None = Field(default=None, max_length=60)
    reason: str = Field(default="", max_length=200, description="Por qué vale la pena recordarlo.")

    @field_validator("fact", "zone", "client", "reason", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("carrier", mode="before")
    @classmethod
    def _upper_carrier(cls, value):
        return value.strip().upper().replace(" ", "") if isinstance(value, str) else value

    @field_validator("country", mode="before")
    @classmethod
    def _country(cls, value):
        if not isinstance(value, str):
            return value
        folded = fold(value).strip()
        return {"espana": "ES", "spain": "ES", "es": "ES", "eeuu": "US", "ee. uu.": "US", "usa": "US",
                "us": "US", "estados unidos": "US"}.get(folded, value.strip().upper())


def slot_of(draft: MemoryDraft) -> tuple[str, str]:
    """`(slot_id, clave del hecho)` de una propuesta. Requiere que la política ya la haya validado."""
    if draft.category is MemoryCategory.carrier_rule:
        return f"carrier_rule:{draft.carrier}:{draft.country.value}", slug(draft.zone)
    if draft.category is MemoryCategory.known_incident:
        return f"known_incident:{draft.country.value}:{slug(draft.zone)}", slug(draft.carrier)
    return f"b2b_report_preference:{slug(draft.client)}", "report"


class PendingProposal(BaseModel):
    """Propuesta esperando la decisión del usuario. Como mucho una por conversación."""

    proposal_id: str
    conversation_id: str
    created_at: str
    expires_at: str
    proposed_to: Actor
    origin_run_id: str | None = None
    origin_message: str = Field(description="Mensaje que originó la propuesta, con los datos sensibles redactados.")
    draft: MemoryDraft
    slot_id: str
    fact_key: str
    supersedes: str | None = Field(default=None, description="Hecho aprobado que esta propuesta sustituiría.")
    supersedes_author: int | None = None


class MemoryFact(BaseModel):
    fact_id: str
    fact_key: str
    fact: str
    approved_by: Actor
    approved_at: str
    proposal_id: str
    conversation_id: str
    confirmations: int = 1
    last_confirmed_at: str
    expires_at: str


class MemorySlot(BaseModel):
    slot_id: str
    category: MemoryCategory
    carrier: Carrier | None = None
    country: Country | None = None
    zone: str | None = None
    client: str | None = None
    facts: list[MemoryFact] = []
    updated_at: str


DecisionLabel = Literal["approve", "reject", "edit", "unrelated", "unclear"]

DecisionOutcome = Literal[
    "approved",
    "edited_and_approved",
    "rejected",
    "discarded_topic_change",
    "discarded_ambiguous",
    "blocked_by_policy",
    "expired",
    "memory_unavailable",
]
ProposalStatus = Literal["proposed", "blocked_by_policy", "skipped_pending_exists", "skipped_duplicate", "skipped"]
