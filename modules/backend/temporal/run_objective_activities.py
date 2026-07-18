"""
Run-objective activity.

Single activity that runs the full run_objective flow
(refine → approve → dispatch) inside a Temporal activity.
The refine step blocks here (not at the HTTP layer), and
dispatch chains to MissionRunWorkflow internally.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.run_objective_models import RunObjectiveInput, RunObjectiveResult

logger = get_logger(__name__)


@activity.defn
async def execute_run_objective(input: RunObjectiveInput) -> RunObjectiveResult:
    """Run MissionPlanService.run_objective() as a Temporal activity.

    Creates its own DB session and Redis event bus. The service's
    run_objective() calls the Planning Agent (refine), approves tasks,
    and starts a MissionRunWorkflow for dispatch.

    The refine step (Planning Agent) blocks within this activity — safe
    because Temporal manages activity timeouts, not HTTP.
    """
    activity.logger.info(
        "Executing run_objective",
        extra={
            "mission_id": input.mission_id,
            "objective_preview": input.objective[:100],
        },
    )

    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        event_bus = SessionEventBus(redis, mission_id=input.mission_id)

        async with get_async_session() as db:
            service = MissionPlanOrchestrator(db, event_bus=event_bus)
            result = await service.run_objective(
                mission_id=input.mission_id,
                objective=input.objective,
                user_id=input.user_id,
                session_id=input.session_id,
                gate_mode=input.gate_mode,
                budget_ceiling_usd=input.budget_ceiling_usd,
            )
            await db.commit()

        return RunObjectiveResult(
            plan_id=result.get("plan_id", ""),
            plan_version=result.get("plan_version", 0),
            task_count=result.get("task_count", 0),
            outcome_status=result.get("outcome_status", ""),
            dispatched_task_ids=result.get("dispatched_task_ids"),
            total_cost_usd=result.get("total_cost_usd", 0.0),
            workflow_id=result.get("workflow_id"),
        )
    except Exception as exc:
        activity.logger.error(
            "run_objective failed",
            extra={"mission_id": input.mission_id},
            exc_info=True,
        )
        # Emit error event so the console shows the failure
        from modules.backend.temporal.activity_helpers import emit_activity_error

        await emit_activity_error(
            input.mission_id,
            "mission_plan_service",
            f"Run objective failed: {exc}",
        )
        raise
    finally:
        await redis.aclose()
