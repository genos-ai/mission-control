"""
Mission Plan Crash Recovery (Plan 46 Phase 1 work unit #2).

Reconciles orphaned ``plan_task_states`` rows after a backend restart.

When the backend crashes (OOM, deploy, kernel panic, whatever), any plan
task that was mid-run is left in ``running`` or ``queued`` status in the
DB with no process that knows about it. On the next startup, if nothing
reconciles those rows, they sit there forever — the UI shows tasks
"running" that are not, budget accounting never closes out, and the
daemon refuses to touch them because they're not in ``approved``.

This module provides ``reconcile_orphaned_task_states()`` which runs at
FastAPI startup (before the mission plan daemon starts polling) and
transitions in-flight rows to safe states:

    running  → failed    (failure_reason = "backend restart — run orphaned")
    queued   → approved  (never attempted, safe to re-dispatch)

Design choices:

  - Split out of ``MissionPlanService`` (services/mission_plan.py is
    already at 933 lines and carries a code-review P9 item flagging it
    for a four-way split). This module is a thin startup helper, not a
    long-lived service class.

  - Called at FastAPI startup *unconditionally* — not gated on the
    ``experimental_mission_plan_daemon_enabled`` feature flag — because
    orphans can exist regardless of whether the daemon is on. If a user
    dispatched a plan manually and the backend crashed mid-run, the
    orphan still needs clearing on next boot.

  - Idempotent: running it a second time finds no in-flight rows (the
    first pass cleared them) and is a no-op. Safe to call from multiple
    startup hooks if needed.

  - Emits ``MissionPlanTaskStatusChangedEvent`` per transition with
    ``actor="system:crash-recovery"`` so connected SSE clients see the
    kanban update live and so the audit trail is clean.

  - Swallows Redis failures (via the service's existing ``_emit()``
    helper) — event emission is best-effort; the DB transition is the
    source of truth.

Known limitation — single-process assumption:

  In a multi-process backend deployment (e.g. multiple uvicorn workers),
  process A might be actively running tasks while process B restarts.
  This reconciler, running in process B's startup, would spuriously mark
  process A's healthy running tasks as orphaned. The correct fix is a
  per-task heartbeat mechanism that this reconciler consults — tasks
  whose heartbeat is fresher than ``orphan_ttl_seconds`` are left alone,
  only stale-heartbeat tasks are transitioned. That's a future
  enhancement tracked separately; for the current single-process dev
  deployment this limitation is documented and accepted.

  The Plan 46 Phase 1 work unit #3 (daemon liveness heartbeat) is the
  primitive that makes per-task heartbeats easy to build later.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.events.types import MissionPlanTaskStatusChangedEvent
from modules.backend.models.mission_plan import PlanTaskStatus
from modules.backend.repositories.mission_plan import MissionPlanRepository

logger = get_logger(__name__)


ORPHAN_FAILURE_REASON = "backend restart — run orphaned"
"""Marker set on failure_reason so the UI can style orphaned tasks distinctly."""

CRASH_RECOVERY_ACTOR = "system:crash-recovery"
"""Actor tag on emitted status_changed events so the audit trail is clear."""


async def reconcile_orphaned_task_states(
    session: AsyncSession,
    event_bus: Any | None = None,
) -> dict[str, int]:
    """Transition every orphaned in-flight task state to a safe status.

    Call at backend startup BEFORE the mission plan daemon begins
    polling. Returns a stats dict so the caller can log the
    reconciliation result.

    Args:
        session: Open async SQLAlchemy session for DB writes.
        event_bus: Optional event bus for emitting
            ``MissionPlanTaskStatusChangedEvent``.  When None, events
            are skipped (DB state still transitions — events are
            best-effort signalling on top).

    Returns:
        Dict with counts:
            - ``running_to_failed``: tasks transitioned running → failed
            - ``queued_to_approved``: tasks transitioned queued → approved
    """
    repo = MissionPlanRepository(session)
    in_flight = await repo.list_in_flight_task_states()

    if not in_flight:
        logger.info(
            "Crash recovery: no orphaned task states to reconcile",
        )
        return {"running_to_failed": 0, "queued_to_approved": 0}

    running_to_failed = 0
    queued_to_approved = 0
    # Buffer transitions so we can emit events AFTER the DB flush
    # (avoids emitting for a transition that failed to persist).
    emit_buffer: list[tuple[str, str, str, str, str]] = []
    # tuple = (mission_id, plan_id, task_id, from_status, to_status)

    for state in in_flight:
        from_status = state.status
        mission_id = state.plan.mission_id  # eager-loaded
        plan_id = state.mission_plan_id

        if state.status == PlanTaskStatus.RUNNING.value:
            state.status = PlanTaskStatus.FAILED.value
            state.failure_reason = ORPHAN_FAILURE_REASON
            state.task_execution_id = None
            state.last_attempt_at = utc_now()
            running_to_failed += 1
            emit_buffer.append(
                (mission_id, plan_id, state.task_id, from_status, PlanTaskStatus.FAILED.value)
            )
        elif state.status == PlanTaskStatus.QUEUED.value:
            # Queued means dispatched by plan-level gating but the
            # agent never picked it up. No partial work to worry about;
            # restore to approved so the daemon (or user) can re-queue.
            state.status = PlanTaskStatus.APPROVED.value
            state.task_execution_id = None
            queued_to_approved += 1
            emit_buffer.append(
                (mission_id, plan_id, state.task_id, from_status, PlanTaskStatus.APPROVED.value)
            )

    await session.flush()

    logger.info(
        "Crash recovery: reconciled orphaned task states",
        extra={
            "running_to_failed": running_to_failed,
            "queued_to_approved": queued_to_approved,
            "total_reconciled": len(emit_buffer),
        },
    )

    # Emit events best-effort. A Redis blip must not block startup.
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
                logger.warning(
                    "Crash recovery: failed to publish status_changed event",
                    extra={
                        "mission_id": mission_id,
                        "plan_id": plan_id,
                        "task_id": task_id,
                        "error": str(exc),
                    },
                )

    return {
        "running_to_failed": running_to_failed,
        "queued_to_approved": queued_to_approved,
    }
