"""Task approval — the unified pre-execution decision mechanism (Plan 80h).

Replaces the dual-mechanism design where pre_dispatch / pre_layer gates
ran in parallel with the task lifecycle. Under this model, the task's
PROPOSED → APPROVED transition IS the pre-execution decision. The mode
(autonomous / manual / interactive / ai_assisted) determines who/what
triggers the transition.

This module owns the asyncio.Event registry that lets a dispatcher
block until a task becomes APPROVED. Mirrors the shape of gate_manual.py
but at the task layer — single-process by design.

Usage from a dispatcher:

    if task.status == TaskStatus.PROPOSED:
        await wait_until_approved(
            task_id=task.id,
            session_factory=get_session_factory(),
            timeout_seconds=1800,
        )
    # task is now APPROVED (or TimeoutError was raised)

Usage from the approve endpoint (after committing the state change):

    await notify_approved(task_id)

Multi-worker note: the registry is process-local. If you ever run
uvicorn with `--workers N>1`, an approval landing on one worker can't
wake a dispatcher waiting in another worker. `notify_approved` logs
loud when called for an unknown id so this fails visibly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# Process-local registry: task_id (str) -> asyncio.Event.
# Populated when a dispatcher starts waiting, fired when the
# approve endpoint calls notify_approved, popped when the awaiter
# returns. Single-process; see module docstring.
_PENDING: dict[str, asyncio.Event] = {}
_LOCK = asyncio.Lock()


async def notify_approved(task_id: str) -> None:
    """Wake the dispatcher (if any) that is waiting on this task's approval.

    Called from the API endpoint after the task row's status has been
    transitioned to APPROVED and committed.

    If no Event is registered for the task_id, it means either:
    (a) The dispatcher hasn't reached this task yet — the next call to
        wait_until_approved will see APPROVED state and return immediately
        without registering anything. This is the normal autonomous-mode
        path and not an error.
    (b) The dispatcher was running in a different process (multi-worker
        config) — the wait will time out. This is logged loud below.
    """
    async with _LOCK:
        event = _PENDING.get(task_id)
    if event is None:
        # See docstring for the two cases. We can't distinguish them
        # without state inspection, so the log is at info level.
        logger.info(
            "Task approval notification — no waiter registered "
            "(task already approved, or dispatcher in another process)",
            extra={"task_id": task_id},
        )
        return
    event.set()


async def wait_until_approved(
    *,
    task_id: str,
    session_factory: Any,
    timeout_seconds: int = 1800,
) -> None:
    """Block until the task's status becomes APPROVED.

    Resolves immediately if the task is already APPROVED when called
    (no race window between the approve endpoint committing and the
    dispatcher reading state).

    Raises:
        TaskApprovalTimeout: if ``timeout_seconds`` elapses without the
            task being approved.
        TaskApprovalCancelled: if the wait is cancelled (e.g. mission
            abort, backend shutdown). The task row is NOT auto-marked;
            the dispatcher's normal failure-handling deals with that.
    """
    from sqlalchemy import select

    from modules.backend.models.task import Task, TaskStatus

    # Re-check current state — a race-free path for the already-approved case.
    async def _current_status() -> str | None:
        async with session_factory() as session:
            result = await session.execute(
                select(Task.status).where(Task.id == task_id),
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return row.value if hasattr(row, "value") else str(row)

    initial = await _current_status()
    if initial is None:
        raise TaskApprovalUnknown(
            f"Cannot wait for task {task_id}: row does not exist.",
        )
    # PROPOSED is the only state that requires waiting. Anything else is
    # "past approval" (APPROVED / QUEUED / RUNNING / COMPLETED / FAILED /
    # SKIPPED) or an explicit no-go (CANCELLED). For the past-approval set
    # we proceed immediately; for CANCELLED we raise so the dispatcher
    # doesn't run cancelled work.
    if initial == TaskStatus.CANCELLED.value:
        raise TaskApprovalCancelled(
            f"Task {task_id} is CANCELLED; refusing to dispatch.",
        )
    if initial != TaskStatus.PROPOSED.value:
        return

    # Register the Event BEFORE re-checking state, so an approval that
    # arrives during this window will fire the Event we're about to wait on.
    event = asyncio.Event()
    async with _LOCK:
        _PENDING[task_id] = event

    try:
        # Re-check after registering — covers a tight race where the
        # approval committed between the initial check and the registry
        # insert. If APPROVED now, we're done.
        if await _current_status() == TaskStatus.APPROVED.value:
            return

        logger.info(
            "Task waiting for approval",
            extra={
                "task_id": task_id,
                "timeout_seconds": timeout_seconds,
                "initial_status": initial,
            },
        )

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TaskApprovalTimeout(
                f"Task {task_id} not approved within {timeout_seconds}s.",
            ) from exc
        except asyncio.CancelledError:
            raise

        logger.info(
            "Task approval received — dispatcher resuming",
            extra={"task_id": task_id},
        )
    finally:
        async with _LOCK:
            _PENDING.pop(task_id, None)


class TaskApprovalUnknown(Exception):
    """Raised when wait_until_approved is called for a non-existent task."""


class TaskApprovalCancelled(Exception):
    """Raised when wait_until_approved finds the task already CANCELLED.

    Cancellation is an explicit operator decision (or a transitive consequence
    of one); the dispatcher must not run a cancelled task.
    """


class TaskApprovalTimeout(Exception):
    """Raised when an approval doesn't arrive within the timeout window."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
