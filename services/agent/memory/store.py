"""Interfaz explícita de lectura/escritura de la memoria del agente.

Nada se acumula en el system prompt: los nodos del grafo leen y escriben la
memoria **solo** a través de `MemoryStore`.

Claves (con el prefijo `trackflow:agent_memory:`):

* `pending:<conversation_id>` — la propuesta pendiente de una conversación.
  Se crea con "solo si no existe": **nunca hay dos a la vez**.
* `slot:<slot_id>` — un slot consolidado (categoría + ámbito) con sus hechos.
* `approvals:<user_id>:<AAAAMMDD>` — escrituras aprobadas hoy por un usuario.
* `audit` — registro *append-only* de cada propuesta y su resultado.

Política de limpieza (ver `docs/agent-memory/memory-design.md`):

* Caducidad por categoría: `known_incident` 7 días (una huelga es temporal),
  `carrier_rule` 90 días (las coberturas se revisan por trimestre) y
  `b2b_report_preference` 180 días. Volver a confirmar un hecho renueva el plazo.
* Consolidación por slot: un hecho nuevo sobre la misma zona/carrier/cliente
  **sustituye** al anterior; uno idéntico suma una confirmación.
* Tope de 5 hechos por slot y 100 slots por categoría: se expulsa el menos
  reciente.
* Una propuesta pendiente caduca a los 30 minutos: se descarta y se audita.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from .backend import KEY_PREFIX, InMemoryBackend, MemoryBackend, RedisBackend, check_prefix
from .models import (
    CARRIER_ALIASES,
    Actor,
    MemoryCategory,
    MemoryFact,
    MemorySlot,
    PendingProposal,
    fold,
    iso,
    utc_now,
)

logger = logging.getLogger("agent.memory")

BACKEND_ENV = "AGENT_MEMORY_BACKEND"  # "redis" (por defecto) o "memory"
PENDING_TTL = timedelta(minutes=30)
# Redis borra la clave mucho después de la caducidad lógica: así el barrido de limpieza
# siempre llega a auditar la propuesta caducada o el hecho vencido antes de que desaparezca.
REDIS_GRACE = timedelta(days=30)
PENDING_KEY_TTL_SECONDS = int((PENDING_TTL + REDIS_GRACE).total_seconds())
CATEGORY_TTL = {
    MemoryCategory.known_incident: timedelta(days=7),
    MemoryCategory.carrier_rule: timedelta(days=90),
    MemoryCategory.b2b_report_preference: timedelta(days=180),
}
MAX_FACTS_PER_SLOT = 5
MAX_SLOTS_PER_CATEGORY = 100
RECALL_LIMIT = 3
STOPWORDS = {"zona", "ruta", "del", "las", "los", "una", "para", "desde", "hacia", "cliente", "de", "la", "el"}


def normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", fold(text)))


def _words(value: str | None) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(value)) if len(w) >= 3 and w not in STOPWORDS]


class MemoryStore:
    def __init__(
        self,
        backend: MemoryBackend,
        *,
        prefix: str = KEY_PREFIX,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.backend = backend
        self.prefix = check_prefix(prefix)
        self.clock = clock

    def _key(self, *parts: str) -> str:
        return self.prefix + ":".join(parts)

    # ------------------------------------------------------------------ #
    # Auditoría
    # ------------------------------------------------------------------ #
    def audit(self, event: str, **fields: Any) -> dict[str, Any]:
        """Añade una entrada al registro. Nunca se modifica ni se borra una entrada."""
        entry = {"event_id": str(uuid.uuid4()), "at": iso(self.clock()), "event": event}
        entry.update({key: value for key, value in fields.items() if value is not None})
        payload = json.dumps(entry, ensure_ascii=False, default=str)
        self.backend.append_log(self._key("audit"), payload)
        logger.info("agent_memory %s proposal=%s", event, fields.get("proposal_id"))
        return json.loads(payload)

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return [json.loads(row) for row in self.backend.read_log(self._key("audit"), count=limit)]

    # ------------------------------------------------------------------ #
    # Propuestas pendientes (una por conversación)
    # ------------------------------------------------------------------ #
    def new_pending_window(self) -> tuple[str, str]:
        now = self.clock()
        return iso(now), iso(now + PENDING_TTL)

    def get_pending(self, conversation_id: str) -> PendingProposal | None:
        raw = self.backend.get(self._key("pending", conversation_id))
        return PendingProposal.model_validate_json(raw) if raw else None

    def save_pending(self, pending: PendingProposal) -> bool:
        """`False` si la conversación ya tiene una propuesta pendiente."""
        return self.backend.set(
            self._key("pending", pending.conversation_id),
            pending.model_dump_json(),
            ttl_seconds=PENDING_KEY_TTL_SECONDS,
            only_if_absent=True,
        )

    def clear_pending(self, conversation_id: str) -> None:
        self.backend.delete(self._key("pending", conversation_id))

    def is_expired(self, pending: PendingProposal) -> bool:
        return datetime.fromisoformat(pending.expires_at) <= self.clock()

    def list_pending(self) -> list[PendingProposal]:
        items = []
        for key in self.backend.keys(self._key("pending", "")):
            raw = self.backend.get(key)
            if raw:
                items.append(PendingProposal.model_validate_json(raw))
        return items

    # ------------------------------------------------------------------ #
    # Slots y hechos
    # ------------------------------------------------------------------ #
    def _live_facts(self, slot: MemorySlot) -> tuple[list[MemoryFact], list[MemoryFact]]:
        now = self.clock()
        live, expired = [], []
        for fact in slot.facts:
            (live if datetime.fromisoformat(fact.expires_at) > now else expired).append(fact)
        return live, expired

    def get_slot(self, slot_id: str) -> MemorySlot | None:
        raw = self.backend.get(self._key("slot", slot_id))
        if not raw:
            return None
        slot = MemorySlot.model_validate_json(raw)
        live, _ = self._live_facts(slot)
        return slot.model_copy(update={"facts": live}) if live else None

    def _save_slot(self, slot: MemorySlot) -> None:
        if not slot.facts:
            self.backend.delete(self._key("slot", slot.slot_id))
            return
        latest = max(datetime.fromisoformat(f.expires_at) for f in slot.facts) + REDIS_GRACE
        ttl = max(int((latest - self.clock()).total_seconds()), 1)
        self.backend.set(self._key("slot", slot.slot_id), slot.model_dump_json(), ttl_seconds=ttl)

    def list_slots(self) -> list[MemorySlot]:
        slots = []
        for key in self.backend.keys(self._key("slot", "")):
            slot = self.get_slot(key.removeprefix(self._key("slot", "")))
            if slot:
                slots.append(slot)
        return sorted(slots, key=lambda s: s.updated_at, reverse=True)

    def find_fact(self, slot_id: str, fact_key: str) -> MemoryFact | None:
        slot = self.get_slot(slot_id)
        return next((f for f in slot.facts if f.fact_key == fact_key), None) if slot else None

    def is_duplicate(self, slot_id: str, fact_key: str, fact_text: str) -> bool:
        current = self.find_fact(slot_id, fact_key)
        return current is not None and normalized(current.fact) == normalized(fact_text)

    def consolidate_fact(
        self, pending: PendingProposal, fact_text: str, approved_by: Actor
    ) -> tuple[MemoryFact, str, MemoryFact | None]:
        """Escribe un hecho APROBADO en su slot. Devuelve `(hecho, acción, hecho sustituido)`.

        Acción: `created`, `confirmed` (mismo texto: suma una confirmación y renueva
        la caducidad) o `superseded` (misma clave, texto distinto: sustituye).
        """
        now = self.clock()
        draft = pending.draft
        expires_at = iso(now + CATEGORY_TTL[draft.category])
        slot = self.get_slot(pending.slot_id) or MemorySlot(
            slot_id=pending.slot_id,
            category=draft.category,
            carrier=draft.carrier,
            country=draft.country,
            zone=draft.zone if draft.category is MemoryCategory.known_incident else None,
            client=draft.client if draft.category is MemoryCategory.b2b_report_preference else None,
            updated_at=iso(now),
        )
        previous = next((f for f in slot.facts if f.fact_key == pending.fact_key), None)
        others = [f for f in slot.facts if f.fact_key != pending.fact_key]

        if previous and normalized(previous.fact) == normalized(fact_text):
            fact = previous.model_copy(
                update={"confirmations": previous.confirmations + 1, "last_confirmed_at": iso(now), "expires_at": expires_at}
            )
            action, replaced = "confirmed", None
        else:
            fact = MemoryFact(
                fact_id=str(uuid.uuid4()),
                fact_key=pending.fact_key,
                fact=fact_text,
                approved_by=approved_by,
                approved_at=iso(now),
                proposal_id=pending.proposal_id,
                conversation_id=pending.conversation_id,
                last_confirmed_at=iso(now),
                expires_at=expires_at,
            )
            action, replaced = ("superseded", previous) if previous else ("created", None)

        facts = sorted([fact, *others], key=lambda f: f.last_confirmed_at, reverse=True)
        for evicted in facts[MAX_FACTS_PER_SLOT:]:
            self.audit("evicted", slot_id=slot.slot_id, fact_id=evicted.fact_id, fact=evicted.fact,
                       reason=f"más de {MAX_FACTS_PER_SLOT} hechos en el slot")
        self._save_slot(slot.model_copy(update={"facts": facts[:MAX_FACTS_PER_SLOT], "updated_at": iso(now)}))
        return fact, action, replaced

    # ------------------------------------------------------------------ #
    # Lectura para el agente
    # ------------------------------------------------------------------ #
    @staticmethod
    def _mentions(folded_question: str, value: str | None) -> bool:
        words = _words(value)
        return bool(words) and all(w in folded_question for w in words)

    def recall(self, question: str, limit: int = RECALL_LIMIT) -> list[tuple[MemorySlot, MemoryFact]]:
        """Hechos aprobados y vigentes que tocan la pregunta (carrier, zona o cliente que menciona)."""
        folded = fold(question)
        hits: list[tuple[MemorySlot, MemoryFact]] = []
        for slot in self.list_slots():
            carrier_hit = slot.carrier is not None and any(a in folded for a in CARRIER_ALIASES[slot.carrier])
            for fact in slot.facts:
                if slot.category is MemoryCategory.carrier_rule:
                    zone_hit = fact.fact_key != "general" and self._mentions(folded, fact.fact_key.replace("-", " "))
                    relevant = carrier_hit or zone_hit
                elif slot.category is MemoryCategory.known_incident:
                    relevant = self._mentions(folded, slot.zone)
                else:
                    relevant = self._mentions(folded, slot.client)
                if relevant:
                    hits.append((slot, fact))
        hits.sort(key=lambda hit: hit[1].last_confirmed_at, reverse=True)
        return hits[:limit]

    # ------------------------------------------------------------------ #
    # Límite diario por usuario (anti-envenenamiento por volumen)
    # ------------------------------------------------------------------ #
    def _approvals_key(self, actor: Actor) -> str:
        return self._key("approvals", str(actor.user_id), self.clock().strftime("%Y%m%d"))

    def approvals_today(self, actor: Actor) -> int:
        return int(self.backend.get(self._approvals_key(actor)) or 0)

    def count_approval(self, actor: Actor) -> int:
        return self.backend.incr(self._approvals_key(actor), ttl_seconds=2 * 24 * 3600)

    # ------------------------------------------------------------------ #
    # Limpieza
    # ------------------------------------------------------------------ #
    def consolidate(self) -> dict[str, int]:
        """Barrido de limpieza (script `agent_memory_consolidate.py` o cron).

        1. Propuestas pendientes caducadas → se descartan y se auditan como `expired`.
        2. Hechos caducados → se eliminan del slot y se auditan como `expired_fact`.
        3. Más de `MAX_SLOTS_PER_CATEGORY` slots en una categoría → se expulsan los menos recientes.
        """
        report = {"expired_pending": 0, "expired_facts": 0, "evicted_slots": 0, "slots": 0, "facts": 0}
        for pending in self.list_pending():
            if self.is_expired(pending):
                self.clear_pending(pending.conversation_id)
                self.audit("expired", proposal_id=pending.proposal_id, conversation_id=pending.conversation_id,
                           slot_id=pending.slot_id, fact=pending.draft.fact, reason="sin respuesta del usuario")
                report["expired_pending"] += 1

        by_category: dict[MemoryCategory, list[MemorySlot]] = {}
        for key in self.backend.keys(self._key("slot", "")):
            raw = self.backend.get(key)
            if not raw:
                continue
            slot = MemorySlot.model_validate_json(raw)
            live, expired = self._live_facts(slot)
            for fact in expired:
                self.audit("expired_fact", slot_id=slot.slot_id, fact_id=fact.fact_id, fact=fact.fact)
                report["expired_facts"] += 1
            if expired:
                self._save_slot(slot.model_copy(update={"facts": live}))
            if live:
                by_category.setdefault(slot.category, []).append(slot.model_copy(update={"facts": live}))

        for slots in by_category.values():
            slots.sort(key=lambda s: s.updated_at, reverse=True)
            for slot in slots[MAX_SLOTS_PER_CATEGORY:]:
                self.backend.delete(self._key("slot", slot.slot_id))
                self.audit("evicted", slot_id=slot.slot_id, reason=f"más de {MAX_SLOTS_PER_CATEGORY} slots")
                report["evicted_slots"] += 1
            kept = slots[:MAX_SLOTS_PER_CATEGORY]
            report["slots"] += len(kept)
            report["facts"] += sum(len(s.facts) for s in kept)
        return report


# --------------------------------------------------------------------------- #
# Instancia compartida (la API, los scripts y los tests la sustituyen)
# --------------------------------------------------------------------------- #
_store: MemoryStore | None = None


def build_store(backend: str | None = None) -> MemoryStore:
    kind = (backend or os.environ.get(BACKEND_ENV) or "redis").lower()
    if kind == "memory":
        return MemoryStore(InMemoryBackend())
    if kind != "redis":
        raise ValueError(f"{BACKEND_ENV} debe ser 'redis' o 'memory' (no {kind!r})")
    return MemoryStore(RedisBackend())


def get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = build_store()
    return _store


def set_store(store: MemoryStore | None) -> None:
    global _store
    _store = store
