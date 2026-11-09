"""Unit tests for ManualGateReviewer (Plan 80g).

Covers:
- timeout path: no decision → reviewer returns ABORT and marks TIMED_OUT
- session_id round-trips into context_json
- opened / timeout event emission

The mocked tests patch the persistence methods and the wait so they need no
DB. The Plan 88 step 88.0.13 tests at the end run against the real database:
the decision is written through a separate session, as the API process does,
and the reviewer must see it by polling the row.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from modules.backend.agents.mission_control.gate_manual import ManualGateReviewer
from modules.backend.core import security
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.user import User
from modules.backend.schemas.gate import GateAction, GateContext
from modules.backend.services.mission_plan import MissionPlanService


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
    """A ManualGateReviewer whose persistence methods are no-op AsyncMocks.

    The wait is patched to time out at once; the DB tests below cover polling.
    """
    reviewer = ManualGateReviewer(
        session_factory=lambda: AsyncMock(),  # unused — methods are patched
        timeout_seconds=timeout,
        poll_interval_seconds=1,
    )
    reviewer._wait_for_decision = AsyncMock(side_effect=asyncio.TimeoutError)
    reviewer._persist_pending = AsyncMock()
    reviewer._persist_timeout = AsyncMock()
    reviewer._persist_cancelled = AsyncMock()
    return reviewer


# ── Tests ─────────────────────────────────────────────────────────


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


# ── Plan 88 step 88.0.13: cross-process wake via the gate row (real DB) ──


@pytest.fixture
async def committed_mission(db_session_factory):
    """A committed user and mission; the reviewer and the decider use separate sessions."""
    user = User(
        id=str(uuid.uuid4()),
        email=f"p88-gate-manual-{uuid.uuid4().hex[:8]}@test.dev",
        display_name="gate-manual",
        hashed_password=security.hash_password("gate-manual-password-123"),
        system_role="user",
        is_active=True,
    )
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"p88-gate-manual-{uuid.uuid4().hex[:8]}",
        description="Plan 88 manual gate test",
        owner_id=user.id,
        status=MissionStatus.ACTIVE,
    )
    async with db_session_factory() as session:
        session.add(user)
        await session.flush()
        session.add(mission)
        await session.flush()
        session.add(MissionPlan(mission_id=mission.id, gate_mode=GateMode.MANUAL))
        await session.commit()
    yield mission.id, user.id
    async with db_session_factory() as session:
        await session.delete(await session.get(Mission, mission.id))
        await session.delete(await session.get(User, user.id))
        await session.commit()


def _db_reviewer(db_session_factory) -> ManualGateReviewer:
    return ManualGateReviewer(
        session_factory=db_session_factory,
        timeout_seconds=5,
        poll_interval_seconds=1,
    )


async def _pending_request_id(db_session_factory, mission_id: str) -> str:
    for _ in range(100):
        async with db_session_factory() as session:
            rows = await MissionPlanService(session).list_pending_gate_requests([mission_id])
        if rows:
            return str(rows[0].id)
        await asyncio.sleep(0.05)
    raise AssertionError("reviewer never opened a gate request")


@pytest.mark.asyncio
async def test_review_returns_decision_written_by_another_session(
    db_session_factory, committed_mission
):
    mission_id, user_id = committed_mission
    reviewer = _db_reviewer(db_session_factory)

    async def _decide_from_another_session():
        request_id = await _pending_request_id(db_session_factory, mission_id)
        await asyncio.sleep(1)
        async with db_session_factory() as session:
            await MissionPlanService(session).record_gate_decision(
                request_id,
                decision={"action": "skip", "reason": "not needed", "reviewer": "user:test"},
                decided_by_user_id=user_id,
            )
            await session.commit()

    decider = asyncio.create_task(_decide_from_another_session())
    decision = await reviewer.review(GateContext(gate_type="pre_layer", mission_id=mission_id))
    await decider

    assert decision.action == GateAction.SKIP
    assert decision.reason == "not needed"
    assert decision.reviewer == "user:test"


@pytest.mark.asyncio
async def test_review_times_out_to_abort(db_session_factory, committed_mission):
    mission_id, _ = committed_mission
    reviewer = _db_reviewer(db_session_factory)

    decision = await reviewer.review(GateContext(gate_type="pre_layer", mission_id=mission_id))

    assert decision.action == GateAction.ABORT
    assert "timeout" in (decision.reason or "").lower()
    async with db_session_factory() as session:
        rows = (
            await session.execute(
                GateRequest.__table__.select().where(GateRequest.mission_id == mission_id)
            )
        ).all()
    assert [row.status for row in rows] == [GateRequestStatus.TIMED_OUT]
