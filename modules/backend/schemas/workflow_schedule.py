"""
Workflow Schedule API Schemas.

Request/response models for cron-based workflow execution schedules.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkflowScheduleResponse(BaseModel):
    """Response for a workflow schedule entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_definition_id: str
    mission_id: str
    cron_expression: str
    timezone: str
    enabled: bool
    description: str
    budget_per_run_usd: float | None
    max_iterations: int | None
    iteration_count: int
    cooldown_seconds: int
    last_fired_at: datetime | None
    next_fire_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class WorkflowScheduleCreateRequest(BaseModel):
    """Request to create a workflow schedule."""

    model_config = ConfigDict(extra="forbid")

    workflow_definition_id: str = Field(
        ...,
        min_length=1,
        max_length=36,
    )
    cron_expression: str = Field(
        ...,
        min_length=9,
        max_length=100,
        description="Standard 5-field cron: minute hour day month weekday",
    )
    timezone: str = Field(
        default="UTC",
        max_length=50,
    )
    description: str = Field(
        default="",
        max_length=2000,
    )
    budget_per_run_usd: float | None = Field(
        None,
        ge=0.01,
        description="USD ceiling per individual run",
    )
    max_iterations: int | None = Field(
        None,
        ge=1,
        description="Total runs this schedule may create (NULL = unlimited)",
    )
    cooldown_seconds: int = Field(
        default=0,
        ge=0,
        description="Minimum seconds between consecutive runs",
    )


class WorkflowScheduleUpdateRequest(BaseModel):
    """Request to update a workflow schedule."""

    model_config = ConfigDict(extra="forbid")

    cron_expression: str | None = Field(
        None,
        min_length=9,
        max_length=100,
    )
    timezone: str | None = Field(None, max_length=50)
    enabled: bool | None = None
    description: str | None = Field(None, max_length=2000)
    budget_per_run_usd: float | None = None
    max_iterations: int | None = None
    cooldown_seconds: int | None = Field(None, ge=0)
