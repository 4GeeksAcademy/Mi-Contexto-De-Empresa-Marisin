from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TelemetryEvent(BaseModel):
    """Telemetry envelope contract, reusable without changes in project 3."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event_id: UUID = Field(alias="eventId")
    timestamp: AwareDatetime
    session_id: UUID = Field(alias="sessionId")
    user_id: str | None = Field(alias="userId", min_length=1)
    event_type: str = Field(pattern=r"^[a-z]+(_[a-z]+)+$")
    schema_version: str = Field(alias="schemaVersion", pattern=r"^\d+\.\d+\.\d+$")
    request_id: UUID = Field(alias="requestId")
    properties: dict[str, Any]


class TelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TelemetryEvent] = Field(max_length=50)
