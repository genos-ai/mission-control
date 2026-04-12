"""
Chat turn workflow data models (Plan 52 Phase B).

Serializable dataclasses for the ChatTurnWorkflow. Same convention
as temporal/models.py — no ORM objects, JSON-safe, Temporal-friendly.
"""

from dataclasses import dataclass, field


@dataclass
class ChatTurnInput:
    """Input to start a ChatTurnWorkflow."""

    session_id: str
    mission_id: str
    message: str
    sender_id: str | None = None
    agent_id: str | None = None
    channel: str = "api"


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
