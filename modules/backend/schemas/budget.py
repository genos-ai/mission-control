"""Mission budget schemas (Plan 88 step 88.4.1, contracts 3.5.1 and 3.5.3).

``breach`` is a ``MissionPauseReason``; on the wire it is the lowercase value
or ``null`` (3.0.2).
"""

from pydantic import BaseModel, ConfigDict, Field

from modules.backend.models.mission import MissionPauseReason


class BudgetCapsUpdate(BaseModel):
    """PUT /missions/{id}/budget body. ``lifetime_usd`` null removes the lifetime cap."""

    model_config = ConfigDict(extra="forbid")

    per_run_usd: float = Field(..., gt=0)
    per_month_usd: float = Field(..., gt=0)
    lifetime_usd: float | None = Field(...)


class BudgetStatus(BaseModel):
    """A mission's caps, its spend and the first breached cap."""

    model_config = ConfigDict(frozen=True)

    per_run_usd: float
    per_month_usd: float
    lifetime_usd: float | None
    month_spent_usd: float
    lifetime_spent_usd: float
    active_run_spent_usd: float
    breach: MissionPauseReason | None


class BudgetStatusResponse(BudgetStatus):
    """GET and PUT /missions/{id}/budget response data."""


class BudgetCheckResult(BaseModel):
    """One run's spend against its run cap and the mission caps."""

    model_config = ConfigDict(frozen=True)

    run_spent_usd: float
    month_spent_usd: float
    lifetime_spent_usd: float
    headroom_usd: float
    breach: MissionPauseReason | None
