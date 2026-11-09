"""
Supervisor loop activities (Plan 52 Phase C).

Activities for the MissionRunWorkflow's post-run supervisor loop:

1. evaluate_post_run — runs AutonomousPostRunReviewer with own DB session
2. approve_run_proposed_tasks — flips the run's proposed → approved when
   the run's gate mode is AUTONOMOUS (idempotent)
3. start_director_turn — starts a ChatTurnWorkflow for the Director
   (used by ADVANCE_REFINE, PROPOSE_COMPLETE, ESCALATE paths)

Each activity opens its own DB session and commits independently.
"""

from dataclasses import dataclass

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.schemas.gate import GateContext
from modules.backend.temporal.mission_run_models import DirectorTurnInput, SupervisorFollowupInput

logger = get_logger(__name__)


async def _emit_supervisor_error(mission_id: str, message: str) -> None:
    """Emit a SystemEvent from a supervisor activity so errors surface in the console."""
    from modules.backend.temporal.activity_helpers import emit_activity_error

    await emit_activity_error(mission_id, "mission.supervisor", message)


@dataclass
class PostRunEvalInput:
    """Input for the evaluate_post_run activity."""

    mission_id: str
    mission_run_id: str
    execution_record_id: str
    supervisor_iteration_count: int
    session_id: str


@dataclass
class PostRunEvalResult:
    """Output from evaluate_post_run."""

    action: str  # wait, advance_approved, advance_refine, propose_complete, escalate
    reason: str = ""
    reviewer: str = "config:rule_engine"
    confidence: float | None = None
    cost_usd: float = 0.0


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
            "mission_run_id": input.mission_run_id,
            "execution_record_id": input.execution_record_id,
        },
    )

    try:
        return await _do_evaluate_post_run(input)
    except Exception as e:
        # Catch-all justified: Temporal activity boundary wrapping the
        # AutonomousPostRunReviewer (LLM call) whose exception surface is
        # unbounded — must convert to a failed PostRunEvalResult rather
        # than raise.
        from modules.backend.temporal.activities import _format_activity_error

        clean_msg = _format_activity_error(e)
        activity.logger.error(
            "evaluate_post_run failed",
            extra={
                "mission_run_id": input.mission_run_id,
                "error": clean_msg,
                "error_type": type(e).__name__,
                "mission_id": input.mission_id,
            },
            exc_info=True,
        )
        await _emit_supervisor_error(
            input.mission_id,
            f"Post-run evaluation failed: {clean_msg}",
        )
        raise


async def _do_evaluate_post_run(input: PostRunEvalInput) -> PostRunEvalResult:
    """Inner logic for evaluate_post_run — separated for error wrapping.

    The gate mode comes from the run; the brief, iteration cap, budget and
    spend from the mission and its plan (Phase 4 moves the last three).
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.agents.adapters.supervisor_introspection import get_recent_run_outcomes
    from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer
    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.models.mission_plan import GateMode
    from modules.backend.models.task import TaskStatus
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_plan import MissionPlanService, remaining_plan_budget_usd
    from modules.backend.services.mission_run import MissionRunService

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        async with get_async_session() as db:
            run = await MissionRunService(db, SessionEventBus(redis)).get_run(
                input.mission_id, input.mission_run_id
            )
            gate_mode = GateMode(run.gate_mode)
            mission = await MissionService(db).get_mission(input.mission_id)
            recent = await get_recent_run_outcomes(
                db,
                mission_id=input.mission_id,
                limit=5,
            )

            # Build task summary from the DB
            svc = MissionPlanService(db)
            plan = await svc.get_or_create_plan(input.mission_id)
            task_states = await svc.get_tasks(plan.id)
            total_spent_usd = plan.total_spent_usd
            budget_usd = total_spent_usd + remaining_plan_budget_usd(plan)

            summary = {
                "approved": sum(1 for s in task_states if s.status == TaskStatus.APPROVED),
                "proposed": sum(1 for s in task_states if s.status == TaskStatus.PROPOSED),
                "running": sum(1 for s in task_states if s.status == TaskStatus.RUNNING),
                "completed": sum(1 for s in task_states if s.status == TaskStatus.COMPLETED),
                "failed": sum(1 for s in task_states if s.status == TaskStatus.FAILED),
                "total_completed": sum(r.get("completed_task_count", 0) for r in recent),
                "execution_record_id": input.execution_record_id,
                "max_supervisor_iterations": plan.max_supervisor_iterations,
            }

            context = GateContext(
                gate_type="post_run",
                mission_id=input.mission_id,
                session_id=input.session_id,
                total_cost_usd=total_spent_usd,
                budget_usd=budget_usd,
                recent_run_outcomes=recent,
                plan_task_summary=summary,
                mission_brief=mission.brief or "",
                supervisor_iteration_count=input.supervisor_iteration_count,
            )

            reviewer = AutonomousPostRunReviewer(
                session=db,
                gate_mode=gate_mode,
            )
            decision = await reviewer.review(context)

            # Increment supervisor iteration counter
            plan.supervisor_iteration_count += 1
            await db.flush()
            await db.commit()
    finally:
        await redis.aclose()

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
async def approve_run_proposed_tasks(mission_run_id: str) -> int:
    """Approve the run's proposed tasks when its gate mode is AUTONOMOUS; else return 0.

    Idempotent — tasks already approved (from a replay) are left untouched.
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.mission_run import MissionRunService

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        async with get_async_session() as db:
            count = await MissionRunService(db, SessionEventBus(redis)).approve_proposed(
                mission_run_id
            )
    finally:
        await redis.aclose()

    activity.logger.info(
        "Approved run proposed tasks",
        extra={"mission_run_id": mission_run_id, "count": count},
    )
    return count


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

        return plan.status == MissionPlanStatus.ACTIVE


