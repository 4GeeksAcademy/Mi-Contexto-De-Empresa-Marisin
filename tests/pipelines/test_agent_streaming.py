"""Streaming y cancelación del agente de CX (chat por WebSocket), sin LLM, Qdrant ni API.

Se usa el grafo real y el `generate_answer` real del harness; solo se sustituyen
`retrieve()`, el enrutador LLM y el **cliente OpenAI** (se deshace el `_complete` caído de `conftest.py`) por un doble que, con
`stream=True`, devuelve un iterable de deltas con `close()` (como el SDK). Así
se mide el abort de verdad: cuántos deltas se consumieron y si se cerró la
respuesta del modelo.

    python -m pytest tests/pipelines/test_agent_streaming.py
"""

import json
import threading
from types import SimpleNamespace

import pytest

from data.pipelines import rag as rag_pipeline
from services.agent import graph as agent_graph
from services.agent import routing, runner
from services.agent.harness import generation as agent_generation

QUESTION = "¿Cuál es la ventana de devolución estándar?"
CONTEXT = [
    {
        "company": "trackflow",
        "source_document": "returns-policy",
        "section": "Política de Devoluciones › Ventana de devolución estándar",
        "language": "es",
        "chunk_index": 1,
        "text": "Ventana de devolución estándar: 30 días desde la entrega.",
    }
]
DELTAS = ["La ventana", " estándar", " es de", " 30 días", " desde la", " entrega.", "\nFuente:", " Política de Devoluciones"]
ANSWER = "".join(DELTAS)
# `tests/conftest.py` sustituye `_complete` por un LLM caído; aquí se prueba el real con un cliente falso.
REAL_COMPLETE = agent_generation._complete


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class FakeStream:
    """Iterable de chunks con `close()`, como el `Stream` del SDK de OpenAI.

    Con `gate`, antes de entregar el delta k (k ≥ 2) espera a que el consumidor
    haya recibido el anterior: el orden entre hilos queda determinista.
    """

    def __init__(self, deltas, gate=None):
        self.deltas = deltas
        self.gate = gate
        self.consumed = 0
        self.close_calls = 0

    def __iter__(self):
        yield _chunk(None)  # primer chunk del SDK: solo el rol, sin contenido
        for index, delta in enumerate(self.deltas):
            if self.close_calls:
                return
            if self.gate is not None and index > 0:
                assert self.gate.acquire(timeout=5), "el consumidor no recibió el token anterior"
            self.consumed += 1
            yield _chunk(delta)
        yield SimpleNamespace(choices=[])  # chunk final de uso, sin choices

    def close(self):
        self.close_calls += 1


class FakeOpenAI:
    def __init__(self, gate=None):
        self.calls = []
        self.streams = []
        self.gate = gate
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            stream = FakeStream(DELTAS, gate=self.gate)
            self.streams.append(stream)
            return stream
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=ANSWER))])


@pytest.fixture
def llm(monkeypatch):
    client = FakeOpenAI()

    def fake_retrieve(question):
        return [dict(chunk) for chunk in CONTEXT] if "devoluci" in question.lower() else []

    def no_llm_router(question):
        raise RuntimeError("sin LLM en los tests")

    monkeypatch.setattr(rag_pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag_pipeline, "query", lambda *_: pytest.fail("ningún nodo debe llamar a query()"))
    monkeypatch.setattr(routing, "classify_with_llm", no_llm_router)
    monkeypatch.setattr(rag_pipeline, "load_settings", lambda: SimpleNamespace(llm_model="modelo"))
    monkeypatch.setattr(rag_pipeline, "check_models", lambda settings: None)
    monkeypatch.setattr(rag_pipeline, "get_generation_client", lambda: client)
    monkeypatch.setattr(agent_generation, "_complete", REAL_COMPLETE)
    return client


@pytest.fixture
def graph():
    return agent_graph.compile_graph()


def read_trace(directory, run_id):
    return json.loads((directory / f"{run_id}.json").read_text(encoding="utf-8"))


def generated_rag_answer(trace):
    event = next(event for event in trace["events"] if event["node"] == "generate_answer")
    return event["output"]["rag_answer"]


