"""
Execution Record API schemas.

Request/response models for querying execution history,
task results, decisions, and cost breakdowns.
"""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.backend.core.decision_reasoning import decode_decision_reasoning
from modules.backend.models.execution_record import DecisionType

# Decision types whose reasoning carries a decision_reasoning metadata tail.
_DECISIONS_WITH_METADATA = frozenset(
    {DecisionType.POST_RUN_SUPERVISOR.value, DecisionType.OBJECTIVE_MET.value}
)


class TaskAttemptResponse(BaseModel):
    """API response for a single task attempt."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt_number: int
    status: str
    failure_tier: str | None
    failure_reason: str | None
    feedback_provided: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    created_at: datetime


class TaskExecutionResponse(BaseModel):
    """API response for a single task execution."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    agent_name: str
    status: str
    output_data: dict | None
    token_usage: dict | None
    cost_usd: float
    duration_seconds: float | None
    verification_outcome: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class TaskExecutionDetailResponse(TaskExecutionResponse):
    """Task execution with attempt history."""

    attempts: list[TaskAttemptResponse] = Field(default_factory=list)


class ExecutionDecisionResponse(BaseModel):
    """API response for a Mission Control decision."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    decision_type: str
    task_id: str | None
    reasoning: str
    created_at: datetime

    @model_validator(mode="after")
    def _drop_stored_metadata(self) -> Self:
        # Post-run supervisor and Director objective-met rows store their
        # metadata after the reason in the same column; clients display
        # `reasoning`, so they get the reason only.
        if self.decision_type in _DECISIONS_WITH_METADATA:
            self.reasoning = decode_decision_reasoning(self.reasoning).human
        return self


class ExecutionRecordResponse(BaseModel):
    """API response for an execution record (list view)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str | None = None
    roster_name: str | None
    status: str
    total_cost_usd: float
    started_at: datetime | None
    completed_at: datetime | None
    # Plan 46 Phase 2 #3: task_count lets the Runs tab render a
    # run's task count on the always-visible row without a per-row
    # detail fetch. Populated in the endpoint layer from the
    # eager-loaded task_executions relationship.
    task_count: int = 0
    # Plan 56 Phase B: background task tracking
    task_type: str | None = None
    task_params: dict | None = None
    temporal_workflow_id: str | None = None
    mission_id: str | None = None
    objective_statement: str | None = None
    created_at: datetime
    updated_at: datetime


class ExecutionRecordDetailResponse(ExecutionRecordResponse):
    """Detailed execution record with full execution data."""

    objective_statement: str | None = None
    objective_category: str | None = None
    execution_outcome_json: dict | None = None
    planning_thinking_trace: str | None = None
    task_executions: list[TaskExecutionResponse] = Field(default_factory=list)
    decisions: list[ExecutionDecisionResponse] = Field(default_factory=list)


class ExecutionCostBreakdown(BaseModel):
    """Cost breakdown for an execution."""

    execution_id: str
    total_cost_usd: float
    task_costs: list[dict] = Field(
        default_factory=list,
        description="Per-task cost: [{task_id, agent_name, cost_usd, tokens}]",
    )
    model_costs: dict[str, float] = Field(
        default_factory=dict,
        description="Cost aggregated by model name",
    )
    attempt_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class ExecutionListResponse(BaseModel):
    """Paginated execution list."""

    executions: list[ExecutionRecordResponse]
    total: int
    page_size: int
    offset: int
