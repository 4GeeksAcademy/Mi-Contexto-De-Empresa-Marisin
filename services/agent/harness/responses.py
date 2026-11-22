"""Respuestas del harness: rechazos y reconducciones con plantilla (sin LLM).

Un rechazo nunca lo redacta el modelo: así no puede "cumplir a medias" la tarea
abusiva ni ser convencido de cambiar de opinión, y siempre termina devolviendo
la conversación al propósito del agente.
"""

from __future__ import annotations

from .authorization import COUNTRY_NAMES

PURPOSE = "el seguimiento de envíos, las devoluciones (según el país del pedido) y las incidencias de TrackFlow"

REDIRECT = (
    "Soy el agente de soporte de TrackFlow: si tienes una consulta sobre el seguimiento de un envío, "
    "una devolución o una incidencia, cuéntamela y te ayudo."
)
GENERAL_LOGISTICS_REDIRECT = (
    "Si quieres, te explico cómo lo aplica TrackFlow a tus envíos, devoluciones o incidencias."
)

BLOCK_MESSAGES = {
    "injection": (
        "No puedo cambiar, ignorar ni revelar mis instrucciones, ni actuar como otro asistente: soy el agente "
        f"de soporte de TrackFlow y mis reglas no se modifican desde la conversación. Puedo ayudarte con {PURPOSE}."
    ),
    "personal_task": (
        "Eso no es algo con lo que pueda ayudarte: soy el agente de soporte de TrackFlow y solo atiendo "
        f"{PURPOSE}. Si tienes alguna consulta sobre un pedido, cuéntamela."
    ),
    "sensitive_request": (
        "No puedo compartir esa información: las tarifas negociadas con transportistas, los términos comerciales "
        "con clientes y la ubicación o las rutas internas de los almacenes son confidenciales. Para temas "
        f"comerciales, habla con tu account manager. Yo puedo ayudarte con {PURPOSE}."
    ),
    "unauthorized_order": (
        "No puedo darte información {refs}: no está asociado a tu sesión. Por seguridad solo consulto los "
        "envíos de la cuenta con la que has iniciado sesión. Si el pedido es tuyo, accede con la cuenta que lo "
        "realizó o contacta con el equipo de CX."
    ),
}
REPEATED_ATTEMPT = " He registrado este intento: por mucho que se reformule, la respuesta será la misma."


def block_message(category: str, *, denied_orders: list[str] | None = None, strikes: int = 0) -> str:
    text = BLOCK_MESSAGES.get(category, BLOCK_MESSAGES["personal_task"])
    if category == "unauthorized_order":
        refs = ", ".join(f"#{ref}" for ref in denied_orders or []) or "ese pedido"
        text = text.format(refs=f"del pedido {refs}" if len(denied_orders or []) <= 1 else f"de los pedidos {refs}")
        if len(denied_orders or []) > 1:
            text = text.replace("no está asociado", "no están asociados")
    if category == "injection" and strikes >= 3:
        text += REPEATED_ATTEMPT
    return text


def policy_override_prefix(requested: str | None, real: str) -> str:
    asked = COUNTRY_NAMES.get(requested or "", "otro país")
    return (
        f"No puedo aplicar la política de {asked} a un pedido de {COUNTRY_NAMES[real]}: cada país tiene sus "
        f"propias políticas de devolución y SLA, y siempre se aplica la del país real del pedido. Esto es lo que "
        f"corresponde a {COUNTRY_NAMES[real]}:"
    )
