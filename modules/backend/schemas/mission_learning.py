"""Pydantic schemas for mission learnings — create, response, list, filter."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from modules.backend.schemas.knowledge import Evidence


class MissionLearningCreate(BaseModel):
    """Request body for creating a learning entry."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        ...,
        description="failure_pattern | success_pattern | anti_pattern | retry_strategy | capability_gap",  # noqa: E501
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
    )
    body: str = Field(
        ...,
        min_length=1,
    )
    recommendation: str = Field(
        ...,
        min_length=1,
    )
    evidence: Evidence = Field(
        default_factory=Evidence,
    )
    domain_tags: list[str] = Field(default_factory=list)
    agent_names: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    occurrence_count: int = Field(default=1, ge=1)


class MissionLearningResponse(BaseModel):
    """Response for a single learning entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    kind: str
    title: str
    body: str
    recommendation: str
    evidence: dict
    domain_tags: list
    agent_names: list
    confidence: float
    occurrence_count: int
    platform_promoted: bool
    promoted_at: str | datetime | None = None
    promoted_by: str | None = None
    contradicts_id: str | None = None
    status: str
    created_at: str | datetime
    updated_at: str | datetime


class MissionLearningListResponse(BaseModel):
    """Paginated list of learnings."""

    items: list[MissionLearningResponse]
    total: int


class MissionLearningFilter(BaseModel):
    """Filter parameters for listing learnings."""

    model_config = ConfigDict(extra="forbid")

    kind: str | None = None
    domain_tags: list[str] | None = None
    status: str | None = Field(default="active")
    platform_only: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
