"""
Data models for tool-forked Temporal workflows (Plan 56 Phase B).

Serializable dataclasses for DesignWorkflowWorkflow and RunWorkflowWorkflow.
Same convention as chat_models.py — no ORM objects, JSON-safe, Temporal-friendly.
"""

from dataclasses import dataclass, field


@dataclass
class DesignWorkflowInput:
    """Input for DesignWorkflowWorkflow."""

    mission_id: str
    session_id: str
    execution_record_id: str
    workflow_name: str
    description: str
    instructions: str


@dataclass
class RunWorkflowInput:
    """Input for RunWorkflowWorkflow (workflow execution fork)."""

    mission_id: str
    session_id: str
    execution_record_id: str
    workflow_name: str
    context_overrides: dict | None = None  # Plan 40: override template context vars


@dataclass
class ToolForkResult:
    """Generic result from a tool-forked workflow."""

    execution_record_id: str
    status: str = "completed"  # completed, failed
    summary: str = ""
    error: str | None = None
    cost_usd: float = 0.0
