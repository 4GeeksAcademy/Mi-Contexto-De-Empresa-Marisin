"""Tarifario de referencia de TrackFlow para las propuestas económicas (Parte 2).

El BRIEFING del Hito 9 fija las reglas (moneda por país, SLA, devoluciones ≥ 48 h,
tabla de descuentos, sin tarifas de transportistas) pero no los precios. Las
cifras salen de dos sitios, y ninguna la inventa el generador:

- **Base de conocimiento** (`docs/company-knowledge-base/`, el corpus del RAG del
  Hito 7): almacenamiento 18 USD/m³ (Los Ángeles) y 16 EUR/m³ (Zaragoza), 30 días
  de gracia, 150 % desde el día 181, SLA del 90 % con compensación del 5 %,
  plazos estándar/express y ventana de devolución de 30 días.
- **Tarifario de referencia de este módulo** (aprobado para el proyecto como
  lista de precios base de Dirección Comercial): preparación de pedidos, precio
  final por envío por tramo de peso, procesamiento de devoluciones, onboarding y
  la tabla de descuentos por volumen. Son precios finales al cliente: no
  contienen ni derivan de tarifas negociadas con transportistas (BRIEFING §5).

Los descuentos por volumen se aplican a los cargos por pedido, envío y devolución;
el almacenamiento solo se negocia con Miguel Torres (base de conocimiento).
Los números se escriben en formato español (`1,40`, `5.000`) y este texto es
también la «fuente» contra la que el evaluador ancla cada cifra del borrador.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tramos de volumen mensual (pedidos/mes) → descuento sobre cargos variables.
VOLUME_TIERS: tuple[tuple[int, int | None, int], ...] = (
    (0, 4999, 0),
    (5000, 9999, 5),
    (10000, 24999, 8),
    (25000, None, 12),
)


@dataclass(frozen=True)
class Tariff:
    currency: str
    site: str  # almacén que da servicio
    storage_m3_month: str
    pick_pack_per_order: str
    shipping_up_to_2kg: str
    shipping_2_to_5kg: str
    shipping_over_5kg: str
    return_processing_per_unit: str
    refurbish_per_unit: str


TARIFFS: dict[str, Tariff] = {
    "USD": Tariff("USD", "Los Ángeles", "18", "1,40", "6,90", "8,90", "12,50", "2,80", "1,50"),
    "EUR": Tariff("EUR", "Zaragoza", "16", "1,25", "4,90", "6,50", "9,20", "2,40", "1,30"),
}

# Constantes de servicio (base de conocimiento + tarifario).
SLA_ON_TIME_PERCENT = 90
SLA_COMPENSATION_PERCENT = 5
STORAGE_GRACE_DAYS = 30
LONG_TERM_STORAGE_PERCENT = 150
LONG_TERM_STORAGE_FROM_DAY = 181
PREFERENTIAL_STORAGE_M3 = 50
RETURNS_PROCESSING_HOURS = 72  # siempre ≥ 48 h (BRIEFING §5)
RETURN_WINDOW_DAYS = 30
ONBOARDING_BUSINESS_DAYS = 10


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def tier_label(low: int, high: int | None) -> str:
    if high is None:
        return f"{_thousands(low)} o más"
    if low == 0:
        return f"Hasta {_thousands(high)}"
    return f"{_thousands(low)} a {_thousands(high)}"


def applicable_tier(monthly_volume: int | None) -> tuple[str, int] | None:
    """Tramo y descuento para el volumen de la RFP; `None` si la RFP no lo indica."""
    if monthly_volume is None:
        return None
    for low, high, discount in VOLUME_TIERS:
        if monthly_volume >= low and (high is None or monthly_volume <= high):
            return tier_label(low, high), discount
    return None


def discount_table() -> str:
    """Tabla Markdown de descuentos por volumen (BRIEFING §5)."""
    rows = ["| Pedidos al mes | Descuento por volumen |", "|---|---|"]
    rows += [f"| {tier_label(low, high)} | {discount} % |" for low, high, discount in VOLUME_TIERS]
    return "\n".join(rows)


def department_price_lines(department_id: str, currency: str) -> list[tuple[str, str]]:
    """(concepto, precio) de la tabla de precios de un departamento."""
    t = TARIFFS[currency]
    c = t.currency
    if department_id == "warehouse":
        return [
            ("Almacenamiento (por m³ ocupado al mes)", f"{t.storage_m3_month} {c}"),
            (f"Primeros {STORAGE_GRACE_DAYS} días de cada producto nuevo", f"0 {c} (periodo de gracia)"),
            ("Preparación y empaquetado (por pedido)", f"{t.pick_pack_per_order} {c}"),
            (f"Inventario sin movimiento desde el día {LONG_TERM_STORAGE_FROM_DAY}",
             f"{LONG_TERM_STORAGE_PERCENT} % de la tarifa de almacenamiento"),
        ]
    if department_id == "lastmile":
        return [
            ("Envío estándar hasta 2 kg (precio final por envío)", f"{t.shipping_up_to_2kg} {c}"),
            ("Envío estándar de 2 a 5 kg (precio final por envío)", f"{t.shipping_2_to_5kg} {c}"),
            ("Envío estándar de más de 5 kg (precio final por envío)", f"{t.shipping_over_5kg} {c}"),
        ]
    if department_id == "reverse":
        return [
            ("Recepción, inspección y clasificación (por unidad devuelta)", f"{t.return_processing_per_unit} {c}"),
            ("Reacondicionamiento y restock (por unidad)", f"{t.refurbish_per_unit} {c}"),
        ]
    raise KeyError(department_id)


def price_table(department_id: str, currency: str) -> str:
    rows = ["| Concepto | Precio |", "|---|---|"]
    rows += [f"| {concept} | {price} |" for concept, price in department_price_lines(department_id, currency)]
    return "\n".join(rows)


def service_terms(department_id: str, currency: str) -> list[str]:
    """Condiciones de servicio (sin precios) que acompañan a la tabla del departamento."""
    t = TARIFFS[currency]
    common = [
        f"SLA de entrega a tiempo: TrackFlow se compromete a un {SLA_ON_TIME_PERCENT} % de entregas a tiempo "
        f"al mes, medido por país; si baja del {SLA_ON_TIME_PERCENT} % dos meses seguidos, el cliente recibe "
        f"una compensación del {SLA_COMPENSATION_PERCENT} % de la tarifa mensual de ese país.",
    ]
    if department_id == "warehouse":
        return common + [
            f"Servicio desde el almacén de {t.site}.",
            f"Onboarding en {ONBOARDING_BUSINESS_DAYS} días hábiles desde la firma.",
            f"Con más de {PREFERENTIAL_STORAGE_M3} m³ de media al mes se puede negociar una tarifa de "
            "almacenamiento preferente, siempre con Miguel Torres.",
        ]
    if department_id == "lastmile":
        return common + [
            "Envío estándar: 3 a 5 días hábiles dentro del mismo país.",
            "Envío express: 24 a 48 horas en zonas metropolitanas (Los Ángeles y Zaragoza-Madrid).",
            "El sistema de TrackFlow elige el transportista de cada envío según destino, peso y urgencia.",
            "En días de alta demanda (Black Friday, Navidad) los plazos pueden alargarse y se avisa antes.",
        ]
    if department_id == "reverse":
        return common + [
            f"Plazo de procesamiento de cada devolución: {RETURNS_PROCESSING_HOURS} horas desde que llega al almacén.",
            f"Ventana de devolución estándar: {RETURN_WINDOW_DAYS} días desde la entrega.",
            "TrackFlow ejecuta la logística según las reglas de la marca; no revende producto por su cuenta.",
        ]
    raise KeyError(department_id)


def reference_text(department_id: str, currency: str) -> str:
    """Todo lo que el generador puede citar de precios y condiciones (y su ancla de cifras)."""
    return "\n".join(
        [
            f"TARIFARIO DE REFERENCIA ({currency}) — {department_id}",
            price_table(department_id, currency),
            "",
            "TABLA DE DESCUENTOS POR VOLUMEN (sobre cargos por pedido, envío y devolución)",
            discount_table(),
            "",
            "CONDICIONES",
            *[f"- {term}" for term in service_terms(department_id, currency)],
        ]
    )
