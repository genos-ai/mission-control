"""
Plan refine workflow data models.

Serializable dataclasses for PlanRefineWorkflow. Same convention
as chat_models.py — no ORM objects, JSON-safe, Temporal-friendly.
"""

from dataclasses import dataclass


@dataclass
class PlanRefineInput:
    """Input to start a PlanRefineWorkflow."""

    mission_id: str
    plan_id: str
    instructions: str
    user_id: str
    mission_budget_usd: float = 10.0


@dataclass
class PlanRefineResult:
    """Output from PlanRefineWorkflow."""

    plan_id: str
    version: int = 0
    task_count: int = 0
    error: str | None = None
