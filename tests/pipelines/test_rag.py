"""Pruebas unitarias del RAG de TrackFlow (Hito 7).

Sin Qdrant ni LLM en vivo: `retrieve()` se prueba con un cliente Qdrant
simulado y `query()` con `retrieve()` y el LLM de generación simulados.

    python -m pytest tests/pipelines/test_rag.py
"""

from types import SimpleNamespace

import pytest

from data.pipelines import rag as pipeline
from data.process import rag as process

CHUNKS = [
    {
        "company": "trackflow",
        "source_document": "returns-policy",
        "section": "Política de Devoluciones › Ventana de devolución estándar",
        "language": "es",
        "chunk_index": 1,
        "text": "Política de Devoluciones › Ventana de devolución estándar\n"
        "Ventana de devolución estándar: 30 días desde la entrega, salvo que la marca cliente "
        "haya configurado una ventana distinta en su contrato.",
    },
    {
        "company": "trackflow",
        "source_document": "returns-policy",
        "section": "Política de Devoluciones › Costos de devolución",
        "language": "es",
        "chunk_index": 2,
        "text": "Política de Devoluciones › Costos de devolución\nCostos de devolución: el costo del envío "
        "de vuelta lo asume la marca cliente.",
    },
]


# --------------------------------------------------------------------------- #
# Dobles de prueba
# --------------------------------------------------------------------------- #
class StubQdrant:
    """Cliente Qdrant simulado: devuelve los puntos dados, ordenados por score."""

    def __init__(self, scored):
        self.scored = scored
        self.calls = []

    def query_points(self, *, collection_name, query, limit, with_payload):
        self.calls.append({"collection_name": collection_name, "query": query, "limit": limit})
        points = [SimpleNamespace(score=score, payload=payload) for score, payload in self.scored][:limit]
        return SimpleNamespace(points=points)


class StubLLM:
    """Cliente OpenAI-compatible simulado para chat y embeddings."""

    def __init__(self, answer="Respuesta redactada por el modelo."):
        self.answer = answer
        self.chat_calls = []
        self.embedding_calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answer))])

    def _embed(self, **kwargs):
        self.embedding_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])


@pytest.fixture(autouse=True)
def models_env(monkeypatch):
    monkeypatch.setenv("LLM_API_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "chat-model-test")
    monkeypatch.setenv("EMBEDDING_MODEL", "embedding-model-test")
    monkeypatch.delenv("EMBEDDING_API_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)


@pytest.fixture
def stub_embed(monkeypatch):
    seen = []

    def fake_embed(text):
        seen.append(text)
        return [0.0, 1.0, 0.0]

    monkeypatch.setattr(pipeline, "embed", fake_embed)
    return seen


# --------------------------------------------------------------------------- #
# retrieve()
# --------------------------------------------------------------------------- #
def test_retrieve_excludes_results_below_min_score(monkeypatch, stub_embed):
    client = StubQdrant([(0.91, CHUNKS[0]), (0.74, CHUNKS[1]), (0.41, {"text": "ruido"}), (0.2, {"text": "x"})])
    monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: client)

    results = pipeline.retrieve("¿Cuál es la ventana de devolución estándar?", k=4, min_score=0.6)

    assert results == [CHUNKS[0], CHUNKS[1]]
    assert all(isinstance(result, dict) for result in results)


def test_retrieve_can_return_fewer_than_k_or_none(monkeypatch, stub_embed):
    client = StubQdrant([(0.55, CHUNKS[0]), (0.30, CHUNKS[1])])
    monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: client)

    assert pipeline.retrieve("pregunta", k=5, min_score=0.5) == [CHUNKS[0]]
    assert pipeline.retrieve("pregunta", k=5, min_score=0.9) == []


def test_retrieve_embeds_the_question_and_searches_the_briefing_collection(monkeypatch, stub_embed):
    client = StubQdrant([(0.9, CHUNKS[0])])
    monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: client)

    pipeline.retrieve("¿Quién paga la devolución?", k=3, min_score=0.5)

    assert stub_embed == ["¿Quién paga la devolución?"]
    assert client.calls == [{"collection_name": "trackflow_knowledge", "query": [0.0, 1.0, 0.0], "limit": 3}]


