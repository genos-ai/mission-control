"""
Plan refine activities.

Single activity that runs the Planning Agent via MissionPlanService.refine().
Opens its own DB session and event bus — safe for Temporal retry.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.plan_refine_models import PlanRefineInput, PlanRefineResult

logger = get_logger(__name__)


@activity.defn
async def execute_plan_refine(input: PlanRefineInput) -> PlanRefineResult:
    """Run MissionPlanService.refine() as a Temporal activity.

    Creates its own DB session and Redis event bus so the activity is
    self-contained and retryable. On success, refine() emits
    MissionPlanRefinedEvent via the event bus — the frontend picks it
    up through SSE and invalidates its plan cache.

    On failure, emits a SystemEvent error so the console shows the
    problem to the user.
    """
    activity.logger.info(
        "Executing plan refine",
        extra={"mission_id": input.mission_id, "plan_id": input.plan_id},
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
            refined = await service.refine(
                input.plan_id,
                input.instructions,
                user_id=input.user_id,
                mission_budget_usd=input.mission_budget_usd,
            )

            # Auto-approve proposed tasks when gate mode permits.
            # Without this, refine creates PROPOSED tasks but nothing
            # transitions them to APPROVED — the daemon only auto-approves
            # AFTER a dispatch completes (supervisor ADVANCE_APPROVED path).
            # Use mission owner for approval — input.user_id is "who
            # requested refinement" which may differ from the mission owner
            # (e.g. admin acting on behalf of a user).
            from modules.backend.services.mission import MissionService
            from modules.backend.services.mission_plan import MissionPlanService

            gate = refined.gate_mode or "autonomous"
            approved_count = 0
            if gate != "interactive":
                mission = await MissionService(db).get_mission(input.mission_id)
                plan_svc = MissionPlanService(db, event_bus=event_bus)
                approved_ids = await plan_svc.approve_all_proposed(
                    input.plan_id,
                    mission.owner_id,
                )
                approved_count = len(approved_ids)

            await db.commit()

            return PlanRefineResult(
                plan_id=input.plan_id,
                version=refined.version,
                task_count=len(refined.tasks),
                approved_count=approved_count,
            )
    except Exception as exc:
        # Catch-all justified: wraps plan refinement (LLM calls, DB
        # writes) whose exception surface is unbounded — logged and
        # emitted here for Console visibility, then re-raised so
        # Temporal's retry/failure semantics still apply.
        activity.logger.error(
            "Plan refine failed",
            extra={"mission_id": input.mission_id, "plan_id": input.plan_id},
            exc_info=True,
        )
        # Emit error event so the console shows the failure
        from modules.backend.temporal.activity_helpers import emit_activity_error

        await emit_activity_error(
            input.mission_id,
            "mission_plan_service",
            f"Plan refinement failed: {exc}",
        )
        raise
    finally:
        await redis.aclose()