def test_on_token_receives_the_deltas_in_order_and_they_add_up_to_the_rag_answer(graph, llm, tmp_path):
    tokens = []

    result = runner.run_agent(QUESTION, graph=graph, trace_directory=tmp_path, on_token=tokens.append)

    trace = read_trace(tmp_path, result.run_id)
    assert tokens == DELTAS  # sin el chunk de rol ni el de uso (deltas vacíos)
    assert "".join(tokens) == generated_rag_answer(trace) == ANSWER
    assert result.status == "answered"
    assert result.answer == ANSWER
    assert llm.calls[0]["stream"] is True
    assert llm.streams[0].consumed == len(DELTAS)
    assert llm.streams[0].close_calls == 1  # se libera la conexión también al terminar bien


def test_without_on_token_the_run_is_the_same_as_before_and_never_streams(graph, llm, tmp_path):
    result = runner.run_agent(QUESTION, graph=graph, trace_directory=tmp_path)
    streamed = runner.run_agent(QUESTION, graph=agent_graph.compile_graph(), trace_directory=tmp_path,
                                on_token=lambda token: None)

    assert not llm.calls[0].get("stream")
    assert "stream" not in llm.calls[0]
    assert (result.status, result.answer, result.sources) == ("answered", ANSWER, ("rag",))
    assert (streamed.status, streamed.answer, streamed.sources) == (result.status, result.answer, result.sources)
    trace = read_trace(tmp_path, result.run_id)
    assert trace["status"] == "answered"
    assert "cancelled" not in trace


def test_cancelling_after_the_third_delta_closes_the_model_stream_and_stops_the_tokens(graph, llm, tmp_path):
    gate = threading.Semaphore(0)
    llm.gate = gate
    cancel = threading.Event()
    tokens = []

    def on_token(token):
        tokens.append(token)
        if len(tokens) == 3:
            cancel.set()
        gate.release()  # el doble del modelo puede entregar el siguiente delta

    with pytest.raises(runner.AgentRunCancelled) as cancelled:
        runner.run_agent(QUESTION, graph=graph, trace_directory=tmp_path, on_token=on_token, cancel_event=cancel)

    stream = llm.streams[0]
    assert tokens == DELTAS[:3]  # ningún on_token tras la cancelación
    assert stream.close_calls == 1  # se cerró la respuesta HTTP del modelo
    assert stream.consumed < len(DELTAS)  # el modelo dejó de entregar deltas
    assert cancelled.value.tokens_sent == 3
    assert cancelled.value.stream_closed is True
    trace = read_trace(tmp_path, cancelled.value.run_id)
    assert trace["status"] == "interrupted"
    assert trace["cancelled"] == {"tokens_sent": 3, "stream_closed": True}
    assert trace["error"] is None and trace["failed_node"] is None
    assert "compose_answer" not in trace["path"]  # no se ejecutan más nodos


def test_cancelling_before_generate_answer_never_calls_the_generation_llm(graph, monkeypatch, llm, tmp_path):
    cancel = threading.Event()

    def retrieve_then_cancel(question):
        cancel.set()  # el usuario interrumpe mientras se recupera el contexto
        return [dict(chunk) for chunk in CONTEXT]

    monkeypatch.setattr(rag_pipeline, "retrieve", retrieve_then_cancel)
    tokens = []

    with pytest.raises(runner.AgentRunCancelled) as cancelled:
        runner.run_agent(QUESTION, graph=graph, trace_directory=tmp_path, on_token=tokens.append, cancel_event=cancel)

    assert llm.calls == []
    assert tokens == []
    assert cancelled.value.tokens_sent == 0
    assert cancelled.value.stream_closed is False
    trace = read_trace(tmp_path, cancelled.value.run_id)
    assert trace["status"] == "interrupted"
    assert "compose_answer" not in trace["path"]


def test_generate_answer_outside_a_graph_does_not_stream(llm):
    answer = agent_generation.generate_answer(QUESTION, CONTEXT)

    assert answer == ANSWER
    assert "stream" not in llm.calls[0]
    assert llm.streams == []
