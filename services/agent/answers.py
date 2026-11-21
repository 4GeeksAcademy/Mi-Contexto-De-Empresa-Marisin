"""Textos de respuesta construidos a partir de los resultados de las tools.

La parte de la respuesta que viene de una tool **no pasa por el LLM**: se
escribe con plantillas a partir de los campos que devolvió el servicio. Así el
estado de un ticket o el stock de un producto nunca se puede inventar.
"""

from __future__ import annotations

from typing import Any

STATUS_LABELS = {
    "open": "abierto",
    "in_progress": "en curso",
    "resolved": "resuelto",
    "discarded": "descartado",
}
CATEGORY_LABELS = {
    "RETURN_REQUEST": "solicitud de devolución",
    "DAMAGE": "daño",
    "DELAYED_DELIVERY": "entrega retrasada",
    "WRONG_ADDRESS": "dirección incorrecta",
    "LOST_PARCEL": "paquete perdido",
}
ORIGIN_LABELS = {"customer": "cliente", "branch": "sucursal", "internal": "interno"}

INCIDENTS_SOURCE = "Fuente: gestor de incidentes de TrackFlow (consulta en tiempo real)"
INVENTORY_SOURCE = "Fuente: gestor de inventario de TrackFlow (consulta en tiempo real)"


def _date(value: str) -> str:
    return (value or "")[:10] or "fecha desconocida"


def _ticket_line(ticket: dict[str, Any]) -> str:
    return (
        f"- Ticket {ticket['id']} «{ticket['title']}»: {STATUS_LABELS.get(ticket['status'], ticket['status'])} "
        f"({CATEGORY_LABELS.get(ticket['category'], ticket['category'])}, {ticket['branch']}; "
        f"actualizado el {_date(ticket['updated_at'])})"
    )


def _filters_text(query: dict[str, Any]) -> str:
    parts = []
    if "status" in query:
        parts.append(f"en estado {STATUS_LABELS.get(query['status'], query['status'])}")
    if "category" in query:
        parts.append(f"de tipo {CATEGORY_LABELS.get(query['category'], query['category'])}")
    if "origin" in query:
        parts.append(f"con origen {ORIGIN_LABELS.get(query['origin'], query['origin'])}")
    if "branch" in query:
        parts.append(f"de la sucursal {query['branch']}")
    return " ".join(parts)


def tickets_answer(result: dict[str, Any]) -> str:
    tickets = result["records"]
    if "ticket_id" in result["query"]:
        ticket = tickets[0]
        return (
            f"El ticket {ticket['id']} «{ticket['title']}» está {STATUS_LABELS.get(ticket['status'], ticket['status'])} "
            f"(categoría: {CATEGORY_LABELS.get(ticket['category'], ticket['category'])}; "
            f"origen: {ORIGIN_LABELS.get(ticket['origin'], ticket['origin'])}; sucursal: {ticket['branch']}). "
            f"Se creó el {_date(ticket['created_at'])} y se actualizó por última vez el {_date(ticket['updated_at'])}.\n"
            f"{INCIDENTS_SOURCE}"
        )
    filters = _filters_text(result["query"])
    noun = "ticket" if result["total"] == 1 else "tickets"
    header = f"Hay {result['total']} {noun}{' ' + filters if filters else ''}."
    if result["total"] > len(tickets):
        header += f" Estos son los {len(tickets)} actualizados más recientemente:"
    lines = "\n".join(_ticket_line(ticket) for ticket in tickets)
    return f"{header}\n{lines}\n{INCIDENTS_SOURCE}"


def inventory_answer(result: dict[str, Any]) -> str:
    products = result["records"]
    lines = "\n".join(
        f"- {p['name']} (SKU {p['sku']}, cliente {p['client_name']}): {p['current_stock']} unidades en stock"
        for p in products
    )
    header = "Stock actual (total entre almacenes):"
    if result["total"] > len(products):
        header = f"Hay {result['total']} productos que coinciden; estos son los {len(products)} primeros (stock total entre almacenes):"
    return f"{header}\n{lines}\n{INVENTORY_SOURCE}"


def fallback_message(result: dict[str, Any]) -> str:
    """Respuesta honesta cuando la tool no pudo dar el dato. Nunca afirma un estado ni un stock."""
    query = result["query"]
    if result["tool"] == "incidents":
        subject = f"del ticket {query['ticket_id']}" if "ticket_id" in query else "de esos tickets"
        if result["status"] == "not_found":
            if "ticket_id" in query:
                return (
                    f"No encuentro el ticket {query['ticket_id']} en el gestor de incidentes, así que no puedo "
                    "confirmar su estado. Revisa el número del ticket."
                )
            return "No hay tickets que coincidan con esos criterios en el gestor de incidentes."
        return (
            f"No he podido confirmar el estado {subject} ahora mismo: el gestor de incidentes no responde. "
            "Inténtalo de nuevo en unos minutos."
        )
    product = f"el SKU {query['sku']}" if "sku" in query else f"el producto «{query.get('product_name', '')}»"
    if result["status"] == "not_found":
        return f"No encuentro {product} en el gestor de inventario, así que no puedo confirmar su stock."
    stock_of = f"del SKU {query['sku']}" if "sku" in query else f"del producto «{query.get('product_name', '')}»"
    return (
        f"No he podido confirmar el stock {stock_of} ahora mismo: el gestor de inventario no responde. "
        "Inténtalo de nuevo en unos minutos."
    )


def tool_section(result: dict[str, Any]) -> str:
    if result["status"] != "ok":
        return result.get("fallback_message") or fallback_message(result)
    return tickets_answer(result) if result["tool"] == "incidents" else inventory_answer(result)
