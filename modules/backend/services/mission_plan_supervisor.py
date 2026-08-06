"""MissionPlanOrchestrator's post-run supervisor evaluation and decision routing.

Split out of mission_plan_orchestrator.py (Plan 84 Phase 5.2). Pure move,
no behavior change. Functions take the owning MissionPlanOrchestrator
instance (`orchestrator`) as an explicit first argument to reach
`_emit`, `refine`, and the orchestrator's repos/session — mirroring the
Phase 5.1 pattern in workflow_run_steps/.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from modules.backend.events.types import (
    MissionPlanRunCompletedEvent,
    SupervisorDecisionEmittedEvent,
    SystemEvent,
)
from modules.backend.models.mission_plan import MissionPlanStatus
from modules.backend.models.task import TaskStatus
from modules.backend.schemas.execution_outcome import TaskStatus as OutcomeStatus
from modules.backend.schemas.gate import GateAction, GateContext

if TYPE_CHECKING:
    from modules.backend.models.mission_plan import MissionPlan
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator


async def post_run_supervisor(
    orchestrator: MissionPlanOrchestrator,
    plan: MissionPlan,
    outcome,
    *,
    session_id: str | None,
) -> None:
    """Run post-run supervisor evaluation and emit events.

    Computes denormalised task counts, persists them on the
    execution_records row, emits the run-completed event, and
    fires any matching session followups in-process.
    """
    _task_results = getattr(outcome, "task_results", []) or []
    _completed = sum(1 for r in _task_results if r.status == OutcomeStatus.SUCCESS)
    _failed = sum(1 for r in _task_results if r.status == OutcomeStatus.FAILED)

    # Persist denormalised counts on the execution_records row.
    if outcome.execution_record_id:
        try:
            from modules.backend.repositories.execution_record import ExecutionRecordRepository

            _exec_repo = ExecutionRecordRepository(orchestrator._session)
            _exec_row = await _exec_repo.get_by_id_or_none(
                outcome.execution_record_id,
            )
            if _exec_row is not None:
                _exec_row.completed_task_count = _completed
                _exec_row.failed_task_count = _failed
                await orchestrator._session.flush()
        except SQLAlchemyError:
            # best-effort — denormalised display counts only; the real
            # run-completed event below is emitted unconditionally.
            orchestrator._logger.warning(
                "Failed to persist task counts on execution_record",
                extra={"execution_record_id": outcome.execution_record_id},
                exc_info=True,
            )

    _run_status = outcome.status.value if hasattr(outcome.status, "value") else str(outcome.status)

    _run_completed_event = MissionPlanRunCompletedEvent(
        session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
        source="mission_plan_orchestrator",
        mission_id=plan.mission_id,
        plan_id=plan.id,
        execution_record_id=outcome.execution_record_id or "",
        run_status=_run_status,
        run_cost_usd=float(outcome.total_cost_usd or 0.0),
        completed_task_count=_completed,
        failed_task_count=_failed,
        total_spent_usd=plan.total_spent_usd,
    )
    await orchestrator._emit(plan.mission_id, _run_completed_event)

    # Plan 52: inline supervisor for non-Temporal dispatch paths
    try:
        from modules.backend.agents.adapters.supervisor_introspection import (
            get_recent_run_outcomes,
        )
        from modules.backend.agents.mission_control.gate_post_run import (
            AutonomousPostRunReviewer,
        )

        recent = await get_recent_run_outcomes(
            orchestrator._session, mission_id=plan.mission_id, limit=5
        )
        task_states_now = await orchestrator._task_repo.get_by_plan_id(plan.id)
        summary = {
            "approved": sum(1 for s in task_states_now if s.status == TaskStatus.APPROVED),
            "proposed": sum(1 for s in task_states_now if s.status == TaskStatus.PROPOSED),
            "running": sum(1 for s in task_states_now if s.status == TaskStatus.RUNNING),
            "completed": sum(1 for s in task_states_now if s.status in (TaskStatus.COMPLETED,)),
            "failed": sum(1 for s in task_states_now if s.status == TaskStatus.FAILED),
            "total_completed": sum(r.get("completed_task_count", 0) for r in recent),
            "execution_record_id": outcome.execution_record_id,
            "max_supervisor_iterations": plan.max_supervisor_iterations,
        }
        mission_obj = await orchestrator._mission_repo.get_by_id(plan.mission_id)
        context = GateContext(
            gate_type="post_run",
            mission_id=plan.mission_id,
            session_id=session_id,
            total_cost_usd=plan.total_spent_usd,
            budget_usd=plan.budget_usd_ceiling or 0.0,
            recent_run_outcomes=recent,
            plan_task_summary=summary,
            mission_brief=mission_obj.brief or mission_obj.description or "",
            supervisor_iteration_count=plan.supervisor_iteration_count,
        )
        reviewer = AutonomousPostRunReviewer(
            session=orchestrator._session, gate_mode=plan.gate_mode
        )
        decision = await reviewer.review(context)
        plan.supervisor_iteration_count += 1
        await apply_supervisor_decision(
            orchestrator,
            plan,
            decision,
            outcome,
            session_id=session_id,
        )
        await orchestrator._session.flush()
        # Emit decision event
        _decision_event = SupervisorDecisionEmittedEvent(
            session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
            source="mission_plan_orchestrator",
            mission_id=plan.mission_id,
            plan_id=plan.id,
            execution_record_id=outcome.execution_record_id or "",
            action=decision.action.value,
            reason=(decision.reason or "")[:500],
            reviewer=decision.reviewer,
        )
        await orchestrator._emit(plan.mission_id, _decision_event)
        orchestrator._log_operation(
            "Post-run supervisor", plan_id=plan.id, action=decision.action.value
        )

        # Fire matching session followups so the Director wakes up
        # and posts a proactive chat update (Plan 51 Phase E).
        await fire_followups(
            orchestrator,
            plan,
            _run_completed_event,
            _decision_event,
        )
    except Exception:
        # Catch-all justified: wraps the post-run supervisor
        # evaluation (LLM review, DB writes, decision application,
        # followups) whose exception surface is unbounded — logged
        # and emitted here so the plan pauses visibly rather than
        # advancing on a half-applied decision.
        orchestrator._logger.warning("Post-run supervisor evaluation failed", exc_info=True)
        await orchestrator._emit(
            plan.mission_id,
            SystemEvent(
                session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
                source="mission_plan_orchestrator",
                level="error",
                message=(
                    "Post-run supervisor evaluation failed — the plan will not "
                    "automatically advance; review and dispatch manually."
                ),
                mission_id=plan.mission_id,
            ),
        )


async def fire_followups(
    orchestrator: MissionPlanOrchestrator,
    plan: MissionPlan,
    run_event,
    decision_event,
) -> None:
    """Fire matching session followups for both supervisor events.

    Creates a lightweight agent_turn_runner adapter that starts a
    Director chat turn via handle_mission. Followup failures are
    swallowed by SessionFollowupService — they never block the
    dispatch path.
    """
    from modules.backend.services.session_followup import SessionFollowupService

    followup_svc = SessionFollowupService(
        orchestrator._session,
        event_bus=orchestrator._event_bus,
    )

    async def _agent_turn_runner(
        session_id: str,
        mission_id: str,
        prompt: str,
    ) -> None:
        """Adapter: start a Director chat turn for the followup."""
        from modules.backend.agents.mission_control.mission_control import handle_mission
        from modules.backend.services.session import SessionService

        await handle_mission(
            mission_run_id=plan.id,
            mission_brief=prompt,
            session_service=SessionService(orchestrator._session),  # type: ignore[arg-type]
            event_bus=orchestrator._event_bus,
            session_id=session_id,
            mission_id=mission_id,
            db_session=orchestrator._session,
        )

    # Fire for both events — followups may subscribe to either
    # "mission_plan.run.completed" or "mission_plan.supervisor_decision".
    for event in (run_event, decision_event):
        try:
            await followup_svc.fire_matching(
                event,
                agent_turn_runner=_agent_turn_runner,
            )
        except Exception:
            # Catch-all justified: _agent_turn_runner calls
            # handle_mission() (an LLM-driven chat turn) whose
            # exception surface is unbounded. best-effort — the
            # dispatch/run itself already completed successfully;
            # only the proactive Director chat notification failed
            # to fire.
            orchestrator._logger.warning(
                "Failed to fire followups for event",
                extra={
                    "event_type": getattr(event, "event_type", "unknown"),
                    "plan_id": plan.id,
                },
                exc_info=True,
            )


async def apply_supervisor_decision(
    orchestrator: MissionPlanOrchestrator,
    plan: MissionPlan,
    decision,
    outcome,
    *,
    session_id: str | None,
) -> None:
    """Route the supervisor's gate decision (inline path).

    Used when dispatch_approved is called directly (e.g. the UI Run
    button). The Temporal MissionRunWorkflow has its own decision
    routing. ADVANCE_APPROVED and ADVANCE_REFINE prepare state for
    the next dispatch cycle without looping.
    """
    action = decision.action

    # Safety: re-read plan status before mutating. If the plan was
    # paused or completed while the supervisor was evaluating, refuse
    # to advance — only PROPOSE_COMPLETE and ESCALATE (which pause
    # the plan themselves) are safe to apply regardless.
    await orchestrator._session.refresh(plan, ["status"])
    _plan_active = plan.status == MissionPlanStatus.ACTIVE

    if action in (GateAction.WAIT, GateAction.ADVANCE_APPROVED, GateAction.ADVANCE_REFINE):
        if not _plan_active:
            orchestrator._log_operation(
                f"Supervisor: {action.value} suppressed — plan is {plan.status}",
                plan_id=plan.id,
            )
            return

    if action == GateAction.WAIT:
        # Approved tasks still pending — next dispatch cycle picks them up.
        orchestrator._log_operation(
            "Supervisor: WAIT",
            plan_id=plan.id,
            reason="Approved tasks remain; next dispatch picks them up",
        )

    elif action == GateAction.ADVANCE_APPROVED:
        # Flip all proposed → approved for the next dispatch cycle.
        mission_obj = await orchestrator._mission_repo.get_by_id(plan.mission_id)
        await orchestrator._plan_svc.approve_all_proposed(
            plan.id,
            mission_obj.owner_id,
        )
        orchestrator._log_operation(
            "Supervisor: ADVANCE_APPROVED",
            plan_id=plan.id,
        )

    elif action == GateAction.ADVANCE_REFINE:
        # Ask the Planning Agent to generate the next wave of tasks,
        # then approve the new proposed tasks for dispatch.
        _run_status = (
            outcome.status.value if hasattr(outcome.status, "value") else str(outcome.status)
        )
        instructions = (
            f"The last wave {_run_status}. "
            f"Total cost so far: ${plan.total_spent_usd:.2f}. "
            f"Generate the next wave of tasks based on outcomes."
        )
        try:
            await orchestrator.refine(
                plan.id,
                instructions,
                "mission.supervisor.agent",
                mission_budget_usd=(
                    plan.budget_usd_ceiling - plan.total_spent_usd
                    if plan.budget_usd_ceiling is not None
                    else 10.0
                ),
            )
            # Auto-approve newly proposed tasks so daemon dispatches them.
            _mission_obj = await orchestrator._mission_repo.get_by_id(plan.mission_id)
            await orchestrator._plan_svc.approve_all_proposed(
                plan.id,
                _mission_obj.owner_id,
            )
        except Exception:
            # Catch-all justified: wraps orchestrator.refine() (Planning
            # Agent LLM call) whose exception surface is unbounded — the
            # plan is paused and a SystemEvent emitted so a human can
            # intervene rather than the mission silently stalling.
            orchestrator._logger.warning(
                "Supervisor ADVANCE_REFINE: refinement failed, " "pausing plan for human review",
                exc_info=True,
            )
            plan.status = MissionPlanStatus.PAUSED
            await orchestrator._emit(
                plan.mission_id,
                SystemEvent(
                    session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
                    source="mission_plan_orchestrator",
                    level="error",
                    message=("Supervisor refinement failed — plan paused for human review."),
                    mission_id=plan.mission_id,
                ),
            )
        orchestrator._log_operation(
            "Supervisor: ADVANCE_REFINE",
            plan_id=plan.id,
        )

    elif action == GateAction.PROPOSE_COMPLETE:
        # Plan stays active — an idle plan with zero approved tasks
        # costs nothing. The Director followup asks the user to
        # confirm completion; the user archives when ready.
        orchestrator._log_operation(
            "Supervisor: PROPOSE_COMPLETE — notifying user",
            plan_id=plan.id,
            reason=(decision.reason or "")[:200],
        )

    elif action == GateAction.ESCALATE:
        # Pause and escalate — human attention required.
        plan.status = MissionPlanStatus.PAUSED
        orchestrator._log_operation(
            "Supervisor: ESCALATE — plan paused for human review",
            plan_id=plan.id,
            reason=(decision.reason or "")[:200],
        )

    else:
        # Unknown action — safe default: do nothing, log.
        orchestrator._logger.warning(
            "Supervisor returned unknown action",
            extra={"action": str(action), "plan_id": plan.id},
        )
