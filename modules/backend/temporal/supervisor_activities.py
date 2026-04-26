"""
Supervisor loop activities (Plan 52 Phase C).

Activities for the MissionRunWorkflow's post-run supervisor loop:

1. evaluate_post_run — runs AutonomousPostRunReviewer with own DB session
2. approve_proposed_tasks — flips proposed → approved (idempotent)
3. fetch_plan_task_counts — returns counts by status for workflow decisions
4. start_director_turn — starts a ChatTurnWorkflow for the Director
   (used by ADVANCE_REFINE, PROPOSE_COMPLETE, ESCALATE paths)

Each activity opens its own DB session and commits independently.
"""

from dataclasses import dataclass, field

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.schemas.gate import GateContext

logger = get_logger(__name__)


async def _emit_supervisor_error(mission_id: str, message: str) -> None:
    """Emit a SystemEvent from a supervisor activity so errors surface in the console."""
    from modules.backend.temporal.activity_helpers import emit_activity_error

    await emit_activity_error(mission_id, "mission.supervisor", message)


@dataclass
class PostRunEvalInput:
    """Input for the evaluate_post_run activity."""

    mission_id: str
    plan_id: str
    execution_record_id: str
    gate_mode: str = "autonomous"
    supervisor_iteration_count: int = 0
    max_supervisor_iterations: int = 20
    budget_usd_ceiling: float = 0.0
    total_spent_usd: float = 0.0
    mission_brief: str = ""


@dataclass
class PostRunEvalResult:
    """Output from evaluate_post_run."""

    action: str  # wait, advance_approved, advance_refine, propose_complete, escalate
    reason: str = ""
    reviewer: str = "config:rule_engine"
    confidence: float | None = None
    cost_usd: float = 0.0


@dataclass
class PlanTaskCounts:
    """Task counts by status for workflow decisions."""

    approved: int = 0
    proposed: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    queued: int = 0


@activity.defn
async def evaluate_post_run(input: PostRunEvalInput) -> PostRunEvalResult:
    """Run the AutonomousPostRunReviewer and return the decision.

    Creates its own DB session for the idempotency check and audit
    row write. The reviewer is the same Plan 51 code — just wrapped
    as a Temporal Activity for durability.

    Errors include mission_id in the logger extra so the centralised
    MissionEventHandler bridges them to the SSE stream automatically.
    """
    activity.logger.info(
        "Evaluating post-run",
        extra={
            "plan_id": input.plan_id,
            "execution_record_id": input.execution_record_id,
            "gate_mode": input.gate_mode,
        },
    )

    try:
        return await _do_evaluate_post_run(input)
    except Exception as e:
        from modules.backend.temporal.activities import _format_activity_error
        clean_msg = _format_activity_error(e)
        activity.logger.error(
            "evaluate_post_run failed",
            extra={
                "plan_id": input.plan_id,
                "error": clean_msg,
                "error_type": type(e).__name__,
                "mission_id": input.mission_id,
            },
            exc_info=True,
        )
        await _emit_supervisor_error(
            input.mission_id, f"Post-run evaluation failed: {clean_msg}",
        )
        raise


