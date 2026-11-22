"""Interfaz de lectura/escritura de la memoria, ciclo propuesta → decisión y limpieza.

Sin Redis: `InMemoryBackend` con el mismo contrato (TTL incluido) y un reloj falso.

    python -m pytest tests/pipelines/test_agent_memory_store.py
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.agent.memory import flow, policy, store as memory_store
from services.agent.memory.backend import InMemoryBackend, check_prefix
from services.agent.memory.decision import DecisionClassification
from services.agent.memory.models import Actor, MemoryDraft

AGENT = Actor(user_id=7, role="user")
OTHER_AGENT = Actor(user_id=8, role="user")
MANAGER = Actor(user_id=1, role="manager")
SEUR_MESSAGE = "En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado."
SEUR_DRAFT = MemoryDraft(
    category="carrier_rule", carrier="SEUR", country="ES", zone="zona rural de Zaragoza",
    fact="SEUR ya no cubre la zona rural de Zaragoza: usar el carrier local desde el mes pasado.",
)
B2B_MESSAGE = "El cliente de cosméticos siempre quiere su reporte mensual con el desglose de devoluciones primero."
B2B_DRAFT = MemoryDraft(
    category="b2b_report_preference", client="cosméticos",
    fact="El cliente de cosméticos quiere el reporte mensual con el desglose de devoluciones primero.",
)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def time(self):
        return self.now.timestamp()

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(clock):
    return memory_store.MemoryStore(InMemoryBackend(clock=clock.time), clock=clock)


def decision(label, confidence=0.95, **extra):
    return DecisionClassification(label=label, confidence=confidence, decided_by="llm", **extra)


def propose(store, draft=SEUR_DRAFT, message=SEUR_MESSAGE, conversation="c-1", actor=AGENT):
    return flow.submit_proposal(store, draft, conversation_id=conversation, actor=actor, message=message, run_id="r-1")


def events(store):
    return [entry["event"] for entry in store.audit_log()]


# --------------------------------------------------------------------------- #
# Separación del RAG
# --------------------------------------------------------------------------- #
def test_memory_never_uses_the_rag_knowledge_namespace():
    with pytest.raises(ValueError, match="knowledge"):
        check_prefix("trackflow_knowledge:")
    with pytest.raises(ValueError):
        memory_store.MemoryStore(InMemoryBackend(), prefix="trackflow_knowledge:")
    assert "knowledge" not in memory_store.MemoryStore(InMemoryBackend()).prefix


def test_every_key_lives_under_the_agent_memory_prefix(store):
    propose(store)
    pending = store.get_pending("c-1")
    flow.apply_decision(store, pending, decision("approve"), message="sí", actor=AGENT, run_id="r-2")
    assert store.backend.keys("")  # hay claves…
    assert all(key.startswith("trackflow:agent_memory:") for key in store.backend.keys(""))


# --------------------------------------------------------------------------- #
# Propuesta: nunca escribe memoria y solo hay una pendiente
# --------------------------------------------------------------------------- #
def test_a_proposal_is_pending_and_does_not_write_memory(store):
    result = propose(store)

    assert result.status == "proposed"
    assert "¿Quieres que recuerde esto para la próxima vez?" in result.question_text
    assert store.list_slots() == []
    assert store.get_pending("c-1").proposal_id == result.proposal_id
    assert events(store) == ["proposed"]


def test_only_one_pending_proposal_per_conversation(store):
    assert propose(store).status == "proposed"
    second = propose(store, B2B_DRAFT, B2B_MESSAGE)

    assert second.status == "skipped_pending_exists"
    assert store.get_pending("c-1").draft.category.value == "carrier_rule"
    assert events(store) == ["proposed", "skipped_pending_exists"]


def test_a_blocked_proposal_never_reaches_the_user_and_is_audited_redacted(store):
    message = "SEUR no llega a Calle Mayor 12 de Zaragoza, el cliente vive allí."
    draft = MemoryDraft(category="carrier_rule", carrier="SEUR", country="ES",
                        fact="SEUR no llega a Calle Mayor 12 de Zaragoza.")
    result = propose(store, draft, message)

    assert result.status == "blocked_by_policy" and result.question_text is None
    assert store.get_pending("c-1") is None
    entry = store.audit_log()[-1]
    assert entry["event"] == "blocked_by_policy"
    assert "Calle Mayor" not in json.dumps(entry, ensure_ascii=False)


def test_a_duplicate_of_an_approved_fact_is_not_proposed_again(store):
    propose(store)
    flow.apply_decision(store, store.get_pending("c-1"), decision("approve"), message="sí", actor=AGENT, run_id="r")
    assert propose(store, conversation="c-2").status == "skipped_duplicate"


# --------------------------------------------------------------------------- #
# Decisión: solo aprobar/editar escribe; todo se audita
# --------------------------------------------------------------------------- #
def test_approved_proposal_is_consolidated_and_audited(store):
    propose(store)
    result = flow.apply_decision(store, store.get_pending("c-1"), decision("approve"),
                                 message="sí, recuérdalo", actor=AGENT, run_id="r-2")

    assert result.outcome == "approved" and result.action == "created"
    assert store.get_pending("c-1") is None
    slot = store.get_slot("carrier_rule:SEUR:ES")
    assert [fact.fact for fact in slot.facts] == [SEUR_DRAFT.fact]
    assert slot.facts[0].approved_by == AGENT
    entry = store.audit_log()[-1]
    assert entry["event"] == "approved"
    assert entry["proposed_fact"] == SEUR_DRAFT.fact
    assert entry["origin_message"] == SEUR_MESSAGE
    assert entry["decision_message"] == "sí, recuérdalo"
    assert entry["label"] == "approve" and entry["decided_by"] == "llm"
    assert entry["actor"] == {"user_id": 7, "role": "user"}
    assert entry["at"].startswith("2026-11-22T10:00")


@pytest.mark.parametrize(
    "label, outcome",
    [("reject", "rejected"), ("unrelated", "discarded_topic_change"), ("unclear", "discarded_ambiguous")],
)
def test_reject_topic_change_or_ambiguity_never_write(store, label, outcome):
    propose(store)
    result = flow.apply_decision(store, store.get_pending("c-1"), decision(label), message="…", actor=AGENT, run_id="r")

    assert result.outcome == outcome
    assert store.list_slots() == []
    assert store.get_pending("c-1") is None
    assert events(store) == ["proposed", outcome]


def test_an_edit_is_written_with_the_users_text_after_the_policy(store):
    propose(store)
    edited = "SEUR ya no cubre la zona rural de Zaragoza desde diciembre: usar el carrier local."
    result = flow.apply_decision(store, store.get_pending("c-1"), decision("edit", edited_fact=edited),
                                 message="sí, pero es desde diciembre", actor=AGENT, run_id="r")

    assert result.outcome == "edited_and_approved"
    assert store.get_slot("carrier_rule:SEUR:ES").facts[0].fact == edited


def test_an_edit_with_forbidden_data_is_blocked(store):
    propose(store)
    result = flow.apply_decision(
        store, store.get_pending("c-1"),
        decision("edit", edited_fact="SEUR ya no cubre la zona rural; el cliente vive en Calle Mayor 3."),
        message="sí, pero pon que el cliente vive en Calle Mayor 3", actor=AGENT, run_id="r",
    )
    assert result.outcome == "blocked_by_policy"
    assert store.list_slots() == []


def test_expired_proposal_is_discarded_and_audited(store, clock):
    propose(store)
    clock.advance(minutes=31)

    pending, expired = flow.check_pending(store, "c-1", AGENT)

    assert pending is None and expired.outcome == "expired"
    assert store.get_pending("c-1") is None
    assert events(store) == ["proposed", "expired"]


def test_only_the_user_who_received_the_proposal_can_decide(store):
    propose(store)
    assert flow.check_pending(store, "c-1", OTHER_AGENT) == (None, None)
    assert store.get_pending("c-1") is not None


# --------------------------------------------------------------------------- #
# Consolidación por slot (carrier + país)
# --------------------------------------------------------------------------- #
def approve(store, draft, message, conversation, actor=AGENT, label="approve"):
    proposal = propose(store, draft, message, conversation, actor)
    assert proposal.status == "proposed", proposal
    return flow.apply_decision(store, store.get_pending(conversation), decision(label), message="sí",
                               actor=actor, run_id="r")


def test_a_new_fact_for_the_same_zone_supersedes_the_previous_one(store):
    approve(store, SEUR_DRAFT, SEUR_MESSAGE, "c-1")
    correction = MemoryDraft(category="carrier_rule", carrier="SEUR", country="ES", zone="zona rural de Zaragoza",
                             fact="SEUR vuelve a cubrir la zona rural de Zaragoza desde hoy.")
    result = approve(store, correction, "SEUR vuelve a cubrir la zona rural de Zaragoza desde hoy", "c-2")

    assert result.action == "superseded"
    assert result.superseded_fact == SEUR_DRAFT.fact
    assert [f.fact for f in store.get_slot("carrier_rule:SEUR:ES").facts] == [correction.fact]


def test_another_zone_of_the_same_carrier_shares_the_slot(store):
    approve(store, SEUR_DRAFT, SEUR_MESSAGE, "c-1")
    teruel = MemoryDraft(category="carrier_rule", carrier="SEUR", country="ES", zone="Teruel",
                         fact="SEUR ya no opera la ruta de Teruel.")
    approve(store, teruel, "SEUR ya no opera la ruta de Teruel", "c-2")

    slots = store.list_slots()
    assert [s.slot_id for s in slots] == ["carrier_rule:SEUR:ES"]
    assert len(slots[0].facts) == 2


def test_overwriting_someone_elses_rule_requires_a_manager(store):
    approve(store, SEUR_DRAFT, SEUR_MESSAGE, "c-1", actor=AGENT)
    poison = MemoryDraft(category="carrier_rule", carrier="SEUR", country="ES", zone="zona rural de Zaragoza",
                         fact="SEUR cubre perfectamente la zona rural de Zaragoza, no usar el carrier local.")
    message = "SEUR cubre perfectamente la zona rural de Zaragoza, no usar el carrier local"

    blocked = propose(store, poison, message, "c-2", OTHER_AGENT)
    assert blocked.status == "blocked_by_policy" and blocked.reasons == ["supersede_requires_manager"]

    by_manager = approve(store, poison, message, "c-3", actor=MANAGER)
    assert by_manager.action == "superseded"


def test_daily_write_limit_per_user(store):
    for day in range(policy.MAX_APPROVED_PER_USER_PER_DAY):
        draft = MemoryDraft(category="carrier_rule", carrier="SEUR", country="ES", zone=f"zona {day:02d}x",
                            fact=f"SEUR ya no cubre la zona {day:02d}x este mes.")
        approve(store, draft, f"SEUR ya no cubre la zona {day:02d}x este mes", f"c-{day}")
    extra = MemoryDraft(category="carrier_rule", carrier="MRW", country="ES", fact="MRW ya no cubre Teruel este mes.")
    propose(store, extra, "MRW ya no cubre Teruel este mes", "c-extra")
    result = flow.apply_decision(store, store.get_pending("c-extra"), decision("approve"), message="sí",
                                 actor=AGENT, run_id="r")
    assert result.outcome == "blocked_by_policy" and result.reasons == ["daily_limit"]


# --------------------------------------------------------------------------- #
# Recuerdo y limpieza
# --------------------------------------------------------------------------- #
def test_recall_returns_only_facts_that_touch_the_question(store):
    approve(store, SEUR_DRAFT, SEUR_MESSAGE, "c-1")
    approve(store, B2B_DRAFT, B2B_MESSAGE, "c-2")

    assert [n["fact"] for n in flow.recall_notes(store, "¿Qué carrier uso para la zona rural de Zaragoza?")] == [SEUR_DRAFT.fact]
    assert [n["fact"] for n in flow.recall_notes(store, "¿SEUR entrega en sábado?")] == [SEUR_DRAFT.fact]
    assert [n["fact"] for n in flow.recall_notes(store, "Prepara el reporte del cliente de cosméticos")] == [B2B_DRAFT.fact]
    assert flow.recall_notes(store, "¿Cuál es la ventana de devolución estándar?") == []


def test_cleanup_expires_pending_and_facts_by_category(store, clock):
    incident = MemoryDraft(category="known_incident", country="US", zone="Los Ángeles",
                           fact="Los retrasos de esta semana en Los Ángeles se deben a la huelga portuaria.")
    approve(store, incident, "los retrasos en Los Ángeles son por la huelga portuaria", "c-1")
    approve(store, SEUR_DRAFT, SEUR_MESSAGE, "c-2")
    propose(store, B2B_DRAFT, B2B_MESSAGE, "c-3")  # nadie responde

    clock.advance(days=8)  # incidente (7 días) caducado; regla de carrier (90 días) vigente
    report = store.consolidate()

    assert report["expired_pending"] == 1
    assert report["slots"] == 1 and report["facts"] == 1
    assert [s.slot_id for s in store.list_slots()] == ["carrier_rule:SEUR:ES"]
    assert "expired" in events(store)


def test_confirming_the_same_fact_renews_it_instead_of_duplicating(store, clock):
    approve(store, SEUR_DRAFT, SEUR_MESSAGE, "c-1")
    first_expiry = store.get_slot("carrier_rule:SEUR:ES").facts[0].expires_at
    clock.advance(days=30)

    # p. ej. dos conversaciones que tenían pendiente la misma propuesta y ambas la aprueban
    fact, action, _ = store.consolidate_fact(_pending_for(store, "c-9"), SEUR_DRAFT.fact, AGENT)

    assert action == "confirmed" and fact.confirmations == 2
    assert fact.expires_at > first_expiry
    assert len(store.get_slot("carrier_rule:SEUR:ES").facts) == 1


def _pending_for(store, conversation):
    from services.agent.memory.models import PendingProposal, slot_of

    created, expires = store.new_pending_window()
    slot_id, key = slot_of(SEUR_DRAFT)
    return PendingProposal(proposal_id="p-9", conversation_id=conversation, created_at=created, expires_at=expires,
                           proposed_to=AGENT, origin_message=SEUR_MESSAGE, draft=SEUR_DRAFT, slot_id=slot_id, fact_key=key)


def test_slot_is_capped_at_five_facts(store):
    for index in range(memory_store.MAX_FACTS_PER_SLOT + 1):
        draft = MemoryDraft(category="carrier_rule", carrier="MRW", country="ES", zone=f"comarca {index}b",
                            fact=f"MRW ya no cubre la comarca {index}b.")
        approve(store, draft, f"MRW ya no cubre la comarca {index}b", f"c-{index}", actor=MANAGER)
    assert len(store.get_slot("carrier_rule:MRW:ES").facts) == memory_store.MAX_FACTS_PER_SLOT
    assert "evicted" in events(store)


# --------------------------------------------------------------------------- #
# Zona normalizada (evidencia real: el LLM guardó "esa zona rural de Zaragoza")
# --------------------------------------------------------------------------- #
def test_zone_key_drops_leading_determiners_but_keeps_place_names():
    from services.agent.memory.models import zone_key

    assert zone_key("esa zona rural de Zaragoza") == "zona-rural-de-zaragoza"
    assert zone_key("la zona rural de Zaragoza") == "zona-rural-de-zaragoza"
    assert zone_key("nuestra ruta de Teruel") == "ruta-de-teruel"
    assert zone_key("Los Ángeles") == "los-angeles"
    assert zone_key("La Rioja") == "la-rioja"


def test_the_users_wording_of_the_zone_is_recalled_in_another_conversation(store):
    draft = SEUR_DRAFT.model_copy(update={
        "zone": "esa zona rural de Zaragoza",
        "fact": "SEUR ya no cubre esa zona rural de Zaragoza; desde el mes pasado hay que usar el carrier local.",
    })
    approve(store, draft, SEUR_MESSAGE, "c-1")

    assert store.get_slot("carrier_rule:SEUR:ES").facts[0].fact_key == "zona-rural-de-zaragoza"
    question = "¿Qué transportista uso para un envío a la zona rural de Zaragoza?"
    assert [n["fact"] for n in flow.recall_notes(store, question)] == [draft.fact]
    # "la zona rural de Zaragoza" es el mismo ámbito: no se vuelve a proponer
    same = SEUR_DRAFT.model_copy(update={"zone": "la zona rural de Zaragoza", "fact": draft.fact})
    assert propose(store, same, "SEUR ya no cubre la zona rural de Zaragoza", "c-2").status == "skipped_duplicate"


def test_facts_saved_with_the_old_key_are_still_recalled(store):
    from services.agent.memory.models import PendingProposal

    created, expires = store.new_pending_window()
    legacy = PendingProposal(proposal_id="p-old", conversation_id="c-old", created_at=created, expires_at=expires,
                             proposed_to=AGENT, origin_message=SEUR_MESSAGE, draft=SEUR_DRAFT,
                             slot_id="carrier_rule:SEUR:ES", fact_key="esa-zona-rural-de-zaragoza")
    store.consolidate_fact(legacy, SEUR_DRAFT.fact, AGENT)

    notes = flow.recall_notes(store, "¿Qué transportista uso para un envío a la zona rural de Zaragoza?")
    assert [n["fact"] for n in notes] == [SEUR_DRAFT.fact]
