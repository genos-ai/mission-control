"""
Tool: run_objective

Execute an objective end-to-end: decompose into tasks, approve where the
gate mode permits, and dispatch.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import run_tool

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
    """Plan, approve and dispatch an objective in one call.

    Args:
        db_session: Active async session.
        mission_id: Mission to run the objective against.
        session_id: Transport session, used to schedule the followup (P15).
        objective: What to accomplish, in natural language.
        event_bus: Event bus passed through to the orchestrator.

    Returns:
        The orchestrator's result, including `outcome_status`.
    """
    from modules.backend.agents.mission.director.tools_workflow import (
        _schedule_director_followup,
    )
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

    acting_user_id = (await MissionService(db_session).get_mission(mission_id)).owner_id
    orchestrator = MissionPlanOrchestrator(db_session, event_bus=event_bus)
    result = await orchestrator.run_objective(
        mission_id=mission_id,
        objective=objective,
        user_id=acting_user_id,
        session_id=session_id,
    )
    await db_session.commit()

    # Wake the Director when the supervisor decides on the dispatched run.
    if result.get("outcome_status") == "dispatching":
        await _schedule_director_followup(
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
        """Execute an objective end-to-end: plan tasks, approve, and dispatch.

        Use this when the user wants something DONE — research, scans,
        code tasks, analysis. The Planning Agent decomposes the objective
        into a task DAG based on the team's capabilities, auto-approves
        (if gate mode permits), and dispatches via Temporal. Returns
        immediately — you are notified when execution completes.

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
