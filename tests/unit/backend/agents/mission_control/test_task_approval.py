"""Unit tests for task_approval.py (Plan 80h, Plan 88.0.13a).

Covers the cross-process polling wait:
- already-approved fast path (no sleep)
- PROPOSED then APPROVED on a later poll returns (approval committed by
  "another process": the row the session factory returns changes, no
  in-process notification)
- CANCELLED raises TaskApprovalCancelled (initially and mid-wait)
- deadline raises TaskApprovalTimeout
- unknown task → TaskApprovalUnknown
- no process-local registry survives in the module

Test strategy: the session factory yields a stub session whose
``execute(...)`` returns whatever status the shared ``row`` dict holds at
that moment, which is what MissionPlanService.get_task reads.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from modules.backend.agents.mission_control import task_approval
from modules.backend.agents.mission_control.task_approval import (
    TaskApprovalCancelled,
    TaskApprovalTimeout,
    TaskApprovalUnknown,
    wait_until_approved,
)
from modules.backend.models.task import TaskStatus

_POLL = 1

# ── Test scaffolding ──────────────────────────────────────────────


def _row_factory(status: str | None):
    """Session factory backed by a mutable row; tests mutate ``row["status"]``."""
    row: dict[str, Any] = {"status": status, "reads": 0}

    @asynccontextmanager
    async def factory():
        yield _StubSession(row)

    return factory, row


class _StubSession:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    async def execute(self, _statement: Any) -> "_StubResult":
        self._row["reads"] += 1
        return _StubResult(self._row["status"])


class _StubResult:
    def __init__(self, value: str | None):
        self._value = value

    def scalar_one_or_none(self):
        if self._value is None:
            return None
        return SimpleNamespace(status=SimpleNamespace(value=self._value))


@pytest.fixture
def fast_sleep(monkeypatch):
    """Replace asyncio.sleep in the module so polls run without real delay.

    Each fake sleep advances a virtual clock used by the deadline check and
    runs an optional per-poll hook (the "other process" committing).
    """
    clock = {"now": 0.0, "hooks": []}
    real_sleep = asyncio.sleep

    async def _sleep(seconds: float) -> None:
        clock["now"] += seconds
        for hook in clock["hooks"]:
            hook(clock["now"])
        await real_sleep(0)

    class _Loop:
        def time(self) -> float:
            return clock["now"]

    # Patch the module's own ``asyncio`` reference only, so the event loop
    # and pytest-asyncio keep the real ``asyncio.sleep``/``get_running_loop``.
    fake_asyncio = SimpleNamespace(sleep=_sleep, get_running_loop=lambda: _Loop())
    monkeypatch.setattr(task_approval, "asyncio", fake_asyncio)
    return clock


async def _wait(factory, *, timeout_seconds: int = 30) -> None:
    await wait_until_approved(
        task_id="task-1",
        session_factory=factory,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=_POLL,
    )


# ── Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_already_approved_returns_immediately(fast_sleep):
    factory, row = _row_factory(TaskStatus.APPROVED.value)
    await _wait(factory)
    assert row["reads"] == 1
    assert fast_sleep["now"] == 0.0


@pytest.mark.asyncio
async def test_past_approval_status_returns_immediately(fast_sleep):
    factory, row = _row_factory(TaskStatus.RUNNING.value)
    await _wait(factory)
    assert row["reads"] == 1


@pytest.mark.asyncio
async def test_proposed_then_approved_on_later_poll(fast_sleep):
    """Approval committed elsewhere is seen on the next poll."""
    factory, row = _row_factory(TaskStatus.PROPOSED.value)

    def _approve_at_3s(now: float) -> None:
        if now >= 3:
            row["status"] = TaskStatus.APPROVED.value

    fast_sleep["hooks"].append(_approve_at_3s)
    await _wait(factory)
    assert fast_sleep["now"] == 3.0
    assert row["reads"] == 4  # initial read + three polls


@pytest.mark.asyncio
async def test_initially_cancelled_raises():
    factory, _row = _row_factory(TaskStatus.CANCELLED.value)
    with pytest.raises(TaskApprovalCancelled):
        await _wait(factory)


@pytest.mark.asyncio
async def test_cancelled_while_waiting_raises(fast_sleep):
    factory, row = _row_factory(TaskStatus.PROPOSED.value)

    def _cancel_at_2s(now: float) -> None:
        if now >= 2:
            row["status"] = TaskStatus.CANCELLED.value

    fast_sleep["hooks"].append(_cancel_at_2s)
    with pytest.raises(TaskApprovalCancelled):
        await _wait(factory)


@pytest.mark.asyncio
async def test_deadline_raises_task_approval_timeout(fast_sleep):
    factory, row = _row_factory(TaskStatus.PROPOSED.value)
    with pytest.raises(TaskApprovalTimeout):
        await _wait(factory, timeout_seconds=5)
    assert fast_sleep["now"] == 5.0
    assert row["reads"] == 6  # initial read + five polls


@pytest.mark.asyncio
async def test_unknown_task_id_raises_task_approval_unknown():
    factory, _row = _row_factory(None)
    with pytest.raises(TaskApprovalUnknown):
        await _wait(factory)


@pytest.mark.asyncio
async def test_real_poll_interval_wakes_waiter():
    """End-to-end with real sleeps: a concurrent status change wakes the waiter."""
    factory, row = _row_factory(TaskStatus.PROPOSED.value)
    waiter = asyncio.create_task(_wait(factory, timeout_seconds=10))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    row["status"] = TaskStatus.APPROVED.value
    await asyncio.wait_for(waiter, timeout=3)


def test_no_process_local_registry():
    """Plan 88.0.13a: the Event registry and its notifier are gone."""
    assert not hasattr(task_approval, "_PENDING")
    assert not hasattr(task_approval, "_LOCK")
    assert not hasattr(task_approval, "notify_approved")
