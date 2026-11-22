"""Guardia de entrada determinista (primera capa, antes de cualquier LLM).

Clasifica el mensaje del usuario según la tabla de decisión del Ticket #SEC-114,
adaptada al BRIEFING de TrackFlow:

| Categoría | Acción | Tipo de fallo | Ejemplo |
|---|---|---|---|
| `injection` | bloquear (rechazo firme, sin cumplir la tarea) | seguridad | «Ignore your previous instructions…», «olvídate de TrackFlow» |
| `unauthorized_order` | bloquear | contenido | «estado del pedido #45821» que no es de la sesión |
| `sensitive_request` | bloquear | contenido | tarifas negociadas con carriers, ubicación/rutas internas de almacenes |
| `personal_task` | bloquear + reconducir | contenido | ensayos, tareas, código ajeno, terapia |
| `policy_override` | reconducir (se responde con la política del país real) | contenido | «aplica la política de España a mi pedido en Los Ángeles» |
| `casual` | permitir breve + reconducir | contenido | saludo, hora, tiempo, trivia |
| `general_logistics` | respuesta breve + reconducir | contenido | «¿qué es la logística inversa?» |
| `domain` | permitir | — | tracking, devoluciones, SLA, incidencias |

Las reglas usan texto normalizado (`normalize.variants`) para resistir tildes,
mayúsculas, l33t, caracteres invisibles y letras separadas. La segunda capa
(clasificación semántica `scope` del enrutador LLM) cubre las paráfrasis que
estas reglas no conocen; la guardia de salida es la tercera.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from . import authorization
from .normalize import Variants, variants

Category = Literal[
    "injection", "unauthorized_order", "sensitive_request", "personal_task",
    "policy_override", "casual", "general_logistics", "domain",
]
Action = Literal["block", "redirect", "allow"]
FailureType = Literal["structural", "content", "security"]

ACTION_BY_CATEGORY: dict[str, Action] = {
    "injection": "block", "unauthorized_order": "block", "sensitive_request": "block", "personal_task": "block",
    "policy_override": "redirect", "casual": "redirect", "general_logistics": "redirect", "domain": "allow",
}
FAILURE_BY_CATEGORY: dict[str, FailureType | None] = {
    "injection": "security", "unauthorized_order": "content", "sensitive_request": "content",
    "personal_task": "content", "policy_override": "content", "casual": "content",
    "general_logistics": "content", "domain": None,
}

_P = re.compile

# --------------------------------------------------------------------------- #
# Inyección / cambio de instrucciones (ES + EN)
# --------------------------------------------------------------------------- #
INSTRUCTION_NOUN = r"(?:instrucciones|instruccion|reglas|normas|indicaciones|restricciones|directrices|prompt|configuracion|programacion|limites|politicas internas)"
EN_NOUN = r"(?:instructions?|rules|prompts?|guidelines|restrictions|directives|programming|guardrails|constraints)"
INJECTION_RULES: dict[str, re.Pattern[str]] = {
    "ignore_instructions_es": _P(
        rf"\b(?:ignora|ignore|ignores|ignorar|ignorad|olvida|olvidate|olvidad|olvides|olvidar|descarta|descartar|omite|omitir|"
        rf"saltate|saltarte|salta|desactiva|desactivar|anula|anular|deja de (?:lado|seguir|cumplir))"
        rf"(?:\s+\w+){{0,4}}\s+{INSTRUCTION_NOUN}\b"
    ),
    "ignore_instructions_en": _P(
        rf"\b(?:ignore|disregard|forget|override|bypass|skip|drop|discard)(?:\s+\w+){{0,4}}\s+{EN_NOUN}\b"
    ),
    "forget_company": _P(
        r"\b(?:olvida\w*|olvidate|deja de ser|ya no eres|no eres|sal de|forget|stop being|you are not)"
        r"(?:\s+\w+){0,3}\s+(?:trackflow|tu (?:empresa|rol|trabajo)|que trabajas|el agente|tu papel|your (?:company|role|job))\b"
    ),
    "role_change_es": _P(
        r"\b(?:a partir de ahora|desde ahora|de ahora en adelante|ahora)\s+(?:eres|seras|vas a ser|actua\w*|responde\w*|te llamas|funciona\w*)\b"
        r"|\b(?:actua|actuar|comportate|haz)\s+(?:como|de)\s+(?:si\s+no|un[ao]?\s+(?:asistente|ia|bot|chatbot|modelo)|chatgpt|gpt|otr[ao]|mi\s+asistente)"
        r"|\b(?:finge|fingir|simula|imagina que eres|haz como si|juego de rol|roleplay)\b"
    ),
    "role_change_en": _P(
        r"\b(?:you are now|from now on|act as|acting as|pretend(?: to be| you)|roleplay as|behave as|you will now|simulate being)\b"
    ),
    "no_rules": _P(
        r"\bsin\s+(?:ningun\w*\s+)?(?:reglas|normas|censura|filtros|instrucciones)\b"
        r"|\b(?:asistente|ia|bot|chatbot|modelo|agente|eres|seas|ser|actua\w*|responde\w*|como si)(?:\s+\w+){0,4}\s+(?:sin|no tuvieras|no tienes)\s+(?:\w+\s+)?(?:restricciones|limites|reglas)\b"
        r"|\b(?:no|without(?: any)?)\s+(?:rules|filters|guidelines|censorship)\b"
        r"|\b(?:assistant|ai|bot|model|act|respond|answer)\w*(?:\s+\w+){0,3}\s+without(?: any)?\s+(?:restrictions|limits)\b"
        r"|\b(?:unrestricted|uncensored|unfiltered|jailbreak\w*|jailbroken)\b"
        r"|\b(?:modo|mode)\s+(?:desarrollador|developer|dios|god|dan|libre|sin filtros?|root)\b"
        r"|\bdeveloper mode\b|\bdan mode\b|\bdo anything now\b"
    ),
    "reveal_prompt": _P(
        r"\b(?:muestra\w*|revela\w*|ensena\w*|dime|repite|imprime|copia|escribe|cuentame|reveal|show|print|repeat|tell me|output|display)"
        r"(?:\s+\w+){0,3}\s+(?:tu|tus|your)\s+(?:prompt|instrucciones|reglas|configuracion|instructions|rules)\b"
        r"|\b(?:system prompt|prompt del sistema|prompt de sistema|mensaje de sistema|mensaje del sistema|initial instructions|"
        r"instrucciones (?:iniciales|del sistema|internas|originales|ocultas))\b"
    ),
    "new_instructions": _P(
        r"\b(?:nuevas instrucciones|instrucciones nuevas|nuevas reglas|tus nuevas|new instructions|updated instructions|new rules)\b"
    ),
    "priority_override": _P(
        r"\b(?:prioridad maxima|maxima prioridad|esto anula|this overrides|highest priority|soy (?:tu|el) (?:desarrollador|creador|administrador|admin)|i am (?:your|the) (?:developer|creator|admin))\b"
    ),
}
# Marcadores de rol o de plantilla de chat que un usuario no debería escribir nunca.
ROLE_MARKERS = _P(
    r"(?im)^\s*(?:system|assistant|developer|sistema)\s*:|<\|im_(?:start|end)\|>|\[/?inst\]|<<\s*/?sys\s*>>|</?\s*system\s*>|#{2,}\s*(?:system|instruction|sistema)"
)
# Texto ofuscado letra a letra ("i g n o r a  t u s  r e g l a s", "i.g.n.o.r.e"): se compacta y se busca.
COMPACT_INJECTION = _P(
    r"(?:ignor|olvid|forget|disregard|descart|omit|bypass|override)[a-z]{0,5}"
    r"(?:tus|las|todas|mis|your|all|the|previous|prior|anteriores|de){0,3}"
    r"(?:instruccion|regla|norma|instruction|rule|prompt|guideline|trackflow)"
    r"|systemprompt|sinreglas|norules|developermode|modod(?:esarrollador|an)"
)


def looks_spelled_out(folded: str) -> bool:
    """Más de la mitad de las "palabras" son letras sueltas: texto deletreado para esquivar filtros."""
    tokens = re.findall(r"[a-z0-9]+", folded)
    return len(tokens) >= 6 and sum(len(t) == 1 for t in tokens) / len(tokens) >= 0.5

# --------------------------------------------------------------------------- #
# Datos sensibles que el agente nunca revela (BRIEFING §3)
# --------------------------------------------------------------------------- #
CARRIERS = r"(?:ups|fedex|dhl|mrw|seur|transportistas?|carriers?)"
SENSITIVE_RULES: dict[str, re.Pattern[str]] = {
    "negotiated_rates": _P(
        rf"\b(?:tarifas?|precios?|costes?|costos?|descuentos?|rates?|prices?|discounts?)\s+(?:\w+\s+){{0,3}}"
        rf"(?:negociad\w*|pactad\w*|acordad\w*|preferent\w*|confidencial\w*|negotiated|contracted)\b"
        rf"|\b(?:cuanto|que)\s+(?:le\s+)?(?:paga|pagamos|cobra|cobran|nos cobra)\w*\s+(?:trackflow\s+)?(?:a\s+)?{CARRIERS}\b"
        rf"|\b(?:tarifas?|precios?|contratos?|acuerdos?)\s+(?:\w+\s+){{0,3}}?(?:con|de)\s+{CARRIERS}\b"
    ),
    "commercial_terms": _P(
        r"\b(?:terminos|condiciones|clausulas|contrato|contratos|acuerdo comercial)\s+(?:comerciales?\s+)?(?:de|con|del)\s+(?:otr[ao]s?\s+)?(?:clientes?|marcas?)\b"
        r"|\b(?:cuanto paga|que paga|que tarifa tiene)\s+(?:la marca|el cliente|otra marca|otro cliente)\b"
        r"|\b(?:terminos|condiciones|clausulas|contratos?|tarifas?|precios?)\s+(?:comerciales?\s+)?(?:\w+\s+){0,2}(?:otr[ao]s?\s+(?:clientes?|marcas?))\b"
    ),
    "warehouse_location": _P(
        r"\b(?:direccion|ubicacion|coordenadas|plano|mapa|address|location)\s+(?:exacta\s+)?(?:\w+\s+){0,2}(?:almacen\w*|nave|warehouse)\b"
        r"|\bdonde\s+(?:esta|estan|queda)\s+(?:exactamente\s+)?(?:el|los)\s+almacen\w*\b"
        r"|\b(?:rutas?|recorridos?)\s+internas?\b|\b(?:pasillos?|muelles? de carga|codigos? de acceso|camaras? de seguridad|turnos? de (?:vigilancia|seguridad))\b"
    ),
    "other_customers": _P(
        r"\b(?:pedidos?|envios?|datos|tracking)\s+de\s+(?:otr[ao]s?\s+(?:clientes?|personas?|usuarios?|marcas?)|todos los clientes|cualquier cliente)\b"
        r"|\b(?:lista|listado|dame|muestra\w*|ensena\w*|show me|list)\s+(?:\w+\s+){0,2}(?:pedidos|envios|orders|shipments)\s+"
        r"(?:de\s+)?(?:otr\w*|todos|cualquier|other|all|every)\b"
    ),
}

# --------------------------------------------------------------------------- #
# Uso como chatbot personal
# --------------------------------------------------------------------------- #
CREATE_VERB = r"(?:escrib\w*|redact\w*|haz\w*|hacer|genera\w*|crea\w*|compon\w*|ayuda\w*\s+(?:a|con)(?:\s+(?:escribir|hacer|redactar|terminar))?|necesito|quiero|write|make|create|generate|help me (?:write|with|do))"
PERSONAL_RULES: dict[str, re.Pattern[str]] = {
    "creative_or_academic": _P(
        rf"\b{CREATE_VERB}(?:\s+\w+){{0,4}}\s+(?:un|una|mi|el|la|me|a|an|my)?\s*(?:ensayo|redaccion|poema|poesia|cancion|letra de|cuento|novela|"
        rf"carta de amor|discurso|tesis|tfg|tfm|monografia|essay|poem|song|story|love letter|speech)\b"
        r"|\b(?:mi|mis|my)\s+(?:deberes|examen|trabajo de (?:clase|la universidad|fin de)|homework|assignment)\b"
        r"|\btareas?\s+(?:de|para)\s+(?:la\s+|mi\s+|el\s+)?(?:universidad|uni|clase|colegio|instituto|matematicas|historia|ingles)\b"
        r"|\bensayo sobre\b|\bessay (?:about|on)\b"
    ),
    "foreign_code": _P(
        r"\b(?:escrib\w*|haz\w*|genera\w*|programa\w*|crea\w*|depura\w*|arregla\w*|write|code|debug|fix)(?:\s+\w+){0,5}\s+"
        r"(?:codigo|script|funcion|programa|app|aplicacion|pagina web|code|function|program)\b(?:\s+\w+){0,4}\s*"
        r"(?:en|in|con|para|de)?\s*(?:python|javascript|typescript|java|c\+\+|c#|php|sql|react|html|css|bash|rust|go)\b"
        r"|\b(?:codigo|code)\s+(?:de|para|for)\s+(?:(?:mi|otro|my|another|other)\s+)+(?:proyecto|project|app|web)\b"
    ),
    "personal_advice": _P(
        r"\b(?:estoy|me siento|i feel|i am)\s+(?:muy\s+)?(?:triste|deprimid\w*|ansios\w*|depressed|lonely|sad|anxious)\b"
        r"|\b(?:haz|actua|se|hazme|be my)\s+(?:de\s+|como\s+)?(?:mi\s+)?(?:terapeuta|psicolog\w*|coach|therapist|psychologist)\b"
        r"|\bconsejo\s+(?:personal|amoroso|sentimental|de pareja)\b|\b(?:mi novio|mi novia) (?:me ha dejado|me dejo)\b"
        r"|\b(?:dieta|rutina de (?:gimnasio|ejercicio)|horoscopo|receta de|recipe for|workout plan)\b"
    ),
}

# --------------------------------------------------------------------------- #
# Small talk, trivia y logística general (permitidos con reconducción)
# --------------------------------------------------------------------------- #
CASUAL_RULES: dict[str, re.Pattern[str]] = {
    "greeting": _P(
        r"^(?:hola|holi|buenas|buenos dias|buenas tardes|buenas noches|hey|hi|hello|que tal|saludos)"
        r"(?:[\s,!.]+(?:hola|buenas|buenos dias|buenas tardes|buenas noches|agente|equipo|trackflow|amigo|que tal|como estas|good morning))*[\s!.,?¿]*$"
    ),
    "how_are_you": _P(r"\b(?:como estas|como te va|que tal estas|how are you|como te llamas|quien eres|what is your name)\b"),
    "thanks": _P(r"^(?:muchas\s+)?(?:gracias|thank you|thanks|genial|perfecto|ok gracias)(?:\s+por\s+(?:todo|tu ayuda|la ayuda))?[\s!.,]*$"),
    "time_weather": _P(r"\b(?:que hora es|que hora (?:es )?en|what time|que tiempo hace|clima en|weather in|va a llover|temperatura en)\b"),
    "trivia": _P(
        r"\b(?:capital de|quien (?:gano|invento|descubrio|es el presidente|escribio)|cuantos habitantes|"
        r"dato curioso|chiste|joke|fun fact|en que ano)\b"
    ),
}
# Si el mensaje habla de un envío, una devolución o una incidencia, no es small talk aunque salude.
DOMAIN_HINTS = _P(
    r"\b(?:pedido|envio|paquete|devolu\w*|reembols\w*|sla|entrega\w*|tracking|seguimiento|incidencia\w*|ticket\w*|"
    r"transportista\w*|carrier\w*|almacen\w*|stock|inventario|plazo\w*|politica\w*|recogida|etiqueta|order|shipment|return|refund|parcel)"
)
GENERAL_LOGISTICS = _P(
    r"\b(?:que es|que significa|explica(?:me)?|definicion de|what is)\s+(?:la |el |un |una |the |a )?"
    r"(?:logistica(?: inversa)?|ultima milla|cross[- ]?docking|picking|fulfillment|3pl|incoterms?|reverse logistics|last mile|almacenaje|sga|wms)\b"
)
POLICY_WORDS = r"(?:politica|politicas|condiciones|plazos?|sla|ventana|reglas|normas|policy|terms)"
POLICY_OVERRIDE = _P(
    rf"\b(?:aplica\w*|usa|utiliza\w*|quiero|pon\w*|dame|apply|use)\b(?:\s+\w+){{0,3}}\s+{POLICY_WORDS}\b(?:\s+\w+){{0,3}}?\s+(?:de|del|of|from)\s+"
    r"(?P<target>espana|spain|estados unidos|ee\.? ?uu\.?|eeuu|usa)\b"
)
CONVENIENCE = _P(r"\b(?:me conviene|es mejor para mi|mas favorable|aunque (?:sea|este|el pedido)|because it'?s better)\b")
TARGET_CODES = {"espana": "ES", "spain": "ES", "estados unidos": "US", "eeuu": "US", "ee uu": "US", "ee. uu.": "US",
                "ee.uu.": "US", "ee.uu": "US", "ee uu.": "US", "usa": "US"}


class InputVerdict(BaseModel):
    category: Category
    action: Action
    failure_type: FailureType | None = None
    rules: list[str] = []
    denied_orders: list[str] = []
    authorized_orders: list[dict] = []
    country_lock: str | None = None
    requested_country: str | None = None

    @property
    def blocked(self) -> bool:
        return self.action == "block"


def _matches(v: Variants, rules: dict[str, re.Pattern[str]]) -> list[str]:
    return [name for name, pattern in rules.items() if v.any(pattern)]


def injection_rules(text: str) -> list[str]:
    """Reglas de inyección que dispara `text` (también se usa sobre contenido externo)."""
    v = variants(text)
    hits = _matches(v, INJECTION_RULES)
    if ROLE_MARKERS.search(v.original) or ROLE_MARKERS.search(v.folded):
        hits.append("role_markers")
    if not hits and looks_spelled_out(v.deleet) and COMPACT_INJECTION.search(v.compact):
        hits.append("obfuscated")
    return hits


def _policy_override(v: Variants, shipments: list[dict]) -> tuple[str | None, str | None]:
    """`(país pedido por el usuario, país real)` si pide aplicar la política de otro país."""
    match = POLICY_OVERRIDE.search(v.folded)
    if not match:
        return None, None
    target = TARGET_CODES.get(match.group("target").strip(), None)
    if target is None:
        target = "US" if match.group("target").startswith(("ee", "usa", "estados")) else "ES"
    if shipments:
        real = shipments[0]["country"]
    else:
        # El país real es el que menciona el mensaje y no es el pedido ("…a mi pedido en Los Ángeles").
        rest = v.folded[: match.start("target")] + v.folded[match.end("target"):]
        mentioned = authorization.countries_mentioned(rest)
        others = [c for c in mentioned if c != target]
        real = others[0] if others else None
    if real is None or real == target:
        return None, None
    return target, real


def check_input(text: str, *, user_id: int | None) -> InputVerdict:
    """Veredicto de la guardia de entrada para el mensaje del usuario."""
    v = variants(text)

    rules = injection_rules(text)
    if rules:
        return InputVerdict(category="injection", action="block", failure_type="security", rules=rules)

    auth = authorization.authorize(text, user_id)
    if auth.has_denied:
        return InputVerdict(category="unauthorized_order", action="block", failure_type="content",
                            rules=["order_not_in_session"], denied_orders=auth.denied)

    rules = _matches(v, SENSITIVE_RULES)
    if rules:
        return InputVerdict(category="sensitive_request", action="block", failure_type="content", rules=rules)

    rules = _matches(v, PERSONAL_RULES)
    if rules:
        return InputVerdict(category="personal_task", action="block", failure_type="content", rules=rules)

    requested, real = _policy_override(v, auth.authorized)
    if real:
        rules = ["policy_override"] + (["convenience"] if v.any(CONVENIENCE) else [])
        return InputVerdict(category="policy_override", action="redirect", failure_type="content", rules=rules,
                            authorized_orders=auth.authorized, country_lock=real, requested_country=requested)

    if auth.authorized:
        return InputVerdict(category="domain", action="allow", authorized_orders=auth.authorized)

    if v.any(GENERAL_LOGISTICS):
        return InputVerdict(category="general_logistics", action="redirect", failure_type="content",
                            rules=["general_logistics"])

    rules = _matches(v, CASUAL_RULES)
    if rules and not v.any(DOMAIN_HINTS):
        return InputVerdict(category="casual", action="redirect", failure_type="content", rules=rules)

    return InputVerdict(category="domain", action="allow")
