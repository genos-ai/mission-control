"""Pydantic schemas for mission intents — create, response, list."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MissionIntentCreate(BaseModel):
    """Request body for creating / revising an intent."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The full intent text",
    )
    scope: dict = Field(
        default_factory=dict,
        description='Structured scope: {"in": [...], "out": [...]}',
    )
    source: str = Field(
        ...,
        description="How captured: user_chat | user_cli | director_inferred | system",
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Why this revision was made",
    )
    agent_id: str | None = Field(
        default=None,
        description="Agent that captured this intent (if director_inferred)",
    )
    session_id: str | None = Field(
        default=None,
        description="Session in which the intent was captured",
    )


class MissionIntentResponse(BaseModel):
    """Response for a single intent revision."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    intent: str
    intent_summary: str
    scope: dict
    source: str
    revised_from: str | None = None
    reason: str
    agent_id: str | None = None
    session_id: str | None = None
    created_at: str | datetime


class MissionIntentListResponse(BaseModel):
    """Paginated list of intent revisions."""

    items: list[MissionIntentResponse]
    total: int
