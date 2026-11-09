"""Task approval — the unified pre-execution decision mechanism (Plan 80h).

Replaces the dual-mechanism design where pre_dispatch / pre_layer gates
ran in parallel with the task lifecycle. Under this model, the task's
PROPOSED → APPROVED transition IS the pre-execution decision. The mode
(autonomous / manual / interactive / ai_assisted) determines who/what
triggers the transition.

Design (Plan 88.0.13a): the dispatcher waits inside the Temporal worker
process while approvals are committed by the API process, so the waiter
polls the task row every ``poll_interval_seconds`` until its status leaves
PROPOSED. The database row is the only coupling between the two processes,
mirroring ``ManualGateReviewer._wait_for_decision`` in gate_manual.py.

Usage from a dispatcher:

    manual = get_app_config().gate.manual
    await wait_until_approved(
        task_id=task.id,
        session_factory=get_session_factory(),
        timeout_seconds=manual.timeout_seconds,
        poll_interval_seconds=manual.poll_interval_seconds,
    )
    # task is now past approval (or an exception was raised)

The approve and retry endpoints only commit the state change; there is
nothing to notify.
"""

from __future__ import annotations

import asyncio
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# Mirror modules.backend.models.task.TaskStatus's string values — this
# module only ever compares against the plain string a service returns,
# so it takes the literals rather than importing the models-layer enum
# (rule 011.1).
_STATUS_PROPOSED = "proposed"
_STATUS_CANCELLED = "cancelled"


async def wait_until_approved(
    *,
    task_id: str,
    session_factory: Any,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> None:
    """Block until the task's status leaves PROPOSED.

    Resolves immediately if the task is already past approval (APPROVED /
    QUEUED / RUNNING / COMPLETED / FAILED / SKIPPED) when called.

    Raises:
        TaskApprovalUnknown: if the task row does not exist.
        TaskApprovalCancelled: if the task is, or becomes, CANCELLED.
        TaskApprovalTimeout: if ``timeout_seconds`` elapses while the task
            is still PROPOSED.
        asyncio.CancelledError: propagated unchanged (mission abort,
            worker shutdown). The task row is NOT auto-marked; the
            dispatcher's normal failure-handling deals with that.
    """
    from modules.backend.services.mission_plan import MissionPlanService

    async def _current_status() -> str | None:
        async with session_factory() as session:
            task = await MissionPlanService(session).get_task(task_id)
            if task is None:
                return None
            return task.status.value if hasattr(task.status, "value") else str(task.status)

    def _resolve(status: str | None) -> bool:
        """True when the wait is over; raises for the no-go states."""
        if status is None:
            raise TaskApprovalUnknown(
                f"Cannot wait for task {task_id}: row does not exist.",
            )
        if status == _STATUS_CANCELLED:
            raise TaskApprovalCancelled(
                f"Task {task_id} is CANCELLED; refusing to dispatch.",
            )
        return status != _STATUS_PROPOSED

    if _resolve(await _current_status()):
        return

    logger.info(
        "Task waiting for approval",
        extra={
            "task_id": task_id,
            "timeout_seconds": timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        },
    )

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        await asyncio.sleep(poll_interval_seconds)
        if _resolve(await _current_status()):
            logger.info(
                "Task approval received — dispatcher resuming",
                extra={"task_id": task_id},
            )
            return

    raise TaskApprovalTimeout(
        f"Task {task_id} not approved within {timeout_seconds}s.",
    )


class TaskApprovalUnknown(Exception):
    """Raised when wait_until_approved is called for a non-existent task."""


class TaskApprovalCancelled(Exception):
    """Raised when wait_until_approved finds the task CANCELLED.

    Cancellation is an explicit operator decision (or a transitive consequence
    of one); the dispatcher must not run a cancelled task.
    """


class TaskApprovalTimeout(Exception):
    """Raised when an approval doesn't arrive within the timeout window."""
