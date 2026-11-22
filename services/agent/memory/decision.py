"""Clasificador de la decisión del usuario sobre la propuesta pendiente.

Cuando hay una propuesta pendiente, el siguiente mensaje se clasifica **primero**
contra ella, con una etiqueta estructurada (no `"sí" in mensaje`):

* `approve` — acepta guardar la propuesta tal cual.
* `reject` — no quiere que se guarde.
* `edit` — la acepta corregida: `edited_fact` lleva el texto nuevo.
* `unrelated` — cambia de tema sin responder.
* `unclear` — no se puede saber.

Además separa lo que queda del mensaje (`remaining_question`) para que la
conversación siga con normalidad ("sí, y ¿cuánto stock hay de…?").

1. **LLM** con salida JSON validada contra `DecisionClassification` y
   `confidence` en [0, 1]. Por debajo de `CONFIDENCE_THRESHOLD` → `unclear`.
2. **Guardas**: una aprobación con negación al inicio, un rechazo que empieza
   por "sí", una edición que no sale del mensaje o un `remaining_question` que
   no está en el mensaje se degradan a `unclear` (o se corrigen).
3. **Reglas** solo si el LLM falla: frases completas de sí/no (todo el mensaje,
   no una subcadena). Cualquier otra cosa → `unclear`.

Solo `approve` y `edit` escriben. `unrelated` y `unclear` **descartan** la
propuesta: nunca se asume aprobación por silencio o ambigüedad.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import DecisionLabel, PendingProposal, fold

logger = logging.getLogger("agent.memory.decision")

CONFIDENCE_THRESHOLD = 0.75
DECISION_TIMEOUT_SECONDS = 15.0


class DecisionClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: DecisionLabel
    confidence: float = Field(ge=0.0, le=1.0)
    edited_fact: str | None = Field(default=None, max_length=280)
    remaining_question: str = Field(default="", max_length=500)
    reason: str = Field(default="", max_length=200)
    decided_by: Literal["llm", "rules"] = "rules"


DECISION_PROMPT = """Eres el clasificador de decisiones del agente de soporte de TrackFlow.
En el turno anterior el agente propuso al usuario guardar en su memoria este hecho:

  «{fact}»

Clasifica el NUEVO mensaje del usuario respecto a ESA propuesta:
- "approve": acepta guardarla tal cual ("sí", "vale, recuérdalo", "correcto, guárdalo").
- "reject": no quiere guardarla ("no", "mejor no", "no hace falta", "eso no es así").
- "edit": la acepta pero corrige el contenido ("sí, pero es desde diciembre"). Devuelve en
  "edited_fact" el hecho completo corregido, en una frase, usando las palabras del usuario.
- "unrelated": no responde a la propuesta y habla de otra cosa.
- "unclear": no se puede saber si la acepta o no.

"remaining_question": copia LITERALMENTE la parte del mensaje que es otra consulta distinta
de la decisión (o "" si no hay). Si es "unrelated", copia el mensaje entero.
"confidence": de 0 a 1, cuánta seguridad tienes en la etiqueta. Si dudas, usa "unclear".

