"""
Research Report API schemas (Plan 40 §5).

Pydantic response shapes for the research reports API.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ResearchReportResponse(BaseModel):
    """Full research report for API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    execution_id: str | None = None
    query: str
    report_markdown: str
    report_structured: dict[str, Any]
    sources: list[dict[str, Any]]
    metadata_json: dict[str, Any]
    status: str
    tags: list[str]
    citation_count: int
    verification_score: float | None = None
    created_at: datetime
    updated_at: datetime


class ResearchReportSummary(BaseModel):
    """Lightweight summary for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    query: str
    status: str
    citation_count: int
    verification_score: float | None = None
    created_at: datetime
