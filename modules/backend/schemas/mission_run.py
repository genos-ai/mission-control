"""Mission run schemas (Plan 88 step 88.1.7, contracts 3.5.3 and 3.0.2).

Enum fields use the lowercase enum value on the wire.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.backend.core.config import get_app_config
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.mission_run import (
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_run_digest import DigestGenerator
from modules.backend.models.task import TaskStatus


class MissionRunCreate(BaseModel):
    """POST /missions/{id}/runs body."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(..., min_length=1)

    @field_validator("objective")
    @classmethod
    def _within_limit(cls, value: str) -> str:
        limit = get_app_config().missions.recurrence.objective_template_max_chars
        if len(value) > limit:
            raise ValueError(f"objective exceeds {limit} characters")
        return value


class MissionRunResponse(BaseModel):
    """One mission run, every column."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    plan_id: str
    schedule_id: str | None
    sequence: int
    trigger: MissionRunTrigger
    triggered_by_user_id: str | None
    scheduled_for: datetime | None
    previous_run_id: str | None
    objective: str | None
    workflow_definition_id: str | None
    workflow_parameters: dict[str, Any]
    status: MissionRunStatus
    status_reason: MissionRunStatusReason | None
    status_detail: str | None
    gate_mode: GateMode | None
    temporal_workflow_id: str | None
    session_id: str | None
    context_version_start: int | None
    context_version_end: int | None
    iteration_count: int
    budget_cap_usd: float | None
    cost_usd: float
    task_count: int
    completed_task_count: int
    failed_task_count: int
    config_snapshot: dict[str, Any]
    cancel_requested_at: datetime | None
    cancel_requested_by_user_id: str | None
    cancel_reason: MissionRunStatusReason | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MissionRunDigestResponse(BaseModel):
    """A run's digest (written from Phase 3)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_run_id: str
    mission_id: str
    schema_version: int
    generator: DigestGenerator
    summary: str
    outcomes: list[Any]
    decisions: list[Any]
    open_items: list[Any]
    context_changes: list[Any]
    metrics: dict[str, Any]
    generation_cost_usd: float
    created_at: datetime


class TaskSummary(BaseModel):
    """A task owned by a run, as listed in the run detail."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    agent: str
    description: str
    status: TaskStatus
    failure_reason: str | None
    cost_usd: float
    created_at: datetime


class MissionRunDetailResponse(BaseModel):
    """GET /missions/{id}/runs/{run_id_or_seq} body. 88.4.8 adds gates."""

    run: MissionRunResponse
    execution_record_id: str | None
    digest: MissionRunDigestResponse | None
    tasks: list[TaskSummary]


class MissionRunListResponse(BaseModel):
    """GET /missions/{id}/runs body, newest sequence first."""

    runs: list[MissionRunResponse]
    next_before_sequence: int | None
