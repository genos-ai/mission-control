"""
Mission Artifact API schemas (Plan 43).

Pydantic response shape for the durable mission artifacts table.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MissionArtifactResponse(BaseModel):
    """Single artifact row in the API response.

    Mirrors ``models/mission_artifact.py::MissionArtifact`` one-to-one
    so the frontend can read the API response with no field mapping.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    execution_record_id: str | None = None
    task_execution_id: str | None = None

    agent_id: str
    artifact_type: str
    title: str
    content_type: str
    language: str | None = None

    content_text: str | None = None
    storage_url: str | None = None

    created_at: datetime
    updated_at: datetime
