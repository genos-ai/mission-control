"""
Temporal DTOs for HumanInputWorkflow (Plan 45 Phase 4).

Serializable dataclasses — no ORM objects. Temporal serializes as JSON.
"""

from dataclasses import dataclass, field


@dataclass
class HumanInputWorkflowInput:
    """Input to start a HumanInputWorkflow."""

    request_id: str
    workflow_run_id: str
    step_id: str
    mission_id: str
    session_id: str
    prompt_message: str
    channel: str
    timeout_seconds: int
    default_response: str | None = None
    choices: list[str] = field(default_factory=list)


@dataclass
class HumanInputResponse:
    """Signal payload: human response to an input request."""

    response: str
    responder_id: str = ""
    responder_type: str = "human"


@dataclass
class HumanInputResult:
    """Output from HumanInputWorkflow."""

    request_id: str
    response: str
    responder_id: str = ""
    timed_out: bool = False
    status: str = "completed"
