"""
Mission Plan API schemas (Plan 42, updated by Plan 72).

Pydantic models for the long-lived mission backlog endpoints. Plan 72
replaced PlanTaskState + task_plan_json with first-class Task rows.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.backend.models.mission_plan import GateMode, MissionPlanStatus
from modules.backend.models.task import TaskStatus

# ── Plan-level ───────────────────────────────────────────────────────────


class AddPlanTaskRequest(BaseModel):
    """POST /missions/:id/plan/tasks body — add a single proposed task."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1, max_length=2000)
    agent: str = Field(..., min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=4000)
    dependencies: list[str] = Field(default_factory=list)


class MissionPlanRefineRequest(BaseModel):
    """POST /missions/:id/plan/refine body."""

    model_config = ConfigDict(extra="forbid")

    instructions: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description=("Natural-language refinement instructions for the Planning Agent."),
    )


class MissionPlanUpdate(BaseModel):
    """Schema for PATCH /missions/:id/plan.

    All fields optional — the service applies only the ones present.
    """

    model_config = ConfigDict(extra="forbid")

    gate_mode: GateMode | None = Field(
        None,
        description=f"Autonomy mode. One of: {[m.value for m in GateMode]}.",
    )
    status: str | None = Field(
        None,
        description=f"Plan lifecycle: {[s.value for s in MissionPlanStatus]}",
    )
    budget_usd_ceiling: float | None = Field(
        None,
        ge=0.0,
        description="Cumulative cap across all runs from this plan",
    )


class TaskResponse(BaseModel):
    """Per-task row as seen by the Plan tab (Plan 72).

    Replaces PlanTaskStateResponse. Each task is a first-class DB row
    with definition + state + result in one object.

    The `dependencies` field is auto-flattened from TaskDependency ORM
    objects to a plain list of UUID strings via the model_validator.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    mission_id: str
    agent: str
    description: str
    instructions: str = ""
    inputs_json: dict = Field(default_factory=dict)
    verification_json: dict = Field(default_factory=dict)
    constraints_json: dict = Field(default_factory=dict)
    domain_tags: list = Field(default_factory=list)
    status: str
    approved_by_user_id: str | None = None
    approved_at: datetime | None = None
    retry_count: int = 0
    last_attempt_at: datetime | None = None
    result_summary: str | None = None
    failure_reason: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of tasks this task depends on",
    )
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def flatten_dependencies(cls, data):
        """Convert TaskDependency ORM objects to flat UUID list."""
        if hasattr(data, "__table__"):
            # ORM model — extract deps from relationship
            deps = getattr(data, "dependencies", [])
            dep_ids = [d.depends_on_id for d in deps] if deps else []
            obj = {c.key: getattr(data, c.key) for c in data.__table__.columns}
            obj["dependencies"] = dep_ids
            return obj
        return data


class MissionPlanResponse(BaseModel):
    """Full plan with all tasks (Plan 72).

    Tasks are first-class rows — no more task_plan_json or task_states.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    summary: str = ""
    estimated_cost_usd: float = 0.0
    estimated_duration: int = 0
    execution_hints_json: dict = Field(default_factory=dict)
    gate_mode: GateMode
    status: str
    version: int
    budget_usd_ceiling: float | None = None
    total_spent_usd: float = 0.0
    supervisor_iteration_count: int = 0
    max_supervisor_iterations: int = 20
    tasks: list[TaskResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Task-level transitions ───────────────────────────────────────────────


class RunObjectiveRequest(BaseModel):
    """POST /missions/:id/plan/run-objective body (Plan 62)."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(
        ...,
        min_length=5,
        description="Natural-language objective for the Planning Agent",
    )
    gate_mode: GateMode | None = Field(None)
    budget_ceiling_usd: float | None = Field(None, ge=0.01)


class RunObjectiveResponse(BaseModel):
    """Result of POST /missions/:id/plan/run-objective."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    outcome_status: str
    workflow_id: str | None = None


class TaskTransitionResponse(BaseModel):
    """Result of an approve / reject / retry call."""

    model_config = ConfigDict(extra="forbid")

    target_task_id: str
    transitioned_task_ids: list[str] = Field(default_factory=list)
    new_status: str = Field(
        ...,
        description=f"Target status: {[s.value for s in TaskStatus]}",
    )
