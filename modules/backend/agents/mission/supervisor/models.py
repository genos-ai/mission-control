"""
Supervisor Decision Model (Plan 51 Phase D).

Pydantic model for the structured output of the event-mode
supervisor agent (branch #8 of the decision matrix). The Haiku
agent returns this as JSON; the reviewer converts it into a
GateDecision.
"""

from pydantic import BaseModel, Field


class SupervisorDecision(BaseModel):
    """Structured output from the event-mode supervisor.

    The Haiku agent classifies the situation into one of three
    actions. If confidence < 0.6, the reviewer overrides to
    ESCALATE regardless of the stated decision.
    """

    decision: str = Field(
        ...,
        description=(
            "One of: ADVANCE_REFINE (objective not yet met, generate "
            "next wave), PROPOSE_COMPLETE (objective appears met, ask "
            "user to confirm), ESCALATE (unclear or unexpected)."
        ),
    )
    reason: str = Field(
        ...,
        description="Short human-readable justification (1-2 sentences).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "How confident the agent is in the decision (0.0-1.0). "
            "Below 0.6 triggers automatic override to ESCALATE."
        ),
    )
