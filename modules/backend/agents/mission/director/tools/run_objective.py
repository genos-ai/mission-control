"""
Tool: run_objective

Start a mission run for an objective. The run plans, approves where the gate
mode permits, and dispatches asynchronously.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import (
    run_tool,
    schedule_director_followup,
)

# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def run_objective(
    db_session: AsyncSession,
    mission_id: str,
    session_id: str | None,
    objective: str,
    event_bus: Any = None,
) -> dict:
    """Start a DIRECTOR-triggered mission run for an objective.

    Planning happens asynchronously in the run; this returns once the run's
    workflow has started.

    Args:
        db_session: Active async session.
        mission_id: Mission to run the objective against.
        session_id: Transport session, used to schedule the followup (P15).
        objective: What to accomplish, in natural language.
        event_bus: Event bus for the run's events.

    Returns:
        The run's `mission_run_id`, `sequence` and `status`.
    """
    from modules.backend.schemas.mission_run import MissionRunTrigger
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_run import MissionRunService

    acting_user_id = (await MissionService(db_session).get_mission(mission_id)).owner_id
    run = await MissionRunService(db_session, event_bus).start_run(
        mission_id,
        trigger=MissionRunTrigger.DIRECTOR,
        objective=objective,
        user_id=acting_user_id,
        session_id=session_id,
    )
    result = {
        "mission_run_id": run.id,
        "sequence": run.sequence,
        "status": run.status.value,
    }

    # Wake the Director when the supervisor decides on the run.
    await schedule_director_followup(
        db_session,
        session_id=session_id,
        mission_id=mission_id,
        trigger_event_types=["mission_plan.supervisor_decision"],
        prompt_template=(
            "The supervisor just evaluated the latest run. "
            "Check the plan status and report back to the user."
        ),
    )

    return result


# ── Registry integration ─────────────────────────────────

_impl = run_objective


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def run_objective(
        ctx: RunContext[MissionDirectorDeps],
        objective: str,
    ) -> str:
        """Start a mission run for an objective: plan tasks, approve, and dispatch.

        Use this when the user wants something DONE — research, scans,
        code tasks, analysis. Planning happens asynchronously in the run:
        the Planning Agent decomposes the objective into a task DAG based
        on the team's capabilities, tasks are auto-approved if the gate
        mode permits, and the run dispatches them. Returns the run's id,
        sequence and status immediately — you are notified when the
        supervisor evaluates the run.

        Do NOT use this for planning-only requests (use refine_plan instead).

        Args:
            objective: What to accomplish (natural language). Be specific —
                include scope, constraints, and any user-specified details.
        """
        return await run_tool(
            ctx,
            "run_objective",
            partial(
                _impl,
                ctx.deps.db_session,
                ctx.deps.mission_id,
                ctx.deps.session_id,
                objective,
                ctx.deps.event_bus,
            ),
            indent=None,
            rollback_on_error=True,
        )