def test_retrieve_returns_payload_dicts_not_sdk_objects(monkeypatch, stub_embed):
    client = StubQdrant([(0.9, CHUNKS[0])])
    monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: client)

    [result] = pipeline.retrieve("ventana", min_score=0.5)

    assert type(result) is dict
    assert set(result) >= {"source_document", "section", "company", "language", "chunk_index", "text"}
    assert "score" not in result


def test_retrieve_ignores_empty_questions(monkeypatch, stub_embed):
    monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: pytest.fail("no debe consultar Qdrant"))
    assert pipeline.retrieve("   ") == []
    assert stub_embed == []


# --------------------------------------------------------------------------- #
# query() y generate_answer()
# --------------------------------------------------------------------------- #
def test_query_returns_the_generation_model_output(monkeypatch):
    llm = StubLLM("La ventana estándar es de 30 días desde la entrega.\nFuente: returns-policy")
    monkeypatch.setattr(pipeline, "retrieve", lambda question: CHUNKS)
    monkeypatch.setattr(pipeline, "get_generation_client", lambda: llm)

    answer = pipeline.query("¿Cuál es la ventana de devolución estándar?")

    assert answer == "La ventana estándar es de 30 días desde la entrega.\nFuente: returns-policy"
    assert len(llm.chat_calls) == 1


def test_query_never_returns_raw_chunk_text(monkeypatch):
    llm = StubLLM("Respuesta generada.")
    monkeypatch.setattr(pipeline, "retrieve", lambda question: CHUNKS)
    monkeypatch.setattr(pipeline, "get_generation_client", lambda: llm)

    answer = pipeline.query("¿Quién paga el envío de vuelta?")

    assert answer == "Respuesta generada."
    assert all(chunk["text"] not in answer for chunk in CHUNKS)
    # El contexto llega al modelo dentro del prompt, no al cliente.
    user_message = llm.chat_calls[0]["messages"][-1]["content"]
    assert CHUNKS[0]["text"] in user_message and CHUNKS[1]["text"] in user_message


def test_query_is_retrieve_plus_generate_answer(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "retrieve", lambda question: calls.append(("retrieve", question)) or CHUNKS)
    monkeypatch.setattr(
        pipeline,
        "generate_answer",
        lambda question, context: calls.append(("generate", question, context)) or "ok",
    )

    assert pipeline.query("pregunta") == "ok"
    assert calls == [("retrieve", "pregunta"), ("generate", "pregunta", CHUNKS)]


def test_query_without_context_asks_the_model_to_admit_it(monkeypatch):
    llm = StubLLM("No tengo información suficiente en la base de conocimiento para responder.")
    monkeypatch.setattr(pipeline, "retrieve", lambda question: [])
    monkeypatch.setattr(pipeline, "get_generation_client", lambda: llm)

    answer = pipeline.query("¿Cuál es el horario del almacén los domingos?")

    assert answer.startswith("No tengo información suficiente")
    messages = llm.chat_calls[0]["messages"]
    assert pipeline.NO_CONTEXT_MARKER in messages[-1]["content"]
    assert "no tiene información suficiente" in messages[0]["content"]


def test_generate_answer_uses_the_generation_model_and_the_briefing_voice(monkeypatch):
    llm = StubLLM()
    monkeypatch.setattr(pipeline, "get_generation_client", lambda: llm)

    pipeline.generate_answer("¿Qué transportista cubre Aragón rural?", CHUNKS)

    call = llm.chat_calls[0]
    assert call["model"] == "chat-model-test"
    system = call["messages"][0]["content"]
    assert "vendedor de TrackFlow" in system
    assert "Miguel Torres" in system and "Carlos Vega" in system and "Sofía Ramos" in system
    assert "Black Friday" in system and "Rebajas de enero" in system
    assert "SOLO la información del CONTEXTO" in system


