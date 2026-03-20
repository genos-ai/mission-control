"""
Execution API schemas.

Request/response models for execution CRUD, status reporting,
and workflow-to-execution conversion.
"""

from pydantic import BaseModel, ConfigDict, Field


class ExecutionCreate(BaseModel):
    """Create an ad-hoc execution (not from a workflow)."""

    objective: str = Field(..., description="Execution objective")
    roster_ref: str = Field(default="default")
    complexity_tier: str = Field(default="simple")
    triggered_by: str = Field(default="user:anonymous")
    cost_ceiling_usd: float | None = None
    upstream_context: dict | None = None


class ExecutionResponse(BaseModel):
    """API response for an execution."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str | None
    workflow_step_id: str | None
    objective: str
    roster_ref: str
    complexity_tier: str
    status: str
    session_id: str
    trigger_type: str
    triggered_by: str
    total_cost_usd: float
    cost_ceiling_usd: float | None
    started_at: str | None
    completed_at: str | None


class ExecutionDetailResponse(BaseModel):
    """Detailed execution response with context and results."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str | None
    workflow_step_id: str | None
    objective: str
    roster_ref: str
    complexity_tier: str
    status: str
    session_id: str
    trigger_type: str
    triggered_by: str
    upstream_context: dict
    context: dict
    total_cost_usd: float
    cost_ceiling_usd: float | None
    started_at: str | None
    completed_at: str | None
    result_summary: str | None
    error_data: dict | None


class ExecutionStateSummary(BaseModel):
    """Execution progress summary."""

    execution_id: str
    objective: str
    status: str
    roster_ref: str
    total_cost_usd: float
    cost_ceiling_usd: float | None
    started_at: str | None
    elapsed_seconds: float | None
