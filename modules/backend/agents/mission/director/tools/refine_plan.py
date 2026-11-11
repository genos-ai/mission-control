"""
Tool: refine_plan

Run a PlanRefineWorkflow so the Planning Agent rebuilds the mission
plan from the user's instructions. While a mission run is active the
tool waits for the refinement to commit or fail (Plan 88 Phase 2 failure
drill B: the run reads its task graph when the Director's turn ends).
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import TYPE_CHECKING, Any

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
    event_bus: Any,
) -> dict:
    """Refine the plan through a PlanRefineWorkflow.

    With no active run the workflow is started and the call returns at
    once. While a run is active the refinement belongs to that run (its
    new tasks join it), so the call waits for the workflow to commit or
    fail: the turn, whose end the run waits on, then cannot end before the
    run's tasks exist. A failed refinement raises with its cause.

    The Temporal activity owns its own DB session, event bus, commit and
    error reporting, so no ORM attribute is read after the workflow
    starts.

    Args:
        db_session: Active async session.
        mission_id: Mission whose plan to refine.
        instructions: The user's refinement request, in their own words.
        event_bus: The Director's event bus, for the run lookup.

    Returns:
        The workflow's identifiers and a message for the user; when a run
        is active, also the refined plan version and task counts.

    Raises:
        ExternalServiceError: The refinement for the active run failed.
    """
    from temporalio.client import WorkflowFailureError

    from modules.backend.core.config import get_app_config
    from modules.backend.core.exceptions import ExternalServiceError
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_plan import MissionPlanService
    from modules.backend.services.mission_run import MissionRunService
    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.config_snapshots import build_workflow_timeouts_snapshot
    from modules.backend.temporal.plan_refine_models import PlanRefineInput
    from modules.backend.temporal.plan_refine_workflow import PlanRefineWorkflow

    mission = await MissionService(db_session).get_mission(mission_id)
    plan_svc = MissionPlanService(db_session)
    plan = await plan_svc.get_or_create_plan(mission_id)
    remaining_budget_usd = await plan_svc.remaining_budget_usd(plan)
    active_run = await MissionRunService(db_session, event_bus).get_active_run(mission_id)
    # Save what the workflow needs before the commit expires the ORM
    # attributes (P-pattern: commit expires everything).
    plan_id = plan.id
    owner_id = mission.owner_id
    run_id = active_run.id if active_run is not None else None
    await db_session.commit()

    client = await get_temporal_client()
    config = get_app_config().temporal
    workflow_id = f"plan-refine-{plan_id[:12]}-{uuid.uuid4().hex[:8]}"
    refine_input = PlanRefineInput(
        mission_id=mission_id,
        plan_id=plan_id,
        instructions=instructions,
        user_id=owner_id,
        mission_budget_usd=remaining_budget_usd,
        timeouts=build_workflow_timeouts_snapshot(),
    )
    log_extra = {
        "mission_id": mission_id,
        "plan_id": plan_id,
        "workflow_id": workflow_id,
        "mission_run_id": run_id,
    }

    if run_id is None:
        await client.start_workflow(
            PlanRefineWorkflow.run, refine_input, id=workflow_id, task_queue=config.task_queue
        )
        logger.info("Director started PlanRefineWorkflow", extra=log_extra)
        return {
            "status": "refining",
            "plan_id": plan_id,
            "workflow_id": workflow_id,
            "message": (
                "Plan refinement started. The Planning Agent is building "
                "tasks now — progress is visible in the Console and Plan "
                "tab. Tell the user to watch the Plan tab for new tasks."
            ),
        }

    logger.info("Director refining the plan for the active run", extra=log_extra)
    try:
        result = await client.execute_workflow(
            PlanRefineWorkflow.run, refine_input, id=workflow_id, task_queue=config.task_queue
        )
    except WorkflowFailureError as exc:
        raise ExternalServiceError(f"Plan refinement failed: {_root_cause(exc)}") from exc
    return {
        "status": "refined",
        "plan_id": plan_id,
        "workflow_id": workflow_id,
        "mission_run_id": run_id,
        "version": result.version,
        "task_count": result.task_count,
        "approved_count": result.approved_count,
        "message": (
            "Plan refined for the active run. Its new tasks are committed; "
            "approve the proposed ones if the gate mode needs it."
        ),
    }


def _root_cause(exc: BaseException) -> str:
    """The innermost Temporal failure message (workflow -> activity -> application error)."""
    while getattr(exc, "cause", None) is not None:
        exc = exc.cause
    return str(exc)


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

        This runs a PlanRefineWorkflow via Temporal. With no active run
        it returns immediately; the workflow emits mission_plan.refined
        via SSE on completion, and the frontend and console pick it up
        automatically. Tell the user their plan is being generated and
        they can watch progress in the Plan tab. While a mission run is
        active the call returns only once the refinement has committed
        (status "refined", with task counts) or failed (an error with the
        cause), so you can approve the new tasks in the same turn.

        Args:
            instructions: Natural-language refinement request from the
                user. Example: "Split the test phase into unit and
                integration. Add a final task that posts the results
                to Slack."
        """
        return await run_tool(
            ctx,
            "refine_plan",
            partial(
                _impl,
                ctx.deps.db_session,
                ctx.deps.mission_id,
                instructions,
                ctx.deps.event_bus,
            ),
        )
