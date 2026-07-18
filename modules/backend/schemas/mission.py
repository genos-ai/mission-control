"""
Mission API schemas.

Pydantic models for mission creation, update, and response serialization.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MissionCreate(BaseModel):
    """Schema for creating a new mission."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="Unique mission name (lowercase, hyphens, underscores)",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Mission purpose and scope",
    )
    brief: str | None = Field(
        None,
        max_length=10000,
        description="Strategic directive that agents read to understand their purpose",
    )
    owner_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Primary human owner identifier",
    )
    team_id: str | None = Field(
        None,
        max_length=200,
        description="Optional team identifier",
    )
    default_roster: str = Field(
        default="default",
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="Default agent roster for this mission",
    )
    budget_ceiling_usd: float | None = Field(
        None,
        ge=0.01,
        description="Mission-level spend cap",
    )
    repo_url: str | None = Field(
        None,
        max_length=2000,
        description="Source repository URL",
    )
    repo_root: str | None = Field(
        None,
        max_length=1000,
        description="Local filesystem root path",
    )
    tier: str = Field(
        default="user",
        pattern=r"^(user|platform)$",
        description="Mission tier: user (standard) or platform (admin-only)",
    )
    execution_environment: str | None = Field(
        None,
        pattern=r"^(local|worktree|container)$",
        description="Default execution environment for this mission. NULL = local.",
    )


class MissionUpdate(BaseModel):
    """Schema for updating a mission."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(None, min_length=1, max_length=2000)
    brief: str | None = Field(None, max_length=10000)
    status: str | None = Field(None, pattern=r"^(active|paused|archived)$")
    default_roster: str | None = Field(None, pattern=r"^[a-z][a-z0-9_-]*$")
    budget_ceiling_usd: float | None = None
    repo_url: str | None = None
    repo_root: str | None = None
    execution_environment: str | None = Field(
        None,
        pattern=r"^(local|worktree|container)$",
        description="Default execution environment. Set to 'container' for Docker isolation.",
    )


class MissionResponse(BaseModel):
    """Schema for mission API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    brief: str | None
    status: str
    owner_id: str
    team_id: str | None
    default_roster: str
    budget_ceiling_usd: float | None
    repo_url: str | None
    repo_root: str | None
    tier: str
    execution_environment: str | None
    created_at: datetime
    updated_at: datetime


class MissionMemberResponse(BaseModel):
    """Schema for mission member API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    user_id: str
    role: str
    created_at: datetime


class MissionMemberAddRequest(BaseModel):
    """Request to add a human user to a mission."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(
        ...,
        min_length=1,
        max_length=36,
        description="UUID of the user to add",
    )
    role: str = Field(
        default="viewer",
        pattern=r"^(owner|maintainer|viewer)$",
        description="Mission role for the user",
    )


class MissionMemberUpdateRequest(BaseModel):
    """Request to update a mission member's role."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(
        ...,
        pattern=r"^(owner|maintainer|viewer)$",
        description="New mission role",
    )
