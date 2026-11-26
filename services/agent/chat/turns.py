"""Productor único por sesión: arranca cada turno del agente, publica sus tokens y lo interrumpe.

`ChatTurnManager` (un singleton por proceso) guarda
`active[session_id] = Generation(message_id, cancel_event, task, text, sequence)`.
Un turno es `asyncio.to_thread(run_agent, text, conversation_id=session_id,
user=owner, on_token=…, cancel_event=…)`: el agente corre en un hilo y cada token
vuelve al event loop con `call_soon_threadsafe`, donde se numera (`sequence`) y se
publica en `chat.<session_id>`. **El handler WebSocket nunca llama al agente**:
solo reenvía comandos aquí y lee su cola del pub/sub. Así N conexiones a la misma
sesión (el cliente y un supervisor) ven los mismos eventos y el agente corre una
vez por turno; si el dueño se desconecta, el turno sigue y se persiste al terminar.

Interrupción (`interrupt_requested` del dueño con turno activo):
1. marca la generación como cancelada y activa `cancel_event` (el modelo cierra su stream);
2. desde ese instante descarta cualquier token tardío de ese `message_id`
   (`dropped_after_abort`, que debe quedarse en 0: `run_agent` ya no reenvía tras el evento);
3. persiste el parcial como `interrupted` y la sesión pasa a `interrupted`;
4. publica `generation_interrupted`;
5. espera al hilo anterior (máx. `INTERRUPT_WAIT_SECONDS`);
6. con `new_input`, empieza un turno nuevo con otro `message_id` (la sesión vuelve a `active`).
El mensaje interrumpido nunca se borra ni se sobrescribe.

Rutas sin LLM (plantillas de tools, guardias, `no_context`, memoria): no hay
tokens; la respuesta final se emite como **un único** `token_chunk` antes de
`generation_completed`, cuyo `answer` (respuesta compuesta y ya pasada por la
guardia de salida) es siempre el texto definitivo.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import runner
from .pubsub import ChatPubSub
from .schemas import (
    EVENT_CHAT_ERROR,
    EVENT_GENERATION_COMPLETED,
    EVENT_GENERATION_INTERRUPTED,
    EVENT_GENERATION_STARTED,
    EVENT_TOKEN_CHUNK,
    EVENT_USER_MESSAGE,
    INTERRUPT_WAIT_SECONDS,
    ActiveGeneration,
    ChatErrorData,
    ChatMessage,
    GenerationCompletedData,
    GenerationInterruptedData,
    GenerationStartedData,
    SessionSnapshotData,
    TokenChunkData,
    UserMessageData,
    dump_event,
    new_message_id,
)
from .store import ChatStore, SessionNotFound

logger = logging.getLogger("api.agent.chat")

AGENT_UNAVAILABLE = "El agente de soporte no ha podido completar la respuesta. Inténtalo de nuevo en unos minutos."
INVALID_QUESTION = "El agente no ha podido procesar ese mensaje."

TurnRunner = Callable[..., runner.AgentResult]


def run_agent_turn(question: str, *, conversation_id: str, user: dict[str, Any],
                   on_token: Callable[[str], None], cancel_event: threading.Event) -> runner.AgentResult:
    """El turno real: el mismo `run_agent` de `POST /agent/query`, con tokens en vivo y cancelación."""
    return runner.run_agent(question, conversation_id=conversation_id, user=user,
                            on_token=on_token, cancel_event=cancel_event)


def get_turn_runner() -> TurnRunner:
    """Dependencia FastAPI (sobreescribible en tests con un runner falso)."""
    return run_agent_turn


class GenerationInProgress(Exception):
    def __init__(self, message_id: str):
        super().__init__(f"Ya hay una respuesta en curso ({message_id})")
        self.message_id = message_id


class NothingToInterrupt(Exception):
    pass


@dataclass(eq=False)
class Generation:
    session_id: str
    message_id: str
    question: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    parts: list[str] = field(default_factory=list)
    sequence: int = 0
    cancelled: bool = False
    completing: bool = False  # el agente ya respondió: se está guardando, no se puede interrumpir
    dropped_after_abort: int = 0
    task: asyncio.Task | None = None

    @property
    def text(self) -> str:
        return "".join(self.parts)


class ChatTurnManager:
    def __init__(self, pubsub: ChatPubSub | None = None, *, interrupt_wait_seconds: float = INTERRUPT_WAIT_SECONDS):
        self.pubsub = pubsub or ChatPubSub()
        self.interrupt_wait_seconds = interrupt_wait_seconds
        self.active: dict[str, Generation] = {}
        self.counters: Counter[str] = Counter()
        self._tasks: set[asyncio.Task] = set()

    # ── lectura ─────────────────────────────────────────────────────────────
    def active_generation(self, session_id: str) -> ActiveGeneration | None:
        generation = self.active.get(session_id)
        if generation is None or generation.cancelled:
            return None
        return ActiveGeneration(message_id=generation.message_id, text=generation.text, sequence=generation.sequence)

    async def snapshot(self, session_id: str, store: ChatStore) -> SessionSnapshotData:
        """Historial persistido + respuesta en curso. Se llama **después** de suscribirse al canal."""
        live_before = self._live_message_id(session_id)
        session = await run_in_threadpool(store.get_session, session_id)
        if session is None:
            raise SessionNotFound(session_id)
        messages = await run_in_threadpool(store.list_messages, session_id)
        active = self.active_generation(session_id)  # en el loop: texto y `sequence` coherentes entre sí
        live = {live_before, self._live_message_id(session_id)}
        return SessionSnapshotData(
            session_id=session_id,
            session=session,
            messages=[self._orphan_as_error(message, live) for message in messages],
            active_generation=active,
        )

    def _live_message_id(self, session_id: str) -> str | None:
        generation = self.active.get(session_id)
        return generation.message_id if generation is not None else None

    @staticmethod
    def _orphan_as_error(message: ChatMessage, live: set[str | None]) -> ChatMessage:
        """Un `streaming` sin generación viva es de un turno perdido (p. ej. reinicio de la API)."""
        if message.status == "streaming" and message.message_id not in live:
            return message.model_copy(update={"status": "error"})
        return message

    # ── publicación ─────────────────────────────────────────────────────────
    def _publish(self, session_id: str, name: str, data: BaseModel) -> None:
        self.pubsub.publish(session_id, dump_event(name, data))

    def _on_token(self, generation: Generation, token: str) -> None:
        """Corre en el event loop. Tras la interrupción ningún token de ese mensaje sale."""
        if generation.cancelled:
            generation.dropped_after_abort += 1
            self.counters["dropped_after_abort"] += 1
            return
        generation.sequence += 1
        generation.parts.append(token)
        self.counters["tokens_published"] += 1
        self._publish(generation.session_id, EVENT_TOKEN_CHUNK, TokenChunkData(
            session_id=generation.session_id, message_id=generation.message_id,
            token=token, sequence=generation.sequence,
        ))

    def _release(self, generation: Generation) -> None:
        if self.active.get(generation.session_id) is generation:
            del self.active[generation.session_id]

    # ── turnos ──────────────────────────────────────────────────────────────
    async def start_turn(self, session_id: str, text: str, *, user: dict[str, Any], store: ChatStore,
                         turn_runner: TurnRunner) -> Generation:
        """Guarda el mensaje del usuario, publica su eco y arranca la respuesta en un hilo."""
        current = self.active.get(session_id)
        if current is not None:
            raise GenerationInProgress(current.message_id)
        generation = Generation(session_id=session_id, message_id=new_message_id(), question=text)
        self.active[session_id] = generation  # antes de cualquier await: un solo turno por sesión
        try:
            message = await run_in_threadpool(
                lambda: store.add_message(session_id=session_id, role="user", text=text, status="completed")
            )
            self._publish(session_id, EVENT_USER_MESSAGE, UserMessageData(
                session_id=session_id, message_id=message.message_id, text=message.text, created_at=message.created_at,
            ))
            await run_in_threadpool(store.set_session_status, session_id, "active")
            await run_in_threadpool(lambda: store.add_message(
                session_id=session_id, role="assistant", text="", status="streaming", message_id=generation.message_id,
            ))
        except Exception:
            self._release(generation)
            raise
        self._publish(session_id, EVENT_GENERATION_STARTED,
                      GenerationStartedData(session_id=session_id, message_id=generation.message_id))

        loop = asyncio.get_running_loop()

        def on_token(token: str) -> None:  # hilo del agente → event loop
            try:
                loop.call_soon_threadsafe(self._on_token, generation, token)
            except RuntimeError:  # el loop se cerró (apagado de la API)
                pass

        self.counters["turns_started"] += 1
        task = asyncio.create_task(self._run(generation, user=user, store=store, turn_runner=turn_runner,
                                             on_token=on_token))
        generation.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return generation

    async def _run(self, generation: Generation, *, user: dict[str, Any], store: ChatStore,
                   turn_runner: TurnRunner, on_token: Callable[[str], None]) -> None:
        session_id, message_id = generation.session_id, generation.message_id
        try:
            self.counters["runner_calls"] += 1
            try:
                result = await asyncio.to_thread(
                    turn_runner, generation.question, conversation_id=session_id, user=user,
                    on_token=on_token, cancel_event=generation.cancel_event,
                )
            except runner.AgentRunCancelled as exc:
                logger.info(
                    "chat session=%s message_id=%s cancelled run_id=%s tokens_sent=%d stream_closed=%s "
                    "dropped_after_abort=%d", session_id, message_id, exc.run_id, exc.tokens_sent,
                    exc.stream_closed, generation.dropped_after_abort,
                )
                await run_in_threadpool(lambda: store.update_message(message_id, run_id=exc.run_id))
                return
            except Exception:
                if generation.cancelled:
                    logger.warning("chat session=%s message_id=%s falló tras la interrupción", session_id, message_id)
                    return
                logger.exception("chat session=%s message_id=%s: fallo del agente", session_id, message_id)
                await self._fail(generation, store, code="agent_unavailable", detail=AGENT_UNAVAILABLE)
                return

            if generation.cancelled:  # terminó antes de ver el evento: el parcial ya está guardado
                logger.info("chat session=%s message_id=%s terminó tras la interrupción: se descarta la respuesta "
                            "dropped_after_abort=%d", session_id, message_id, generation.dropped_after_abort)
                return
            generation.completing = True
            if result.status == "invalid":
                await self._fail(generation, store, code="invalid_message", detail=result.answer or INVALID_QUESTION)
                return
            if generation.sequence == 0 and result.answer:
                self._on_token(generation, result.answer)  # ruta sin LLM: un único token_chunk
            await run_in_threadpool(lambda: store.update_message(
                message_id, text=result.answer, status="completed", run_id=result.run_id,
            ))
            self.counters["turns_completed"] += 1
            self._publish(session_id, EVENT_GENERATION_COMPLETED, GenerationCompletedData(
                session_id=session_id, message_id=message_id, answer=result.answer,
                status=result.status, sources=list(result.sources),
            ))
            logger.info("chat session=%s message_id=%s completed run_id=%s tokens=%d",
                        session_id, message_id, result.run_id, generation.sequence)
        finally:
            self._release(generation)

    async def _fail(self, generation: Generation, store: ChatStore, *, code: str, detail: str) -> None:
        generation.completing = True
        try:
            await run_in_threadpool(lambda: store.update_message(
                generation.message_id, text=generation.text, status="error",
            ))
        except Exception:
            logger.exception("No se pudo guardar el error del mensaje %s", generation.message_id)
        self._publish(generation.session_id, EVENT_CHAT_ERROR, ChatErrorData(
            session_id=generation.session_id, code=code, detail=detail, message_id=generation.message_id,
        ))

    async def interrupt(self, session_id: str, new_input: str | None, *, user: dict[str, Any], store: ChatStore,
                        turn_runner: TurnRunner) -> Generation | None:
        """Aborta la respuesta en curso, conserva el parcial y, con `new_input`, empieza otro turno."""
        generation = self.active.get(session_id)
        if generation is None or generation.cancelled or generation.completing:
            raise NothingToInterrupt()
        generation.cancelled = True  # primero: desde aquí `_on_token` descarta
        generation.cancel_event.set()
        self.counters["turns_interrupted"] += 1
        partial = generation.text
        await run_in_threadpool(lambda: store.update_message(generation.message_id, text=partial, status="interrupted"))
        await run_in_threadpool(store.set_session_status, session_id, "interrupted")
        self._publish(session_id, EVENT_GENERATION_INTERRUPTED,
                      GenerationInterruptedData(session_id=session_id, message_id=generation.message_id))
        logger.info("chat session=%s message_id=%s interrupted tokens_published=%d",
                    session_id, generation.message_id, generation.sequence)
        if generation.task is not None:
            done, _ = await asyncio.wait({generation.task}, timeout=self.interrupt_wait_seconds)
            if not done:
                logger.warning("chat session=%s message_id=%s: el hilo del agente sigue tras %.0f s (sus tokens se "
                               "descartan)", session_id, generation.message_id, self.interrupt_wait_seconds)
        self._release(generation)
        if not new_input:
            return None
        return await self.start_turn(session_id, new_input, user=user, store=store, turn_runner=turn_runner)


turn_manager = ChatTurnManager()


def get_turn_manager() -> ChatTurnManager:
    """Dependencia FastAPI (sobreescribible en tests con un gestor nuevo)."""
    return turn_manager
