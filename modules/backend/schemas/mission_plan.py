"""
Mission Plan API schemas (Plan 42).

Pydantic models for the long-lived mission backlog endpoints. The plan
body itself is a `TaskPlan` (schemas/task_plan.py) carried verbatim in
the response — this file only defines the wrapper metadata and the
per-task state shape.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from modules.backend.models.mission_plan import (
    VALID_GATE_MODES,
    MissionPlanStatus,
    PlanTaskStatus,
)


# ── Plan-level ───────────────────────────────────────────────────────────


class AddPlanTaskRequest(BaseModel):
    """POST /missions/:id/plan/tasks body — add a single proposed task."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1, max_length=2000)
    agent: str = Field(..., min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=4000)
    dependencies: list[str] = Field(default_factory=list)


class MissionPlanRefineRequest(BaseModel):
    """POST /missions/:id/plan/refine body.

    The Director (or user) provides natural-language instructions that the
    Planning Agent uses to revise the current TaskPlan. Plan 42 §10.4.
    """

    model_config = ConfigDict(extra="forbid")

    instructions: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description=(
            "Natural-language refinement instructions. The Planning Agent "
            "receives these alongside the current TaskPlan and the mission "
            "brief, and produces a new TaskPlan that incorporates the "
            "requested changes while preserving task_ids where possible."
        ),
    )


class MissionPlanUpdate(BaseModel):
    """Schema for PATCH /missions/:id/plan.

    All fields optional — the service applies only the ones present.
    """

    model_config = ConfigDict(extra="forbid")

    gate_mode: str | None = Field(
        None,
        description=(
            f"Autonomy mode. One of: {sorted(VALID_GATE_MODES)}. Mirrors "
            f"config/settings/gate.yaml values. Plan 42 section 10.4."
        ),
    )
    status: str | None = Field(
        None,
        description=f"Plan lifecycle: {[s.value for s in MissionPlanStatus]}",
    )
    budget_usd_ceiling: float | None = Field(
        None, ge=0.0,
        description="Cumulative cap across all runs from this plan",
    )
    veto_window_sec: int | None = Field(
        None, ge=1, le=3600,
        description=(
            "For ai_assisted mode: seconds a user has to veto an auto-"
            "approved task before it queues. NULL = no veto window."
        ),
    )
    task_order: list[str] | None = Field(
        None,
        description=(
            "Desired display order for proposed tasks — list of task_ids. "
            "Tasks in this list are sorted to match; tasks not in the list "
            "keep their current relative position after. Used by the kanban "
            "drag-to-reorder UI (Phase 4)."
        ),
    )


class PlanTaskStateResponse(BaseModel):
    """Per-task state row as seen by the Plan tab."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    status: str
    approved_by_user_id: str | None
    approved_at: datetime | None
    execution_record_id: str | None
    task_execution_id: str | None
    last_attempt_at: datetime | None
    retry_count: int
    veto_expires_at: datetime | None
    result_summary: str | None
    failure_reason: str | None
    # Plan 46 Phase 2 #2: per-task cost + duration denormalised from
    # task_executions at run completion so the Plan tab's Done cards
    # render "$X.XX · Ns" without a separate join.
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    created_at: datetime
    updated_at: datetime


class MissionPlanResponse(BaseModel):
    """Full plan with all task states.

    The `task_plan_json` field carries the TaskPlan verbatim — the
    frontend parses it to get task bodies (title, agent, description,
    dependencies, instructions, etc.) and joins with `task_states` by
    the string `task_id` to get per-task status.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    task_plan_json: dict | None = Field(
        None,
        description=(
            "Live TaskPlan as stored in the DB. NULL until the first "
            "refinement. Shape: schemas/task_plan.py::TaskPlan."
        ),
    )
    gate_mode: str | None
    status: str
    version: int
    budget_usd_ceiling: float | None
    total_spent_usd: float
    veto_window_sec: int | None
    task_states: list[PlanTaskStateResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Task-level transitions ───────────────────────────────────────────────


class DispatchApprovedResponse(BaseModel):
    """Result of POST /missions/:id/plan/dispatch (Plan 42 §10.1)."""

    model_config = ConfigDict(extra="forbid")

    outcome_status: str = Field(
        ...,
        description="Dispatch result: success | partial | failed",
    )
    execution_record_id: str | None = Field(
        None,
        description="ExecutionRecord row for this run (Plan 15). None on failure.",
    )
    dispatched_task_ids: list[str] = Field(
        default_factory=list,
        description="task_ids included in the derived subset TaskPlan",
    )
    updated_task_ids: list[str] = Field(
        default_factory=list,
        description="task_ids whose plan_task_state was written back post-run",
    )
    total_cost_usd: float = Field(
        ...,
        description="Cost of this individual run",
    )
    new_total_spent_usd: float = Field(
        ...,
        description=(
            "Cumulative total across all runs dispatched from this plan, "
            "including this one"
        ),
    )


class TaskTransitionResponse(BaseModel):
    """Result of an approve / reject / retry call.

    Returns the IDs of all tasks that were actually transitioned so the
    frontend can highlight the dep-closure effect (e.g. "approving this
    task also approved 2 dependencies").
    """

    model_config = ConfigDict(extra="forbid")

    target_task_id: str = Field(
        ...,
        description="The task_id the user explicitly acted on",
    )
    transitioned_task_ids: list[str] = Field(
        default_factory=list,
        description=(
            "All task_ids whose state actually changed as a result of this "
            "call. Includes transitive dependencies on approve, transitive "
            "dependents on reject. The target is always first."
        ),
    )
    new_status: str = Field(
        ...,
        description=f"Target status after the transition: {[s.value for s in PlanTaskStatus]}",
    )
