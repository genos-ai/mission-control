"""
Mission Plan Crash Recovery (Plan 46, updated by Plan 72).

Reconciles orphaned Task rows after a backend restart.

When the backend crashes, any task that was mid-run is left in ``running``
or ``queued`` status with no process that knows about it. This module
transitions them to safe states at startup:

    running  -> failed    (failure_reason = "backend restart - run orphaned")
    queued   -> approved  (never attempted, safe to re-dispatch)

Plan 72: queries the `tasks` table directly instead of `plan_task_states`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.events.types import MissionPlanTaskStatusChangedEvent, SystemEvent
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.task import TaskRepository

logger = get_logger(__name__)


ORPHAN_FAILURE_REASON = "backend restart — run orphaned"
"""Marker set on failure_reason so the UI can style orphaned tasks distinctly."""

CRASH_RECOVERY_ACTOR = "system:crash-recovery"
"""Actor tag on emitted status_changed events so the audit trail is clear."""


async def reconcile_orphaned_task_states(
    session: AsyncSession,
    event_bus: Any | None = None,
    plan_id: str | None = None,
) -> dict[str, int]:
    """Transition every orphaned in-flight task to a safe status.

    Call at backend startup BEFORE the mission plan daemon begins
    polling, or before dispatch_approved to clean up orphans from
    a prior failed dispatch.

    When plan_id is provided, only reconciles tasks for that plan.
    When None, reconciles all in-flight tasks (startup mode).

    Returns a stats dict for logging.
    """
    task_repo = TaskRepository(session)
    in_flight = await task_repo.list_in_flight(plan_id=plan_id)

    if not in_flight:
        logger.info("Crash recovery: no orphaned tasks to reconcile")
        return {"running_to_failed": 0, "queued_to_approved": 0}

    running_to_failed = 0
    queued_to_approved = 0
    # Buffer transitions for event emission after flush
    emit_buffer: list[tuple[str, str, str, str, str]] = []
    # tuple = (mission_id, plan_id, task_id, from_status, to_status)

    for task in in_flight:
        from_status = task.status
        mission_id = task.mission_id
        plan_id = task.plan_id

        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.FAILED
            task.failure_reason = ORPHAN_FAILURE_REASON
            task.last_attempt_at = utc_now()
            running_to_failed += 1
            emit_buffer.append((mission_id, plan_id, task.id, from_status, TaskStatus.FAILED))
        elif task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.APPROVED
            queued_to_approved += 1
            emit_buffer.append((mission_id, plan_id, task.id, from_status, TaskStatus.APPROVED))

    await session.flush()

    logger.info(
        "Crash recovery: reconciled orphaned tasks",
        extra={
            "running_to_failed": running_to_failed,
            "queued_to_approved": queued_to_approved,
            "total_reconciled": len(emit_buffer),
        },
    )

    # Emit events best-effort
    if event_bus is not None:
        for mission_id, plan_id, task_id, from_status, to_status in emit_buffer:
            try:
                await event_bus.publish_to_mission(
                    mission_id,
                    MissionPlanTaskStatusChangedEvent(
                        session_id=uuid.uuid4(),
                        source="mission_plan_crash_recovery",
                        mission_id=mission_id,
                        plan_id=plan_id,
                        task_id=task_id,
                        from_status=from_status,
                        to_status=to_status,
                        actor=CRASH_RECOVERY_ACTOR,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                # best-effort — this IS the event-emission path (see
                # "Emit events best-effort" above); nowhere further to
                # escalate to.
                logger.warning(
                    "Crash recovery: failed to publish status_changed event",
                    extra={
                        "mission_id": mission_id,
                        "plan_id": plan_id,
                        "task_id": task_id,
                        "error": str(exc),
                    },
                )

        affected_missions = {mid for mid, *_ in emit_buffer}
        for mid in affected_missions:
            try:
                await event_bus.publish_to_mission(
                    mid,
                    SystemEvent(
                        session_id=uuid.uuid4(),
                        source="crash_recovery",
                        level="warning",
                        message=(
                            f"Crash recovery: {running_to_failed} task(s) marked failed, "
                            f"{queued_to_approved} task(s) re-approved after backend restart"
                        ),
                        mission_id=mid,
                    ),
                )
            except Exception:
                logger.debug(
                    "event publish failed after crash recovery (best-effort)", exc_info=True
                )

    return {
        "running_to_failed": running_to_failed,
        "queued_to_approved": queued_to_approved,
    }


async def reconcile_orphaned_workflow_runs(
    session: AsyncSession,
    event_bus: Any | None = None,
) -> int:
    """Mark WorkflowRun rows stuck in RUNNING or PENDING as FAILED.

    A workflow run transitions to RUNNING when dispatch starts and only
    leaves that state when _execute_steps finishes — whether driven
    in-process or, since Plan 84 Phase 3.1, by the RunWorkflowWorkflow
    Temporal activity. Temporal resumes its own runs after a backend
    restart, so this reconciler only catches the two cases Temporal
    cannot: runs dispatched before Phase 3.1's Temporal routing existed,
    and runs whose Temporal *worker* (not just the API process) died
    mid-activity, leaving nothing to ever flip the row to a terminal
    state.
    """
    from sqlalchemy import select

    from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState

    result = await session.execute(
        select(WorkflowRun).where(
            WorkflowRun.status.in_([WorkflowRunState.RUNNING, WorkflowRunState.PENDING])
        )
    )
    orphaned = list(result.scalars().all())
    if not orphaned:
        logger.info("Crash recovery: no orphaned workflow runs to reconcile")
        return 0

    for run in orphaned:
        run.status = WorkflowRunState.FAILED
        run.completed_at = utc_now()
        run.error_data = {"message": ORPHAN_FAILURE_REASON, "type": "CrashRecovery"}
        run.result_summary = f"Workflow failed: {ORPHAN_FAILURE_REASON}"

    await session.flush()

    count = len(orphaned)
    logger.info(
        "Crash recovery: reconciled orphaned workflow runs",
        extra={"count": count},
    )

    # Emit events best-effort
    if event_bus is not None:
        from modules.backend.events.types import WorkflowRunFailedEvent

        for run in orphaned:
            if not run.mission_id:
                continue
            try:
                session_id = uuid.UUID(run.session_id) if run.session_id else uuid.uuid4()
                await event_bus.publish_to_mission(
                    run.mission_id,
                    WorkflowRunFailedEvent(
                        session_id=session_id,
                        source="mission_plan_crash_recovery",
                        workflow_run_id=run.id,
                        workflow_name=run.workflow_name,
                        error=ORPHAN_FAILURE_REASON,
                        total_cost_usd=run.total_cost_usd,
                    ),
                )
            except Exception:
                logger.debug(
                    "Crash recovery: failed to publish workflow_run.failed event " "(best-effort)",
                    exc_info=True,
                )

    return count


async def reconcile_orphaned_execution_records(
    session: AsyncSession,
) -> int:
    """Mark execution records stuck in RUNNING or PENDING as FAILED.

    Tool-fork workflows (RunWorkflowWorkflow, DesignWorkflowWorkflow) set
    execution_record status to RUNNING at start. If the Temporal worker
    crashes, the record stays RUNNING forever. This reconciler transitions
    them to FAILED so they don't block future dispatches.
    """
    from sqlalchemy import update

    from modules.backend.models.execution_record import ExecutionRecord, ExecutionRecordStatus

    result = await session.execute(
        update(ExecutionRecord)
        .where(
            ExecutionRecord.status.in_(
                [
                    ExecutionRecordStatus.RUNNING,
                    ExecutionRecordStatus.PENDING,
                ]
            )
        )
        .values(status=ExecutionRecordStatus.FAILED)
    )
    count = result.rowcount
    if count > 0:
        await session.flush()
        logger.info(
            "Crash recovery: reconciled orphaned execution records",
            extra={"count": count},
        )
    return count
