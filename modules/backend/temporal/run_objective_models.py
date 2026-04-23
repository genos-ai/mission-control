"""
Run-objective workflow data models.

Serializable dataclasses for RunObjectiveWorkflow. Same convention
as chat_models.py — no ORM objects, JSON-safe, Temporal-friendly.
"""

from dataclasses import dataclass


@dataclass
class RunObjectiveInput:
    """Input to start a RunObjectiveWorkflow."""

    mission_id: str
    objective: str
    user_id: str
    session_id: str
    gate_mode: str | None = None
    budget_ceiling_usd: float | None = None


@dataclass
class RunObjectiveResult:
    """Output from RunObjectiveWorkflow."""

    plan_id: str
    plan_version: int = 0
    task_count: int = 0
    outcome_status: str = ""
    dispatched_task_ids: list[str] | None = None
    total_cost_usd: float = 0.0
    workflow_id: str | None = None
    error: str | None = None