async def _do_evaluate_post_run(input: PostRunEvalInput) -> PostRunEvalResult:
    """Inner logic for evaluate_post_run — separated for error wrapping."""
    from modules.backend.agents.mission_control.gate_post_run import (
        AutonomousPostRunReviewer,
    )
    from modules.backend.agents.adapters.supervisor_introspection import (
        get_recent_run_outcomes,
    )
    from modules.backend.core.database import get_async_session
    from modules.backend.models.mission_plan import PlanTaskStatus

    async with get_async_session() as db:
        recent = await get_recent_run_outcomes(
            db, mission_id=input.mission_id, limit=5,
        )

        # Build task summary from the DB
        from modules.backend.services.mission_plan import MissionPlanService
        svc = MissionPlanService(db)
        plan = await svc.get_or_create_plan(input.mission_id)
        task_states = await svc.get_task_states(plan.id)

        summary = {
            "approved": sum(1 for s in task_states if s.status == PlanTaskStatus.APPROVED.name),
            "proposed": sum(1 for s in task_states if s.status == PlanTaskStatus.PROPOSED.name),
            "running": sum(1 for s in task_states if s.status == PlanTaskStatus.RUNNING.name),
            "completed": sum(1 for s in task_states if s.status in (PlanTaskStatus.COMPLETED.name,)),
            "failed": sum(1 for s in task_states if s.status == PlanTaskStatus.FAILED.name),
            "total_completed": sum(r.get("completed_task_count", 0) for r in recent),
            "execution_record_id": input.execution_record_id,
            "max_supervisor_iterations": input.max_supervisor_iterations,
        }

        context = GateContext(
            gate_type="post_run",
            mission_id=input.mission_id,
            total_cost_usd=input.total_spent_usd,
            budget_usd=input.budget_usd_ceiling,
            recent_run_outcomes=recent,
            plan_task_summary=summary,
            mission_brief=input.mission_brief,
            supervisor_iteration_count=input.supervisor_iteration_count,
        )

        reviewer = AutonomousPostRunReviewer(
            session=db,
            gate_mode=input.gate_mode,
        )
        decision = await reviewer.review(context)

        # Increment supervisor iteration counter
        plan.supervisor_iteration_count += 1
        await db.flush()
        await db.commit()

    # Extract confidence from model_metadata if present
    confidence = None
    if decision.model_metadata and "confidence" in decision.model_metadata:
        confidence = decision.model_metadata["confidence"]

    return PostRunEvalResult(
        action=decision.action.value,
        reason=(decision.reason or "")[:500],
        reviewer=decision.reviewer,
        confidence=confidence,
        cost_usd=decision.model_metadata.get("cost_usd", 0.0) if decision.model_metadata else 0.0,
    )


@activity.defn
async def approve_proposed_tasks(mission_id: str) -> int:
    """Flip all proposed tasks to approved. Returns count approved.

    Idempotent — checks status before approving. If tasks are already
    approved (from a replay), returns 0 without error.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_plan import MissionPlanService
    from modules.backend.models.mission_plan import PlanTaskStatus

    activity.logger.info("Approving proposed tasks", extra={"mission_id": mission_id})

    async with get_async_session() as db:
        svc = MissionPlanService(db)
        plan = await svc.get_or_create_plan(mission_id)
        task_states = await svc.get_task_states(plan.id, status=PlanTaskStatus.PROPOSED)

        approved_count = 0
        for ts in task_states:
            try:
                await svc.approve_task(plan.id, ts.task_id, "mission.supervisor.agent")
                approved_count += 1
            except Exception as exc:
                activity.logger.warning(
                    "Failed to approve task: %s",
                    exc,
                    extra={"task_id": ts.task_id, "mission_id": mission_id},
                )
                await _emit_supervisor_error(
                    mission_id, f"Failed to approve task '{ts.task_id}': {exc}",
                )

        await db.commit()

    activity.logger.info(
        "Approved proposed tasks",
        extra={"mission_id": mission_id, "count": approved_count},
    )
    return approved_count


@activity.defn
async def fetch_plan_task_counts(mission_id: str) -> PlanTaskCounts:
    """Return task counts by status for workflow decisions."""
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_plan import MissionPlanService

    async with get_async_session() as db:
        svc = MissionPlanService(db)
        plan = await svc.get_or_create_plan(mission_id)
        task_states = await svc.get_task_states(plan.id)

    from modules.backend.models.mission_plan import PlanTaskStatus

    counts = PlanTaskCounts()
    for s in task_states:
        if s.status == PlanTaskStatus.APPROVED.name:
            counts.approved += 1
        elif s.status == PlanTaskStatus.PROPOSED.name:
            counts.proposed += 1
        elif s.status == PlanTaskStatus.RUNNING.name:
            counts.running += 1
        elif s.status == PlanTaskStatus.COMPLETED.name:
            counts.completed += 1
        elif s.status == PlanTaskStatus.FAILED.name:
            counts.failed += 1
        elif s.status == PlanTaskStatus.QUEUED.name:
            counts.queued += 1

    return counts


@activity.defn
async def check_plan_active(mission_id: str) -> bool:
    """Return True if the plan is still active. False if paused/completed.

    Called before applying supervisor decisions — if someone paused
    the plan while we were evaluating, we should not advance.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_plan import MissionPlanService

    async with get_async_session() as db:
        svc = MissionPlanService(db)
        plan = await svc.get_or_create_plan(mission_id)
        from modules.backend.models.mission_plan import MissionPlanStatus
        return plan.status == MissionPlanStatus.ACTIVE.name


