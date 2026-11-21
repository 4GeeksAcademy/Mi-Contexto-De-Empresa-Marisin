"""Ciclo propuesta → decisión → consolidación (lo usan los nodos del grafo).

1. `submit_proposal` — el modelo propuso algo (`memory_proposal`): pasa la
   política, se guarda como **pendiente** (una por conversación) y se devuelve
   la pregunta que el agente añade al final de su respuesta. No escribe memoria.
2. `check_pending` — al empezar el turno siguiente: ¿hay una pendiente? Si caducó,
   se descarta y se audita.
3. `apply_decision` — con la clasificación del mensaje: solo `approve`/`edit`
   consolidan; `reject`, `unrelated` y `unclear` descartan.

Cada paso deja una entrada en la auditoría con la propuesta, la decisión, el
mensaje que la originó (redactado), el actor y la marca de tiempo.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from . import policy
from .decision import DecisionClassification
from .models import (
    CATEGORY_LABELS,
    Actor,
    DecisionLabel,
    DecisionOutcome,
    MemoryDraft,
    PendingProposal,
    ProposalStatus,
    slot_of,
)
from .store import MemoryStore


class DecisionResult(BaseModel):
    proposal_id: str
    outcome: DecisionOutcome
    slot_id: str
    proposed_fact: str
    fact: str | None = None
    action: str | None = None
    superseded_fact: str | None = None
    label: DecisionLabel | None = None
    confidence: float | None = None
    decided_by: str | None = None
    reasons: list[str] = []
    expires_at: str | None = None
    message: str


class ProposalResult(BaseModel):
    status: ProposalStatus
    proposal_id: str | None = None
    category: str | None = None
    fact: str | None = None
    slot_id: str | None = None
    expires_at: str | None = None
    supersedes: str | None = None
    reasons: list[str] = []
    question_text: str | None = None


def _date(value: str | None) -> str:
    return (value or "")[:10]


def _actor_fields(actor: Actor | None) -> dict[str, Any] | None:
    return actor.model_dump() if actor else None


# --------------------------------------------------------------------------- #
# 1. Propuesta
# --------------------------------------------------------------------------- #
def proposal_question(pending: PendingProposal) -> str:
    supersedes = f" Sustituiría a la nota actual: «{pending.supersedes}»." if pending.supersedes else ""
    return (
        "---\n"
        f"**¿Quieres que recuerde esto para la próxima vez?** «{pending.draft.fact}» "
        f"({CATEGORY_LABELS[pending.draft.category]}).{supersedes}\n"
        "Responde «sí», «no» o corrígelo. Si no respondes o cambias de tema, no se guardará nada."
    )


def submit_proposal(
    store: MemoryStore,
    draft: MemoryDraft,
    *,
    conversation_id: str | None,
    actor: Actor | None,
    message: str,
    run_id: str | None,
) -> ProposalResult:
    """Valida la propuesta del modelo y la deja pendiente de la decisión del usuario."""
    if not conversation_id or actor is None:
        return ProposalResult(status="skipped", reasons=["no_conversation"])

    audit = {
        "conversation_id": conversation_id,
        "actor": _actor_fields(actor),
        "origin_run_id": run_id,
        "origin_message": policy.redact(message),
        "category": draft.category.value,
    }
    verdict = policy.check_draft(draft, message=message)
    if not verdict.allowed:
        store.audit("blocked_by_policy", proposed_fact=policy.redact(draft.fact), reasons=verdict.reasons, **audit)
        return ProposalResult(status="blocked_by_policy", category=draft.category.value, reasons=verdict.reasons)

    slot_id, fact_key = slot_of(draft)
    if store.is_duplicate(slot_id, fact_key, draft.fact):
        store.audit("skipped_duplicate", proposed_fact=draft.fact, slot_id=slot_id, **audit)
        return ProposalResult(status="skipped_duplicate", slot_id=slot_id, fact=draft.fact)
    if store.get_pending(conversation_id) is not None:
        store.audit("skipped_pending_exists", proposed_fact=draft.fact, slot_id=slot_id, **audit)
        return ProposalResult(status="skipped_pending_exists", slot_id=slot_id, fact=draft.fact)

    previous = store.find_fact(slot_id, fact_key)
    if previous and not policy.may_supersede(actor, previous.approved_by.user_id):
        reasons = ["supersede_requires_manager"]
        store.audit("blocked_by_policy", proposed_fact=draft.fact, slot_id=slot_id, reasons=reasons, **audit)
        return ProposalResult(status="blocked_by_policy", slot_id=slot_id, reasons=reasons)

    created_at, expires_at = store.new_pending_window()
    pending = PendingProposal(
        proposal_id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        created_at=created_at,
        expires_at=expires_at,
        proposed_to=actor,
        origin_run_id=run_id,
        origin_message=policy.redact(message),
        draft=draft,
        slot_id=slot_id,
        fact_key=fact_key,
        supersedes=previous.fact if previous else None,
        supersedes_author=previous.approved_by.user_id if previous else None,
    )
    if not store.save_pending(pending):  # otra petición creó una entre medias
        store.audit("skipped_pending_exists", proposed_fact=draft.fact, slot_id=slot_id, **audit)
        return ProposalResult(status="skipped_pending_exists", slot_id=slot_id, fact=draft.fact)
    store.audit(
        "proposed",
        proposal_id=pending.proposal_id,
        proposed_fact=draft.fact,
        draft=draft.model_dump(mode="json", exclude_none=True),
        slot_id=slot_id,
        supersedes=pending.supersedes,
        expires_at=expires_at,
        **audit,
    )
    return ProposalResult(
        status="proposed",
        proposal_id=pending.proposal_id,
        category=draft.category.value,
        fact=draft.fact,
        slot_id=slot_id,
        expires_at=expires_at,
        supersedes=pending.supersedes,
        question_text=proposal_question(pending),
    )


# --------------------------------------------------------------------------- #
# 2. Pendiente al empezar el turno
# --------------------------------------------------------------------------- #
EXPIRED_MESSAGE = "La propuesta de memoria anterior caducó sin respuesta, así que no la he guardado."


def check_pending(
    store: MemoryStore, conversation_id: str | None, actor: Actor | None
) -> tuple[PendingProposal | None, DecisionResult | None]:
    """`(pendiente, None)`, `(None, resultado "expired")` o `(None, None)`."""
    if not conversation_id:
        return None, None
    pending = store.get_pending(conversation_id)
    if pending is None:
        return None, None
    if actor is None or pending.proposed_to.user_id != actor.user_id:
        return None, None  # solo decide quien recibió la propuesta
    if store.is_expired(pending):
        store.clear_pending(conversation_id)
        store.audit("expired", proposal_id=pending.proposal_id, conversation_id=conversation_id,
                    slot_id=pending.slot_id, proposed_fact=pending.draft.fact, actor=_actor_fields(actor),
                    origin_message=pending.origin_message, reason="sin respuesta del usuario")
        return None, DecisionResult(proposal_id=pending.proposal_id, outcome="expired", slot_id=pending.slot_id,
                                    proposed_fact=pending.draft.fact, message=EXPIRED_MESSAGE)
    return pending, None


# --------------------------------------------------------------------------- #
# 3. Decisión
# --------------------------------------------------------------------------- #
DISCARD_MESSAGES = {
    "rejected": "Entendido: no lo guardo. La memoria del agente no ha cambiado.",
    "discarded_topic_change": (
        "No has respondido a la propuesta de memoria anterior, así que la he descartado sin guardar nada."
    ),
    "discarded_ambiguous": (
        "No me ha quedado claro si querías guardar la propuesta anterior, así que la he descartado sin guardar nada."
    ),
}
OUTCOME_BY_LABEL = {"reject": "rejected", "unrelated": "discarded_topic_change", "unclear": "discarded_ambiguous"}


def apply_decision(
    store: MemoryStore,
    pending: PendingProposal,
    classification: DecisionClassification,
    *,
    message: str,
    actor: Actor,
    run_id: str | None,
) -> DecisionResult:
    base = {
        "proposal_id": pending.proposal_id,
        "slot_id": pending.slot_id,
        "proposed_fact": pending.draft.fact,
        "label": classification.label,
        "confidence": classification.confidence,
        "decided_by": classification.decided_by,
    }
    audit = {
        **base,
        "conversation_id": pending.conversation_id,
        "actor": _actor_fields(actor),
        "origin_run_id": pending.origin_run_id,
        "decision_run_id": run_id,
        "origin_message": pending.origin_message,
        "decision_message": policy.redact(message),
        "classifier_reason": classification.reason,
    }

    if classification.label not in {"approve", "edit"}:
        outcome = OUTCOME_BY_LABEL[classification.label]
        store.clear_pending(pending.conversation_id)
        store.audit(outcome, **audit)
        return DecisionResult(outcome=outcome, message=DISCARD_MESSAGES[outcome], **base)

    fact_text = (classification.edited_fact or "").strip() if classification.label == "edit" else pending.draft.fact
    reasons: list[str] = []
    if classification.label == "edit":
        reasons = policy.check_edited_fact(fact_text).reasons
    if not reasons and not policy.may_supersede(actor, pending.supersedes_author):
        reasons = ["supersede_requires_manager"]
    if not reasons and store.approvals_today(actor) >= policy.MAX_APPROVED_PER_USER_PER_DAY:
        reasons = ["daily_limit"]
    if reasons:
        store.clear_pending(pending.conversation_id)
        store.audit("blocked_by_policy", reasons=reasons, edited_fact=policy.redact(fact_text), **audit)
        explanation = policy.PolicyVerdict(False, reasons).explanation
        return DecisionResult(outcome="blocked_by_policy", reasons=reasons,
                              message=f"No he guardado la propuesta: {explanation}.", **base)

    fact, action, replaced = store.consolidate_fact(pending, fact_text, actor)
    store.count_approval(actor)
    store.clear_pending(pending.conversation_id)
    outcome = "edited_and_approved" if classification.label == "edit" else "approved"
    store.audit(
        outcome,
        fact=fact.fact,
        fact_id=fact.fact_id,
        action=action,
        superseded_fact=replaced.fact if replaced else None,
        expires_at=fact.expires_at,
        **audit,
    )
    if action == "confirmed":
        text = f"Ya lo tenía en la memoria del agente: «{fact.fact}». He renovado su vigencia hasta el {_date(fact.expires_at)}."
    else:
        text = f"Guardado en la memoria del agente: «{fact.fact}». Lo tendré en cuenta en próximas conversaciones (vigente hasta el {_date(fact.expires_at)})."
        if replaced:
            text += f" Sustituye a la nota anterior: «{replaced.fact}»."
    return DecisionResult(
        outcome=outcome, fact=fact.fact, action=action, superseded_fact=replaced.fact if replaced else None,
        expires_at=fact.expires_at, message=text, **base,
    )


# --------------------------------------------------------------------------- #
# Lectura para la respuesta
# --------------------------------------------------------------------------- #
MEMORY_SOURCE = "Fuente: memoria del agente (notas aprobadas por el equipo; no forman parte de la base documental)"


def recall_notes(store: MemoryStore, question: str) -> list[dict[str, Any]]:
    return [
        {
            "slot_id": slot.slot_id,
            "category": slot.category.value,
            "fact_id": fact.fact_id,
            "fact": fact.fact,
            "approved_at": fact.approved_at,
            "approved_by": fact.approved_by.model_dump(),
            "confirmations": fact.confirmations,
            "expires_at": fact.expires_at,
        }
        for slot, fact in store.recall(question)
    ]


def notes_section(notes: list[dict[str, Any]]) -> str:
    lines = "\n".join(
        f"- {note['fact']} (aprobada el {_date(note['approved_at'])}, vigente hasta el {_date(note['expires_at'])})"
        for note in notes
    )
    return f"Notas operativas recordadas:\n{lines}\n{MEMORY_SOURCE}"
