"""Validacion y transformacion compartida para el historico de incidencias."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

REQUIRED_FIELDS = (
    "incident_id",
    "date",
    "country",
    "customer_type",
    "tracking_number",
    "carrier",
    "category",
    "description",
    "status",
    "customer_email",
)
VALID_CATEGORIES = (
    "RETURN_REQUEST",
    "DAMAGE",
    "DELAYED_DELIVERY",
    "WRONG_ADDRESS",
    "LOST_PARCEL",
)
VALID_STATUSES = ("OPEN", "CLOSED", "DISCARDED")
INCIDENT_CATEGORIES = (
    "RETURN_REQUEST",
    "DAMAGE",
    "DELAYED_DELIVERY",
    "WRONG_ADDRESS",
    "LOST_PARCEL",
)
INCIDENT_STATUSES = ("open", "in_progress", "resolved", "discarded")
INCIDENT_ORIGINS = ("customer", "branch", "internal")
INCIDENT_BRANCHES = ("Los Angeles", "Zaragoza", "central")


class IncidentStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    discarded = "discarded"


class IncidentOrigin(str, Enum):
    customer = "customer"
    branch = "branch"
    internal = "internal"


class IncidentCategory(str, Enum):
    return_request = "RETURN_REQUEST"
    damage = "DAMAGE"
    delayed_delivery = "DELAYED_DELIVERY"
    wrong_address = "WRONG_ADDRESS"
    lost_parcel = "LOST_PARCEL"


class IncidentBranch(str, Enum):
    los_angeles = "Los Angeles"
    zaragoza = "Zaragoza"
    central = "central"
COUNTRY_TO_BRANCH = {
    "United States": "Los Angeles",
    "Spain": "Zaragoza",
}
STATUS_TO_INCIDENT_STATUS = {
    "OPEN": "open",
    "CLOSED": "resolved",
    "DISCARDED": "discarded",
}


@dataclass(frozen=True)
class ValidationResult:
    """Resultado de validacion con la primera razon detectada."""

    valid: bool
    reason: str | None = None
    field: str | None = None


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def validate_csv_row(row: Mapping[str, Any]) -> ValidationResult:
    """Replica el orden de validacion de scripts/analyze.py."""
    for field in REQUIRED_FIELDS:
        if field not in row or _is_blank(row[field]):
            return ValidationResult(False, "missing_fields", field)

    if row["category"] not in VALID_CATEGORIES:
        return ValidationResult(False, "invalid_category", "category")

    if row["status"] not in VALID_STATUSES:
        return ValidationResult(False, "invalid_status", "status")

    if row["country"] not in COUNTRY_TO_BRANCH:
        return ValidationResult(False, "invalid_country", "country")

    return ValidationResult(True)


def parse_csv_date(value: Any) -> str:
    """Normaliza fechas ISO y fechas habituales del CSV a ISO 8601."""
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, date_format).isoformat()
            except ValueError:
                continue
    raise ValueError(f"Formato de fecha no valido: {text}")


def transform_csv_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convierte una fila validada al documento persistible de Incident."""
    result = validate_csv_row(row)
    if not result.valid:
        raise ValueError(f"Fila invalida en {result.field}: {result.reason}")

    created_at = parse_csv_date(row["date"])
    return {
        "source_incident_id": str(row["incident_id"]).strip(),
        "title": str(row["description"]).strip(),
        "description": str(row["description"]).strip(),
        "category": str(row["category"]),
        "status": STATUS_TO_INCIDENT_STATUS[str(row["status"])],
        "origin": "customer",
        "branch": COUNTRY_TO_BRANCH[str(row["country"])],
        "created_at": created_at,
        "updated_at": created_at,
    }