@activity.defn
async def fire_supervisor_followups(
    mission_id: str,
    plan_id: str,
    execution_record_id: str,
    action: str,
    reason: str,
    reviewer: str,
    run_status: str,
    run_cost_usd: float,
    total_spent_usd: float,
) -> int:
    """Fire session followups after a supervisor decision.

    Emits MissionPlanRunCompletedEvent and SupervisorDecisionEmittedEvent,
    then fires matching session followups so the Director wakes up and
    reports to the user.

    Returns the number of followups fired.
    """
    import uuid as _uuid

    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.events.types import (
        MissionPlanRunCompletedEvent,
        SupervisorDecisionEmittedEvent,
    )
    from modules.backend.services.session_followup import SessionFollowupService

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        event_bus = SessionEventBus(redis, mission_id=mission_id)
        sid = _uuid.uuid4()

        # Emit run completed event
        run_event = MissionPlanRunCompletedEvent(
            session_id=sid, source="temporal_supervisor",
            mission_id=mission_id, plan_id=plan_id,
            execution_record_id=execution_record_id,
            run_status=run_status, run_cost_usd=run_cost_usd,
            total_spent_usd=total_spent_usd,
        )
        await event_bus.publish_to_mission(mission_id, run_event)

        # Emit supervisor decision event
        decision_event = SupervisorDecisionEmittedEvent(
            session_id=sid, source="temporal_supervisor",
            mission_id=mission_id, plan_id=plan_id,
            execution_record_id=execution_record_id,
            action=action, reason=reason[:500], reviewer=reviewer,
        )
        await event_bus.publish_to_mission(mission_id, decision_event)

        # Fire matching followups
        async with get_async_session() as db:
            followup_svc = SessionFollowupService(db, event_bus=event_bus)

            async def _noop_runner(s: str, m: str, p: str) -> None:
                # In Temporal path, Director is woken via start_director_turn
                # activity, not via the followup runner. The followup still
                # fires to consume the row and emit the audit event.
                pass

            fired = []
            for event in (run_event, decision_event):
                result = await followup_svc.fire_matching(
                    event, agent_turn_runner=_noop_runner,
                )
                fired.extend(result)
            await db.commit()

        activity.logger.info(
            "Supervisor followups fired",
            extra={"mission_id": mission_id, "fired_count": len(fired)},
        )
        return len(fired)
    finally:
        await redis.aclose()


@activity.defn
async def start_director_turn(
    mission_id: str,
    session_id: str,
    prompt: str,
    parent_workflow_id: str | None = None,
) -> str:
    """Start a ChatTurnWorkflow for the Director.

    Used by ADVANCE_REFINE, PROPOSE_COMPLETE, and ESCALATE paths
    to wake the Director with a system-generated prompt. Returns
    the workflow ID.

    When parent_workflow_id is set (advance_refine path), it is passed
    to ChatTurnWorkflow so it can signal the parent when done — replacing
    polling with an instant wake-up.
    """
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal.chat_models import ChatTurnInput
    from modules.backend.temporal.chat_workflow import ChatTurnWorkflow
    from modules.backend.temporal.client import get_temporal_client

    import uuid

    client = await get_temporal_client()
    config = get_app_config().temporal

    input_data = ChatTurnInput(
        session_id=session_id,
        mission_id=mission_id,
        message=prompt,
        sender_id="mission.supervisor.agent",
        agent_id="mission.director.agent",
        channel="followup",
        parent_workflow_id=parent_workflow_id,
    )

    workflow_id = f"director-followup-{mission_id[:12]}-{uuid.uuid4().hex[:8]}"

    handle = await client.start_workflow(
        ChatTurnWorkflow.run,
        input_data,
        id=workflow_id,
        task_queue=config.task_queue,
    )

    activity.logger.info(
        "Director turn started",
        extra={
            "workflow_id": workflow_id,
            "mission_id": mission_id,
            "prompt_preview": prompt[:100],
        },
    )

    return workflow_id