def test_unsupported_figures_flags_numbers_not_in_context():
    assert pipeline.unsupported_figures("La ventana es de 30 días [1].", CHUNKS) == []
    assert pipeline.unsupported_figures("La ventana es de 45 días.", CHUNKS) == ["45"]
    # Un número dado en la propia pregunta no es una cifra inventada.
    question = "¿Descuento para una marca con 60 metros cúbicos al mes?"
    assert pipeline.unsupported_figures("Con 60 metros cúbicos al mes…", CHUNKS, question) == []


def test_default_min_score_is_the_calibrated_threshold():
    assert pipeline.DEFAULT_MIN_SCORE == 0.46


# --------------------------------------------------------------------------- #
# embed(): modelo de embeddings dedicado
# --------------------------------------------------------------------------- #
def test_embed_uses_the_embedding_model_not_the_generation_model(monkeypatch):
    llm = StubLLM()
    monkeypatch.setattr(process, "get_embedding_client", lambda: llm)

    vector = process.embed("  ¿Cuál es la   ventana?\n")

    assert vector == [0.1, 0.2, 0.3]
    assert llm.embedding_calls == [{"model": "embedding-model-test", "input": "¿Cuál es la ventana?"}]


def test_embedding_and_generation_models_must_be_different(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "same-model")
    monkeypatch.setenv("LLM_MODEL", "same-model")
    with pytest.raises(RuntimeError, match="distintos"):
        process.check_models(process.load_settings())


# --------------------------------------------------------------------------- #
# Chunking de la base de conocimiento real (docs/company-knowledge-base/)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def chunks():
    return process.build_chunks()


def test_each_briefing_document_produces_at_least_3_chunks(chunks):
    per_document = {}
    for chunk in chunks:
        per_document[chunk["source_document"]] = per_document.get(chunk["source_document"], 0) + 1
    assert set(per_document) == {"sla-delivery", "returns-policy", "carrier-coverage", "storage-pricing"}
    assert all(count >= 3 for count in per_document.values())


def test_chunks_carry_the_briefing_payload(chunks):
    for chunk in chunks:
        assert set(chunk) == {"company", "source_document", "section", "language", "chunk_index", "text"}
        assert chunk["company"] == "trackflow"
        assert chunk["language"] == "es"
        assert chunk["section"] and chunk["text"].startswith(chunk["section"])


def test_chunks_never_cut_a_sentence_or_a_rule(chunks):
    for chunk in chunks:
        body = chunk["text"].split("\n", 1)[1].rstrip()
        assert body.endswith("."), chunk["text"]
        assert not body.endswith(":")
    process_steps = next(c for c in chunks if c["source_document"] == "returns-policy" and c["chunk_index"] == 0)
    assert all(step in process_steps["text"] for step in ("1. ", "2. ", "3. "))
    pricing = next(c for c in chunks if c["source_document"] == "storage-pricing" and c["chunk_index"] == 0)
    assert "18 USD" in pricing["text"] and "16 EUR" in pricing["text"] and "150%" in pricing["text"]


def test_point_ids_are_deterministic_and_unique(chunks):
    ids = [process.point_id(chunk) for chunk in chunks]
    assert len(set(ids)) == len(ids)
    assert ids == [process.point_id(chunk) for chunk in process.build_chunks()]


def test_setup_is_idempotent_with_an_in_memory_qdrant(monkeypatch):
    qdrant_client = pytest.importorskip("qdrant_client")
    client = qdrant_client.QdrantClient(":memory:")

    def fake_embed(text):
        return [float((sum(map(ord, text)) * (i + 1)) % 97) + 1.0 for i in range(8)]

    monkeypatch.setattr(process, "embed", fake_embed)
    first = process.setup(client=client)
    second = process.setup(client=client)

    assert first["collection"] == "trackflow_knowledge"
    assert first["chunks"] == second["chunks"] == first["points_in_collection"] == second["points_in_collection"]
    points, _ = client.scroll("trackflow_knowledge", limit=100, with_payload=True)
    assert {p.payload["source_document"] for p in points} == {
        "sla-delivery",
        "returns-policy",
        "carrier-coverage",
        "storage-pricing",
    }
