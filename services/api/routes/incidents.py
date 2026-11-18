from typing import List, Optional

from fastapi import APIRouter, Query, Response

from ..cache import (
    CACHE_ENABLED,
    INCIDENTS_SUMMARY_KEY,
    INCIDENTS_SUMMARY_TTL,
    api_cache,
)
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
    incident = create_incident(payload)
    api_cache.invalidate(INCIDENTS_SUMMARY_KEY)
    return incident


@router.get("", response_model=List[Incident])
def get_incidents(
    status: Optional[IncidentStatus] = None,
    origin: Optional[IncidentOrigin] = None,
    branch: Optional[str] = Query(default=None),
    category: Optional[IncidentCategory] = None,
):
    return list_incidents(status, origin, branch, category)


# No JWT or per-user details: only global counters are shared.
@router.get("/summary", response_model=IncidentSummary)
def get_incidents_summary(response: Response):
    if CACHE_ENABLED:
        hit, cached = api_cache.get(INCIDENTS_SUMMARY_KEY)
        if hit:
            response.headers["X-Cache"] = "HIT"
            return dict(cached)

    result = summary()
    if CACHE_ENABLED:
        api_cache.set(INCIDENTS_SUMMARY_KEY, result, ttl=INCIDENTS_SUMMARY_TTL)
        response.headers["X-Cache"] = "MISS"
    else:
        response.headers["X-Cache"] = "BYPASS"
    return result


@router.get("/{incident_id}", response_model=Incident)
def get_incident_detail(incident_id: int):
    return get_incident(incident_id)


@router.patch("/{incident_id}/status", response_model=Incident)
def patch_incident_status(incident_id: int, payload: IncidentStatusUpdate):
    incident = update_incident_status(incident_id, payload)
    api_cache.invalidate(INCIDENTS_SUMMARY_KEY)
    return incident
