"""ExecutionOutcome — structured result from mission dispatch.

Shared Pydantic models returned to the Execution layer (or caller) with
per-task results, cost breakdown, and references to planning artifacts.

These types are consumed by services, agents, and temporal activities.
Extracted from agents/mission_control/outcome.py (Plan 65 import cycle fix).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExecutionStatus(StrEnum):
    """Execution completion status."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class TaskStatus(StrEnum):
    """Individual task completion status."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class TaskTokenUsage(BaseModel):
    """Token usage for a single task execution."""

    model_config = ConfigDict(extra="forbid")

    input: int = 0
    output: int = 0
    thinking: int = 0


class Tier1Outcome(BaseModel):
    """Tier 1 structural verification outcome."""

    model_config = ConfigDict(extra="forbid")

    status: str = "skipped"  # "pass" | "fail" | "skipped"
    details: str = ""


class FailedCheck(BaseModel):
    """A single failed Tier 2 check."""

    model_config = ConfigDict(extra="forbid")

    check: str
    reason: str


class Tier2Outcome(BaseModel):
    """Tier 2 deterministic verification outcome."""

    model_config = ConfigDict(extra="forbid")

    status: str = "skipped"  # "pass" | "fail" | "skipped"
    checks_run: int = 0
    checks_passed: int = 0
    failed_checks: list[FailedCheck] = Field(default_factory=list)


class Tier3Outcome(BaseModel):
    """Tier 3 AI evaluation verification outcome."""

    model_config = ConfigDict(extra="forbid")

    status: str = "skipped"  # "pass" | "fail" | "skipped"
    overall_score: float = 0.0
    criteria_results_reference: str = ""
    evaluator_thinking_trace_reference: str = ""
    cost_usd: float = 0.0


class VerificationOutcome(BaseModel):
    """Complete verification outcome per task in ExecutionOutcome."""

    model_config = ConfigDict(extra="forbid")

    tier_1: Tier1Outcome = Field(default_factory=Tier1Outcome)
    tier_2: Tier2Outcome = Field(default_factory=Tier2Outcome)
    tier_3: Tier3Outcome = Field(default_factory=Tier3Outcome)


class RetryHistoryEntry(BaseModel):
    """Record of a single retry attempt."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    failure_tier: int  # 0=execution, 1=tier1, 2=tier2, 3=tier3
    failure_reason: str
    feedback_provided: str


class TaskResult(BaseModel):
    """Result of a single task execution."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_name: str
    status: TaskStatus
    output_reference: dict = Field(default_factory=dict)
    token_usage: TaskTokenUsage = Field(default_factory=TaskTokenUsage)
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    verification_outcome: VerificationOutcome = Field(
        default_factory=VerificationOutcome,
    )
    retry_count: int = 0
    retry_history: list[RetryHistoryEntry] = Field(default_factory=list)
    execution_id: str = Field(
        default="",
        description="Globally unique execution ID assigned at dispatch time",
    )
    context_updates: list[dict] = Field(
        default_factory=list,
        description="Structured patches to the PCD proposed by this agent",
    )
    skip_reason: str | None = None


class GateDecisionRecord(BaseModel):
    """Record of a single gate review decision for audit trail."""

    model_config = ConfigDict(extra="forbid")

    gate_type: str
    layer_index: int = 0
    task_id: str | None = None
    action: str
    reason: str | None = None
    reviewer: str = "human"


class ExecutionOutcome(BaseModel):
    """Complete result of a Mission Control dispatch.

    Returned to the Execution layer with per-task results and cost breakdown.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    status: ExecutionStatus
    summary: str = Field(
        default="",
        description="Human-readable narrative summary generated post-dispatch",
    )
    task_results: list[TaskResult] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    total_duration_seconds: float = 0.0
    total_tokens: TaskTokenUsage = Field(default_factory=TaskTokenUsage)
    abort_reason: str | None = None
    planning_trace_reference: str | None = None
    task_plan_reference: str | None = None
    gate_decisions: list[GateDecisionRecord] = Field(default_factory=list)
    execution_record_id: str | None = Field(
        default=None,
        description=(
            "ID of the ExecutionRecord row persisted by the bridge. Set by "
            "handle_mission after persist_mission_results returns. None on "
            "failure or when persistence is disabled. Used by callers that "
            "need to link back to the run record."
        ),
    )
