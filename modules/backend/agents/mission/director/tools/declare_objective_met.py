"""
Tool: declare_objective_met

End a mission run's refine turn by declaring the objective met (Plan 88
Phase 2, owner decision 2026-11-11). The post-run reviewer can ask for a
refine the Director judges unnecessary; without this tool the Director could
only say so in text, and the run failed "refine produced no tasks" (failure
drill p88-faildrill-b3). The declaration travels structurally: RunRefineTurn
-> ChatTurnResult -> the run's refinement_complete signal.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import ToolRefusal, run_tool
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

DIRECTOR_AGENT_NAME = "mission.director.agent"

# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.agents.deps.base import RunRefineTurn


async def declare_objective_met(
    db_session: AsyncSession,
    mission_id: str,
    run_refine: RunRefineTurn | None,
    reason: str,
    event_bus: Any,
) -> dict:
    """Declare the active run's objective met in its refine turn.

    Records the decision on the run's ExecutionRecord with the Director as
    decider and commits it, then marks the turn so the run ends SUCCEEDED
    (OBJECTIVE_MET) when the turn ends.

    Args:
        db_session: Active async session.
        mission_id: The Director's mission.
        run_refine: The run refine turn this call belongs to; None outside one.
        reason: Why the objective is met, in the Director's words.
        event_bus: The Director's event bus.

    Returns:
        The declared run and a message for the Director.

    Raises:
        ToolRefusal: Not a run's refine turn, no reason, or already declared.
        ConflictError: The turn's run is no longer the mission's active run.
    """
    from modules.backend.services.mission_run import MissionRunService

    if run_refine is None:
        raise ToolRefusal(
            "declare_objective_met only works in a mission run's refine turn "
            "(the turn the supervisor starts with an advance_refine request). "
            "Outside one there is no run waiting on the declaration."
        )
    reason = reason.strip()
    if not reason:
        raise ToolRefusal("A reason is required: say why the mission objective is met.")
    if run_refine.objective_met_reason is not None:
        raise ToolRefusal(
            "The objective is already declared met for this run.",
            {"mission_run_id": run_refine.mission_run_id},
        )

    run_id = run_refine.mission_run_id
    await MissionRunService(db_session, event_bus).record_director_objective_met(
        mission_id, run_id, reason, DIRECTOR_AGENT_NAME
    )
    await db_session.commit()
    run_refine.objective_met_reason = reason
    logger.info(
        "Director declared the run objective met",
        extra={"mission_id": mission_id, "mission_run_id": run_id},
    )
    return {
        "status": "declared",
        "mission_run_id": run_id,
        "message": (
            "Recorded. The run ends SUCCEEDED (objective met) when this turn "
            "ends. Do not call refine_plan in this turn: a refine that adds "
            "tasks contradicts the declaration and fails the run."
        ),
    }


# ── Registry integration ─────────────────────────────────

_impl = declare_objective_met


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def declare_objective_met(
        ctx: RunContext[MissionDirectorDeps],
        reason: str,
    ) -> str:
        """Declare the mission run's objective met instead of refining the plan.

        Use this only in a mission run's refine turn, when the supervisor
        asked you to call refine_plan for the next wave but you judge the
        mission objective is already met and no further tasks are needed.
        Call it instead of replying in text: a text reply alone fails the
        run. The run then ends SUCCEEDED with your reason. Do not call
        refine_plan in the same turn. Outside a run's refine turn the call
        is refused.

        Args:
            reason: Why the objective is met, citing the completed work.
                Example: "The brief asks for one completed poem task; task
                01a1cb50 completed with the poem in wave 2."
        """
        return await run_tool(
            ctx,
            "declare_objective_met",
            partial(
                _impl,
                ctx.deps.db_session,
                ctx.deps.mission_id,
                ctx.deps.run_refine,
                reason,
                ctx.deps.event_bus,
            ),
            rollback_on_error=True,
        )
