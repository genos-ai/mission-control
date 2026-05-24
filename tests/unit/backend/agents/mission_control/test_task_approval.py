"""Unit tests for task_approval.py (Plan 80h).

Covers:
- already-approved fast path (no waiting, no registry entry)
- waiter registered → notify_approved fires the Event
- timeout returns TaskApprovalTimeout
- cancellation propagates without leaking registry entries
- unknown task → TaskApprovalUnknown
- notify_approved on unknown id is a logged no-op (single-process safety)
- multiple independent waiters

Test strategy: patch _current_status indirectly by stubbing the session
factory's execute. Each test stub controls what status comes back per
call, which is what the function under test cares about.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from modules.backend.agents.mission_control.task_approval import (
    TaskApprovalTimeout,
    TaskApprovalUnknown,
    _PENDING,
    notify_approved,
    wait_until_approved,
)
from modules.backend.models.task import TaskStatus


# ── Test scaffolding ──────────────────────────────────────────────


def _factory_returning(*statuses: str | None):
    """Return a session_factory whose successive `execute(...)` calls
    yield the given statuses (None means "row not found").

    Each call to `execute(...)` consumes one value from the sequence.
    Once exhausted, all further calls return the last value (so a single
    "APPROVED" handles tight-loop re-checks).
    """
    state = {"calls": 0, "values": list(statuses)}

    def _next_value():
        idx = min(state["calls"], len(state["values"]) - 1)
        state["calls"] += 1
        return state["values"][idx]

    @asynccontextmanager
    async def factory():
        session = _StubSession(_next_value)
        yield session

    return factory, state


class _StubSession:
    def __init__(self, next_value_fn) -> None:
        self._next = next_value_fn

    async def execute(self, _statement: Any) -> "_StubResult":
        return _StubResult(self._next())


class _StubResult:
    def __init__(self, value: str | None):
        self._value = value

    def scalar_one_or_none(self):
        if self._value is None:
            return None
        return SimpleNamespace(value=self._value)


@pytest.fixture(autouse=True)
def _clean_registry():
    _PENDING.clear()
    yield
    _PENDING.clear()


# ── Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_already_approved_returns_immediately():
    """Task already APPROVED → return without registering an Event."""
    factory, _state = _factory_returning(TaskStatus.APPROVED.value)
    await asyncio.wait_for(
        wait_until_approved(task_id="any", session_factory=factory, timeout_seconds=5),
        timeout=1.0,
    )
    assert _PENDING == {}


@pytest.mark.asyncio
async def test_proposed_waits_until_notify():
    """PROPOSED → block on Event → notify_approved wakes the waiter."""
    # Calls: initial check returns PROPOSED, after the wait re-check
    # returns APPROVED (status changed while we waited).
    factory, _state = _factory_returning(
        TaskStatus.PROPOSED.value, TaskStatus.PROPOSED.value, TaskStatus.APPROVED.value,
    )

    async def _approve_after_delay():
        for _ in range(50):
            if _PENDING:
                break
            await asyncio.sleep(0.01)
        task_id = next(iter(_PENDING.keys()))
        await notify_approved(task_id)

    approver = asyncio.create_task(_approve_after_delay())
    await wait_until_approved(task_id="abc", session_factory=factory, timeout_seconds=5)
    await approver

    assert _PENDING == {}


@pytest.mark.asyncio
async def test_timeout_raises_task_approval_timeout():
    """No notify within timeout → TaskApprovalTimeout."""
    factory, _state = _factory_returning(
        TaskStatus.PROPOSED.value, TaskStatus.PROPOSED.value,
    )
    with pytest.raises(TaskApprovalTimeout):
        await wait_until_approved(task_id="abc", session_factory=factory, timeout_seconds=1)
    assert _PENDING == {}


@pytest.mark.asyncio
async def test_cancellation_propagates_and_cleans_registry():
    """CancelledError propagates; registry cleaned in finally."""
    factory, _state = _factory_returning(
        TaskStatus.PROPOSED.value, TaskStatus.PROPOSED.value,
    )
    task = asyncio.create_task(
        wait_until_approved(task_id="abc", session_factory=factory, timeout_seconds=30),
    )
    for _ in range(50):
        if _PENDING:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _PENDING == {}


@pytest.mark.asyncio
async def test_unknown_task_id_raises_task_approval_unknown():
    """Row missing → TaskApprovalUnknown."""
    factory, _state = _factory_returning(None)
    with pytest.raises(TaskApprovalUnknown):
        await wait_until_approved(task_id="ghost", session_factory=factory, timeout_seconds=1)


@pytest.mark.asyncio
async def test_notify_approved_unknown_id_is_safe_noop():
    """notify_approved with no registered waiter must not raise."""
    await notify_approved("not-a-real-task-id")  # must not raise


@pytest.mark.asyncio
async def test_multiple_waiters_independent():
    """Two waiters keyed by different ids — notifying one doesn't wake the other."""
    factory, _state = _factory_returning(
        TaskStatus.PROPOSED.value,  # task_a initial
        TaskStatus.PROPOSED.value,  # task_a re-check
        TaskStatus.PROPOSED.value,  # task_b initial
        TaskStatus.PROPOSED.value,  # task_b re-check
        TaskStatus.APPROVED.value,  # task_a read-back after notify
    )

    async def _waiter(task_id: str) -> str:
        await wait_until_approved(
            task_id=task_id, session_factory=factory, timeout_seconds=5,
        )
        return task_id

    wa = asyncio.create_task(_waiter("task-a"))
    wb = asyncio.create_task(_waiter("task-b"))

    for _ in range(50):
        if len(_PENDING) >= 2:
            break
        await asyncio.sleep(0.01)
    assert len(_PENDING) == 2

    # Notify only task-a; task-b should remain blocked.
    await notify_approved("task-a")
    done, pending = await asyncio.wait({wa, wb}, timeout=1.0)
    assert wa in done
    assert wb in pending

    # Clean up task-b.
    wb.cancel()
    with pytest.raises(asyncio.CancelledError):
        await wb
