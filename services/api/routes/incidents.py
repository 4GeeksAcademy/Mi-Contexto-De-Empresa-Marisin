from typing import List, Optional

from fastapi import APIRouter, Query

from ..models import (
    Incident,
    IncidentCategory,
    IncidentCreate,
    IncidentOrigin,
    IncidentStatus,
    IncidentStatusUpdate,
    IncidentSummary,
)
from ..services.incidents import (
    create_incident,
    get_incident,
    list_incidents,
    summary,
    update_incident_status,
)

router = APIRouter(prefix="/api/incidents", tags=["Incidents"])


@router.post("", response_model=Incident, status_code=201)
def post_incident(payload: IncidentCreate):
    return create_incident(payload)


@router.get("", response_model=List[Incident])
def get_incidents(
    status: Optional[IncidentStatus] = None,
    origin: Optional[IncidentOrigin] = None,
    branch: Optional[str] = Query(default=None),
    category: Optional[IncidentCategory] = None,
):
    return list_incidents(status, origin, branch, category)


@router.get("/summary", response_model=IncidentSummary)
def get_incidents_summary():
    return summary()


@router.get("/{incident_id}", response_model=Incident)
def get_incident_detail(incident_id: int):
    return get_incident(incident_id)


@router.patch("/{incident_id}/status", response_model=Incident)
def patch_incident_status(incident_id: int, payload: IncidentStatusUpdate):
    return update_incident_status(incident_id, payload)
