"""
Execution Record API schemas.

Request/response models for querying execution history,
task results, decisions, and cost breakdowns.
"""

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: str


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
    started_at: str | None
    completed_at: str | None
    created_at: str


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
    created_at: str


class ExecutionRecordResponse(BaseModel):
    """API response for an execution record (list view)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    roster_name: str | None
    status: str
    total_cost_usd: float
    started_at: str | None
    completed_at: str | None
    parent_execution_record_id: str | None
    created_at: str
    updated_at: str


class ExecutionRecordDetailResponse(ExecutionRecordResponse):
    """Detailed execution record with full execution data."""

    objective_statement: str | None = None
    objective_category: str | None = None
    task_plan_json: dict | None = None
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
