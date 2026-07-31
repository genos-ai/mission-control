"""Unit tests for ManualGateReviewer (Plan 80g).

Covers:
- happy path: client decides → reviewer returns the GateDecision
- timeout path: no decision → reviewer returns ABORT and marks TIMED_OUT
- cancellation path: coroutine cancelled mid-wait → row marked CANCELLED
- session_id round-trips into context_json
- fire_decision on unknown id is a logged no-op (multi-worker safety)
- registry cleanup after decision

Test strategy: patch ManualGateReviewer's persistence methods so we
don't need a real DB. The asyncio.Event behaviour is what matters.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from modules.backend.agents.mission_control.gate_manual import (
    _PENDING,
    ManualGateReviewer,
    fire_decision,
)
from modules.backend.schemas.gate import GateAction, GateContext, GateDecision


def _context(
    gate_type: str = "pre_layer",
    session_id: str | None = None,
) -> GateContext:
    return GateContext(
        gate_type=gate_type,
        mission_id=str(uuid.uuid4()),
        session_id=session_id,
    )


def _make_reviewer(*, timeout: int = 5) -> ManualGateReviewer:
    """A ManualGateReviewer whose persistence methods are no-op AsyncMocks."""
    reviewer = ManualGateReviewer(
        session_factory=lambda: AsyncMock(),  # unused — methods are patched
        timeout_seconds=timeout,
    )
    reviewer._persist_pending = AsyncMock()
    reviewer._persist_timeout = AsyncMock()
    reviewer._persist_cancelled = AsyncMock()
    return reviewer


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure no leaked Events between tests."""
    _PENDING.clear()
    yield
    _PENDING.clear()


# ── Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_client_decision():
    """fire_decision wakes the reviewer; it reads the persisted decision back."""
    reviewer = _make_reviewer(timeout=5)
    expected = GateDecision(
        action=GateAction.CONTINUE,
        reason="looks good",
        reviewer="user:test",
    )
    reviewer._read_decision = AsyncMock(return_value=expected)

    async def _decide_after_short_delay():
        for _ in range(50):
            if _PENDING:
                break
            await asyncio.sleep(0.01)
        request_id = next(iter(_PENDING.keys()))
        await fire_decision(request_id)

    decision_task = asyncio.create_task(_decide_after_short_delay())
    decision = await reviewer.review(_context())
    await decision_task

    assert decision.action == GateAction.CONTINUE
    assert decision.reason == "looks good"
    assert decision.reviewer == "user:test"
    reviewer._persist_pending.assert_awaited_once()
    reviewer._read_decision.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_returns_abort_and_marks_row():
    """No decision within timeout → ABORT + status TIMED_OUT."""
    reviewer = _make_reviewer(timeout=1)
    decision = await reviewer.review(_context())

    assert decision.action == GateAction.ABORT
    assert "timeout" in (decision.reason or "").lower()
    reviewer._persist_timeout.assert_awaited_once()
    reviewer._persist_cancelled.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_marks_row_and_propagates():
    """CancelledError → row marked CANCELLED + exception propagates."""
    reviewer = _make_reviewer(timeout=30)

    task = asyncio.create_task(reviewer.review(_context()))
    for _ in range(50):
        if _PENDING:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    reviewer._persist_cancelled.assert_awaited_once()
    reviewer._persist_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_id_passed_through_to_persist():
    """Context.session_id flows into the row persist call."""
    reviewer = _make_reviewer(timeout=1)
    expected_session = str(uuid.uuid4())
    await reviewer.review(_context(session_id=expected_session))
    persist_call = reviewer._persist_pending.await_args
    # _persist_pending(request_id, context) — context is second positional arg
    persisted_context = persist_call.args[1]
    assert persisted_context.session_id == expected_session


@pytest.mark.asyncio
async def test_fire_decision_unknown_id_is_safe_noop():
    """fire_decision on an unknown id must not raise (multi-worker safety)."""
    # If the dispatcher coroutine isn't in this process, _PENDING has no
    # Event for that id — the call should be silent, not crash.
    await fire_decision("not-a-real-request-id")  # must not raise


@pytest.mark.asyncio
async def test_registry_cleaned_up_after_decision():
    """Reviewer must pop its Event from _PENDING after returning."""
    reviewer = _make_reviewer(timeout=5)
    reviewer._read_decision = AsyncMock(
        return_value=GateDecision(
            action=GateAction.ABORT,
            reason="x",
            reviewer="u",
        )
    )

    async def _decide():
        for _ in range(50):
            if _PENDING:
                break
            await asyncio.sleep(0.01)
        request_id = next(iter(_PENDING.keys()))
        await fire_decision(request_id)

    t = asyncio.create_task(_decide())
    await reviewer.review(_context())
    await t

    assert _PENDING == {}, "Registry leaked an Event"


@pytest.mark.asyncio
async def test_opened_event_emitted_when_event_bus_provided():
    """If event_bus is passed, _emit_opened publishes GateRequestOpenedEvent.

    With timeout_seconds=1 and no decision ever fired, review() also hits
    the timeout path, which publishes a second, error-level SystemEvent —
    so the bus sees two publishes: opened, then timeout.
    """
    bus = AsyncMock()
    reviewer = _make_reviewer(timeout=1)
    reviewer._event_bus = bus
    await reviewer.review(_context())
    assert bus.publish.await_count == 2
    opened_event = bus.publish.await_args_list[0].args[0]
    assert opened_event.event_type == "gate.request.opened"
    timeout_event = bus.publish.await_args_list[1].args[0]
    assert timeout_event.level == "error"


@pytest.mark.asyncio
async def test_no_event_emission_when_event_bus_none():
    """No bus → no emit attempted (silently)."""
    reviewer = _make_reviewer(timeout=1)
    # reviewer._event_bus already None — exercise the path
    await reviewer.review(_context())
    # No assertion needed — just verifying no AttributeError
