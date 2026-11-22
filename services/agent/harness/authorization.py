"""Autorización por sesión: solo se habla de los envíos del usuario autenticado.

BRIEFING §3 y caso 3: «Dame el estado del pedido #45821» cuando ese pedido no
pertenece a la sesión → **rechazo por falta de autorización**, no por falta de
datos. Por eso un pedido inexistente y uno ajeno reciben la misma respuesta:
el agente no confirma si un número existe (evita enumerar pedidos cambiando
dígitos).

La fuente de envíos es `ShipmentDirectory`. Hoy lee el directorio de
demostración `data/agent/shipments.json` (TrackFlow no tiene aún API de
tracking); cambiar a una API real solo cambia esta clase.

También detecta el país del que habla el mensaje (EE. UU. / España), que usa la
guardia de mezcla de políticas (BRIEFING caso 4).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .normalize import fold

ROOT = Path(__file__).resolve().parents[3]
SHIPMENTS_PATH_ENV = "AGENT_SHIPMENTS_PATH"
DEFAULT_SHIPMENTS_PATH = ROOT / "data" / "agent" / "shipments.json"

CountryCode = Literal["US", "ES"]
COUNTRY_NAMES = {"US": "Estados Unidos", "ES": "España"}

STATUS_LABELS = {
    "created": "registrado",
    "in_transit": "en tránsito",
    "out_for_delivery": "en reparto",
    "delivered": "entregado",
    "delivery_failed": "entrega fallida",
    "returned": "devuelto",
}

# Una referencia de pedido/tracking: palabra clave + identificador con al menos 4 dígitos seguidos,
# o "#" seguido de 4+ dígitos. Los tickets ("ticket 3") usan otra palabra y no entran.
ORDER_REF = re.compile(
    r"\b(?:pedidos?|orders?|envios?|shipments?|tracking|seguimiento|paquetes?|guia|parcel)\b"
    r"(?:\s+(?:numero|num\.?|n[o°º]\.?|id|de\s+seguimiento|con\s+tracking))?\s*[:#]?\s*#?\s*"
    r"([a-z0-9][a-z0-9-]{3,24})\b"
)
HASH_REF = re.compile(r"#\s*(\d{4,})\b")
TRACKING_CODE = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{10,}\b")


def normalize_reference(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def order_references(text: str | None) -> list[str]:
    """Referencias de pedido/tracking que aparecen en el mensaje (normalizadas, sin repetir)."""
    folded = fold(text)
    # Un número de pedido tiene al menos 4 dígitos seguidos: así "envío 24h" o "48-72 horas" no cuentan.
    refs = [m for m in ORDER_REF.findall(folded) if re.search(r"\d{4,}", m)]
    refs += HASH_REF.findall(folded)
    refs += TRACKING_CODE.findall(text or "")
    seen: list[str] = []
    for ref in map(normalize_reference, refs):
        if ref and ref not in seen:
            seen.append(ref)
    return seen


# --------------------------------------------------------------------------- #
# Países
# --------------------------------------------------------------------------- #
COUNTRY_MARKERS: dict[str, re.Pattern[str]] = {
    "US": re.compile(
        r"\b(?:estados unidos|ee\.? ?uu\.?|eeuu|usa|u\.s\.a?\.?|united states|los angeles|california|l\.a\.|"
        r"new york|nueva york|texas|miami|estadounidense)\b"
    ),
    "ES": re.compile(
        r"\b(?:espana|spain|zaragoza|aragon|madrid|barcelona|cataluna|valencia|sevilla|bilbao|espanol[a]?|"
        r"peninsula)\b"
    ),
}


def countries_mentioned(text: str | None) -> list[str]:
    folded = fold(text)
    return [code for code, pattern in COUNTRY_MARKERS.items() if pattern.search(folded)]


# --------------------------------------------------------------------------- #
# Directorio de envíos
# --------------------------------------------------------------------------- #
class Shipment(BaseModel):
    reference: str
    owner_user_ids: list[int]
    country: CountryCode
    city: str
    carrier: str
    status: str
    last_event: str
    updated_at: str

    def public_view(self) -> dict:
        """Lo que se puede contar al dueño: sin ids de otros usuarios."""
        return self.model_dump(exclude={"owner_user_ids"})


class ShipmentDirectory:
    def __init__(self, shipments: list[Shipment]):
        self._by_ref = {normalize_reference(s.reference): s for s in shipments}

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "ShipmentDirectory":
        path = Path(path or os.environ.get(SHIPMENTS_PATH_ENV) or DEFAULT_SHIPMENTS_PATH)
        if not path.exists():
            return cls([])
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls([Shipment.model_validate(item) for item in payload.get("shipments", [])])

    def get(self, reference: str) -> Shipment | None:
        return self._by_ref.get(normalize_reference(reference))


@lru_cache(maxsize=1)
def default_directory() -> ShipmentDirectory:
    return ShipmentDirectory.from_file()


_directory: ShipmentDirectory | None = None


def get_directory() -> ShipmentDirectory:
    return _directory or default_directory()


def set_directory(directory: ShipmentDirectory | None) -> None:
    global _directory
    _directory = directory


class AuthorizationResult(BaseModel):
    references: list[str] = []
    authorized: list[dict] = []
    denied: list[str] = []

    @property
    def has_denied(self) -> bool:
        return bool(self.denied)


def authorize(text: str, user_id: int | None) -> AuthorizationResult:
    """Separa las referencias del mensaje en autorizadas (del usuario) y denegadas (ajenas o inexistentes)."""
    references = order_references(text)
    authorized, denied = [], []
    directory = get_directory()
    for ref in references:
        shipment = directory.get(ref)
        if shipment is not None and user_id is not None and user_id in shipment.owner_user_ids:
            authorized.append(shipment.public_view())
        else:
            denied.append(ref)
    return AuthorizationResult(references=references, authorized=authorized, denied=denied)


def shipment_section(shipments: list[dict]) -> str:
    lines = []
    for item in shipments:
        status = STATUS_LABELS.get(item["status"], item["status"])
        lines.append(
            f"El envío {item['reference']} ({item['city']}, {COUNTRY_NAMES[item['country']]}) está {status} "
            f"con {item['carrier']}. Último evento: {item['last_event']} ({item['updated_at'][:16].replace('T', ' ')} UTC)."
        )
    countries = sorted({item["country"] for item in shipments})
    lines.append(
        "Las políticas de devolución y los SLA dependen del país del envío: "
        + " y ".join(COUNTRY_NAMES[c] for c in countries)
        + "."
    )
    lines.append("Fuente: directorio de envíos de TrackFlow (envíos asociados a tu sesión)")
    return "\n".join(lines)
