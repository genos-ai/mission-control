"""
Mission Team API Schemas.

Request/response models for per-mission agent team management.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MissionTeamMemberResponse(BaseModel):
    """Response for a team member entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    agent_catalog_id: str
    user_prompt: str | None
    user_prompt_version: int
    enabled: bool
    display_order: int
    custom_constraints: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class MissionTeamAddRequest(BaseModel):
    """Request to add an agent to a mission team."""

    model_config = ConfigDict(extra="forbid")

    agent_catalog_id: str = Field(
        ..., min_length=1, max_length=36,
        description="UUID of the agent from the catalog",
    )
    user_prompt: str | None = Field(
        None, max_length=10000,
        description="Mission-specific instructions for this agent",
    )
    display_order: int = Field(default=0, ge=0)
    custom_constraints: dict[str, Any] | None = None


class UserPromptUpdateRequest(BaseModel):
    """Request to update a team member's user prompt."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1, max_length=10000)
    changed_by: str = Field(..., min_length=1, max_length=200)
    change_reason: str | None = Field(None, max_length=1000)
