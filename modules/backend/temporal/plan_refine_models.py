"""
Plan refine workflow data models.

Serializable dataclasses for PlanRefineWorkflow. Same convention
as chat_models.py — no ORM objects, JSON-safe, Temporal-friendly.
"""

from dataclasses import dataclass, field

from modules.backend.temporal.mission_run_models import WorkflowTimeoutsSnapshot


@dataclass
class PlanRefineInput:
    """Input to start a PlanRefineWorkflow."""

    mission_id: str
    plan_id: str
    instructions: str
    user_id: str
    mission_budget_usd: float
    timeouts: WorkflowTimeoutsSnapshot = field(kw_only=True)


@dataclass
class PlanRefineResult:
    """Output from PlanRefineWorkflow."""

    plan_id: str
    version: int = 0
    task_count: int = 0
    approved_count: int = 0
    error: str | None = None
