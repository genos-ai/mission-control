"""
Tool: refine_plan

Start a PlanRefineWorkflow so the Planning Agent rebuilds the mission
plan from the user's instructions.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import run_tool
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def refine_plan(
    db_session: AsyncSession,
    mission_id: str,
    instructions: str,
) -> dict:
    """Start plan refinement via Temporal and return immediately.

    The Temporal activity owns its own DB session, event bus, commit and
    error reporting, so no ORM attribute is read after the workflow
    starts.

    Args:
        db_session: Active async session.
        mission_id: Mission whose plan to refine.
        instructions: The user's refinement request, in their own words.

    Returns:
        The started workflow's identifiers and a message for the user.
    """
    from modules.backend.core.config import get_app_config, get_default_budget_usd
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_plan import MissionPlanService
    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.plan_refine_models import PlanRefineInput
    from modules.backend.temporal.plan_refine_workflow import PlanRefineWorkflow

    mission = await MissionService(db_session).get_mission(mission_id)
    plan_svc = MissionPlanService(db_session)
    plan = await plan_svc.get_or_create_plan(mission_id)
    await db_session.commit()

    # Save what the workflow needs before the commit above expires the
    # ORM attributes (P-pattern: commit expires everything).
    client = await get_temporal_client()
    config = get_app_config().temporal
    workflow_id = f"plan-refine-{plan.id[:12]}-{uuid.uuid4().hex[:8]}"

    await client.start_workflow(
        PlanRefineWorkflow.run,
        PlanRefineInput(
            mission_id=mission_id,
            plan_id=plan.id,
            instructions=instructions,
            user_id=mission.owner_id,
            mission_budget_usd=plan.budget_usd_ceiling or get_default_budget_usd(),
        ),
        id=workflow_id,
        task_queue=config.task_queue,
    )

    logger.info(
        "Director started PlanRefineWorkflow",
        extra={
            "mission_id": mission_id,
            "plan_id": plan.id,
            "workflow_id": workflow_id,
        },
    )

    return {
        "status": "refining",
        "plan_id": plan.id,
        "workflow_id": workflow_id,
        "message": (
            "Plan refinement started. The Planning Agent is building "
            "tasks now — progress is visible in the Console and Plan "
            "tab. Tell the user to watch the Plan tab for new tasks."
        ),
    }


# ── Registry integration ─────────────────────────────────

_impl = refine_plan


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def refine_plan(
        ctx: RunContext[MissionDirectorDeps],
        instructions: str,
    ) -> str:
        """Refine the mission plan via the Planning Agent.

        Delegates to the Planning Agent — you do NOT author TaskPlans
        yourself. The Planning Agent receives the current plan + your
        instructions and produces a new TaskPlan that incorporates the
        user's requested changes while preserving task_id strings for
        unchanged tasks (so existing approvals and run history survive).

        Use this when the user describes what they want to work on,
        asks for a new plan, or asks to modify the existing plan. Pass
        the user's instructions in their own words — the Planning Agent
        works best with concrete, specific language.

        This starts a PlanRefineWorkflow via Temporal and returns
        immediately. The workflow emits mission_plan.refined via SSE
        on completion — the frontend and console pick it up
        automatically. Tell the user their plan is being generated
        and they can watch progress in the Plan tab.

        Args:
            instructions: Natural-language refinement request from the
                user. Example: "Split the test phase into unit and
                integration. Add a final task that posts the results
                to Slack."
        """
        return await run_tool(
            ctx,
            "refine_plan",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id, instructions),
        )