Responde SOLO con un objeto JSON, sin texto alrededor:
{{"label": "approve|reject|edit|unrelated|unclear", "confidence": 0.0, "edited_fact": null,
 "remaining_question": "", "reason": "una frase"}}"""

JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# Reglas de respaldo: el mensaje COMPLETO (plegado y sin puntuación) tiene que ser una de estas frases.
AFFIRM = {
    "si", "si por favor", "si gracias", "si recuerdalo", "si guardalo", "si apuntalo", "vale", "vale recuerdalo",
    "vale guardalo", "ok", "okay", "de acuerdo", "adelante", "correcto", "correcto guardalo", "recuerdalo",
    "guardalo", "yes", "yes please",
}
NEGATE = {
    "no", "no gracias", "no hace falta", "mejor no", "no lo guardes", "no lo recuerdes", "descartalo", "nop",
    "para nada", "ni hablar", "no es correcto", "no please", "no thanks",
}
NEGATION_START = re.compile(r"^\s*(?:no\b|nop\b|mejor no\b|ni hablar\b|para nada\b|nunca\b)")
AFFIRM_START = re.compile(r"^\s*(?:si\b|vale\b|ok\b|de acuerdo\b|adelante\b|claro\b|correcto\b)")


class DecisionRejected(ValueError):
    """La salida del LLM no es una clasificación válida."""


def _plain(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", fold(text)))


def classify_with_rules(message: str, *, reason: str = "") -> DecisionClassification:
    plain = _plain(message)
    if plain in AFFIRM:
        return DecisionClassification(label="approve", confidence=1.0, reason=reason or "Frase de aprobación completa")
    if plain in NEGATE:
        return DecisionClassification(label="reject", confidence=1.0, reason=reason or "Frase de rechazo completa")
    # Fail-closed: si no es una frase completa de sí/no, no se interpreta. El mensaje se
    # contesta como una consulta normal y la propuesta se descarta.
    return DecisionClassification(
        label="unclear", confidence=0.0, remaining_question=message.strip(),
        reason=reason or "Sin clasificación fiable: se descarta por defecto",
    )


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", fold(text)) if len(w) >= 4}


def apply_guards(result: DecisionClassification, message: str, pending: PendingProposal) -> DecisionClassification:
    """Correcciones deterministas sobre la salida del LLM."""
    folded = fold(message)
    update: dict = {}

    remaining = (result.remaining_question or "").strip()
    if remaining and _plain(remaining) not in _plain(message):
        update["remaining_question"] = message.strip()  # no inventa preguntas: responde al mensaje
    label = result.label

    if label == "approve" and NEGATION_START.search(folded):
        label, update["reason"] = "unclear", "Aprobación con negación al inicio"
    elif label == "reject" and AFFIRM_START.search(folded) and not NEGATION_START.search(folded):
        label, update["reason"] = "unclear", "Rechazo que empieza por una afirmación"
    elif label == "edit":
        edited = (result.edited_fact or "").strip()
        new_words = _words(edited) - _words(pending.draft.fact)
        if len(edited) < 10 or (new_words and not new_words & _words(message)):
            label, update["reason"] = "unclear", "Edición que no sale del mensaje del usuario"
    if label in {"unrelated"} and not update.get("remaining_question") and not remaining:
        update["remaining_question"] = message.strip()
    if result.confidence < CONFIDENCE_THRESHOLD and label in {"approve", "reject", "edit"}:
        label, update["reason"] = "unclear", f"Confianza {result.confidence:.2f} < {CONFIDENCE_THRESHOLD}"
    if label == "unclear" and not (update.get("remaining_question") or remaining):
        update["remaining_question"] = ""
    update["label"] = label
    if label != "edit":
        update["edited_fact"] = None
    return result.model_copy(update=update)


def parse_llm_decision(text: str, message: str, pending: PendingProposal) -> DecisionClassification:
    match = JSON_OBJECT.search(text or "")
    if not match:
        raise DecisionRejected("el LLM no devolvió JSON")
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise DecisionRejected(f"JSON inválido: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise DecisionRejected("el JSON no es un objeto")
    raw.pop("decided_by", None)
    raw["remaining_question"] = raw.get("remaining_question") or ""
    try:
        result = DecisionClassification.model_validate({**raw, "decided_by": "llm"})
    except ValidationError as exc:
        raise DecisionRejected(f"contrato no válido: {exc.error_count()} errores") from exc
    return apply_guards(result, message, pending)


def classify_with_llm(pending: PendingProposal, message: str) -> DecisionClassification:
    from data.pipelines import rag as rag_pipeline  # import diferido: cliente LLM del Hito 7

    settings = rag_pipeline.load_settings()
    rag_pipeline.check_models(settings)
    completion = rag_pipeline.get_generation_client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": DECISION_PROMPT.format(fact=pending.draft.fact)},
            {"role": "user", "content": message},
        ],
        temperature=0.0,
        timeout=DECISION_TIMEOUT_SECONDS,
    )
    return parse_llm_decision(completion.choices[0].message.content or "", message, pending)


def classify_decision(pending: PendingProposal, message: str) -> DecisionClassification:
    """LLM primero; si falla, reglas de frase completa (y si no, `unclear`)."""
    try:
        return classify_with_llm(pending, message)
    except Exception as exc:
        logger.warning("Clasificador LLM de la decisión descartado (%s): uso reglas", exc)
        return classify_with_rules(message, reason=f"Reglas (LLM descartado: {type(exc).__name__})")
