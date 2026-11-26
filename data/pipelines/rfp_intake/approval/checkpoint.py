"""Checkpointer de la Parte 3: SQLite persistente (por defecto) o memoria (solo desarrollo y tests).

`SqliteSaver` (paquete `langgraph-checkpoint-sqlite`) guarda el estado de cada
hilo antes de cada interrupción en `data/checkpoints/rfp_approval.sqlite`
(`RFP_CHECKPOINT_PATH`): si la API se reinicia con aprobaciones pendientes, la
rama se reanuda en el mismo nodo. El fichero es estado de ejecución (no se
versiona). `RFP_CHECKPOINTER=memory` usa `InMemorySaver`: se pierde al
reiniciar, así que solo vale para desarrollo local y para los tests.

Un único checkpointer por proceso (`get_checkpointer()`), compartido por todos
los tickets: lo que los separa es el `thread_id` (`rfp-{ticket_id}` y
`rfp-{ticket_id}:{department_id}`).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from . import config

logger = logging.getLogger("rfp_intake.approval.checkpoint")

_lock = threading.Lock()
_checkpointer = None


class CheckpointerUnavailable(RuntimeError):
    pass


def make_checkpointer(kind: str | None = None, path: Path | str | None = None):
    kind = (kind or config.CHECKPOINTER).strip().lower()
    if kind == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        logger.warning("Checkpointer en memoria: las aprobaciones pendientes se pierden al reiniciar (solo desarrollo).")
        return InMemorySaver()
    if kind != "sqlite":
        raise CheckpointerUnavailable(f"RFP_CHECKPOINTER desconocido: {kind!r} (sqlite | memory)")
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ModuleNotFoundError as exc:
        raise CheckpointerUnavailable(
            "Falta el checkpointer SQLite de LangGraph: ejecuta `uv add langgraph-checkpoint-sqlite`."
        ) from exc
    target = Path(path or config.CHECKPOINT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), check_same_thread=False)
    saver = SqliteSaver(connection)
    if hasattr(saver, "setup"):
        saver.setup()
    logger.info("Checkpointer SQLite de la Parte 3 en %s", target)
    return saver


def get_checkpointer():
    """El checkpointer del proceso (se crea la primera vez que se usa)."""
    global _checkpointer
    with _lock:
        if _checkpointer is None:
            _checkpointer = make_checkpointer()
        return _checkpointer


def set_checkpointer(checkpointer) -> None:
    """Para tests: sustituye el checkpointer del proceso (o lo borra con `None`)."""
    global _checkpointer
    with _lock:
        _checkpointer = checkpointer


def delete_threads(checkpointer, thread_ids: list[str]) -> None:
    """Borra los checkpoints de un ticket antes de reiniciar su aprobación desde cero."""
    delete = getattr(checkpointer, "delete_thread", None)
    if delete is None:
        logger.warning("El checkpointer no permite borrar hilos: %s", thread_ids)
        return
    for thread_id in thread_ids:
        delete(thread_id)
