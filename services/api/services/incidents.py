from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from fastapi import HTTPException

from ..database import incidents_table
from ..models import (
    IncidentCategory,
    IncidentCreate,
    IncidentOrigin,
    IncidentStatus,
    IncidentStatusUpdate,
)

ALLOWED_TRANSITIONS = {
    IncidentStatus.open.value: {
        IncidentStatus.in_progress.value,
        IncidentStatus.discarded.value,
    },
    IncidentStatus.in_progress.value: {
        IncidentStatus.resolved.value,
        IncidentStatus.discarded.value,
    },
    IncidentStatus.resolved.value: set(),
    IncidentStatus.discarded.value: set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(doc_id: int, item: dict) -> dict:
    return {**item, "id": str(doc_id)}


def list_incidents(
    status: Optional[IncidentStatus] = None,
    origin: Optional[IncidentOrigin] = None,
    branch: Optional[str] = None,
    category: Optional[IncidentCategory] = None,
) -> list[dict]:
    results = []
    for item in incidents_table.all():
        if status and item.get("status") != status.value:
            continue
        if origin and item.get("origin") != origin.value:
            continue
        if branch and item.get("branch") != branch:
            continue
        if category and item.get("category") != category.value:
            continue
        results.append(_serialize(item.doc_id, item))
    return results


def get_incident(incident_id: int) -> dict:
    item = incidents_table.get(doc_id=incident_id)
    if item is None:
        raise HTTPException(status_code=404, detail="La incidencia no existe")
    return _serialize(incident_id, item)


def create_incident(payload: IncidentCreate) -> dict:
    now = _now()
    data = payload.dict()
    data.update({"created_at": now, "updated_at": now})
    doc_id = incidents_table.insert(data)
    return _serialize(doc_id, incidents_table.get(doc_id=doc_id))


def update_incident_status(incident_id: int, payload: IncidentStatusUpdate) -> dict:
    current = get_incident(incident_id)
    current_status = current["status"]
    next_status = payload.status.value
    if next_status not in ALLOWED_TRANSITIONS[current_status]:
        raise HTTPException(
            status_code=400,
            detail={
                "field": "status",
                "message": f"No se puede cambiar de {current_status} a {next_status}",
            },
        )

    incidents_table.update(
        {"status": next_status, "updated_at": _now()}, doc_ids=[incident_id]
    )
    return get_incident(incident_id)


def summary() -> dict:
    status_totals = {status.value: 0 for status in IncidentStatus}
    category_totals = {category.value: 0 for category in IncidentCategory}
    origin_totals = {origin.value: 0 for origin in IncidentOrigin}
    branch_totals = {"Los Angeles": 0, "Zaragoza": 0, "central": 0}

    for item in incidents_table.all():
        for totals, key in (
            (status_totals, "status"),
            (category_totals, "category"),
            (origin_totals, "origin"),
            (branch_totals, "branch"),
        ):
            if item.get(key) in totals:
                totals[item[key]] += 1

    return {
        "total": len(incidents_table),
        "by_status": status_totals,
        "by_category": category_totals,
        "by_origin": origin_totals,
        "by_branch": branch_totals,
    }
