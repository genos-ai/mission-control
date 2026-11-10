"""
Chat turn workflow data models (Plan 52 Phase B).

Serializable dataclasses for the ChatTurnWorkflow. Same convention
as temporal/models.py — no ORM objects, JSON-safe, Temporal-friendly.
"""

from dataclasses import dataclass, field

from modules.backend.temporal.mission_run_models import WorkflowTimeoutsSnapshot


@dataclass
class ChatTurnInput:
    """Input to start a ChatTurnWorkflow."""

    session_id: str
    mission_id: str
    message: str
    sender_id: str | None = None
    agent_id: str | None = None
    channel: str = "api"
    parent_workflow_id: str | None = None
    timeouts: WorkflowTimeoutsSnapshot = field(kw_only=True)


@dataclass
class ChatTurnResult:
    """Output from ChatTurnWorkflow."""

    session_id: str
    content: str = ""
    agent_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    error: str | None = None
    thinking: str | None = None