@activity.defn
async def fire_supervisor_followups(input: SupervisorFollowupInput) -> None:
    """Fire session followups after a supervisor decision.

    Emits SupervisorDecisionEmittedEvent, then fires matching session
    followups so the Director wakes up and reports to the user.
    """
    import uuid as _uuid

    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.events.types import SupervisorDecisionEmittedEvent
    from modules.backend.services.session_followup import SessionFollowupService

    mission_id = input.mission_id
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        event_bus = SessionEventBus(redis, mission_id=mission_id)

        decision_event = SupervisorDecisionEmittedEvent(
            session_id=_uuid.uuid4(),
            source="temporal_supervisor",
            mission_id=mission_id,
            execution_record_id=input.execution_record_id,
            action=input.action,
            reason=input.reason[:500],
            reviewer=input.reviewer,
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

            fired = await followup_svc.fire_matching(
                decision_event,
                agent_turn_runner=_noop_runner,
            )
            await db.commit()

        activity.logger.info(
            "Supervisor followups fired",
            extra={
                "mission_id": mission_id,
                "mission_run_id": input.mission_run_id,
                "wave_status": input.wave_status,
                "wave_cost_usd": input.wave_cost_usd,
                "failure_reason": input.failure_reason,
                "fired_count": len(fired),
            },
        )
    finally:
        await redis.aclose()


@activity.defn
async def start_director_turn(input: DirectorTurnInput) -> str:
    """Start a ChatTurnWorkflow for the Director.

    Used by ADVANCE_REFINE, PROPOSE_COMPLETE, and ESCALATE paths
    to wake the Director with a system-generated prompt. Returns
    the workflow ID.

    When signal_workflow_id is set (advance_refine path), it is passed
    to ChatTurnWorkflow so it can signal that workflow when done — replacing
    polling with an instant wake-up.
    """
    import uuid

    from modules.backend.core.config import get_app_config
    from modules.backend.temporal.chat_models import ChatTurnInput
    from modules.backend.temporal.chat_workflow import ChatTurnWorkflow
    from modules.backend.temporal.client import get_temporal_client

    client = await get_temporal_client()
    config = get_app_config().temporal

    input_data = ChatTurnInput(
        session_id=input.session_id,
        mission_id=input.mission_id,
        message=input.prompt,
        sender_id="mission.supervisor.agent",
        agent_id="mission.director.agent",
        channel="followup",
        parent_workflow_id=input.signal_workflow_id,
    )

    workflow_id = f"director-followup-{input.mission_id[:12]}-{uuid.uuid4().hex[:8]}"

    await client.start_workflow(
        ChatTurnWorkflow.run,
        input_data,
        id=workflow_id,
        task_queue=config.task_queue,
    )

    activity.logger.info(
        "Director turn started",
        extra={
            "workflow_id": workflow_id,
            "mission_id": input.mission_id,
            "mission_run_id": input.mission_run_id,
            "prompt_preview": input.prompt[:100],
        },
    )

    return workflow_id
