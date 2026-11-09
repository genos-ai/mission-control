"""Tests for the MissionRun model and its state machine (Plan 88 step 88.1.2)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import MissionRunStateError
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    VALID_RUN_TRANSITIONS,
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)

S = MissionRunStatus

# Contract 3.2.1, row by row (From -> To). Inserts are not transitions.
_CONTRACT_TABLE = [
    (S.PENDING, S.RUNNING),
    (S.PENDING, S.FAILED),
    (S.PENDING, S.CANCELLED),
    (S.RUNNING, S.AWAITING_GATE),
    (S.RUNNING, S.PAUSED),
    (S.RUNNING, S.SUCCEEDED),
    (S.RUNNING, S.FAILED),
    (S.RUNNING, S.BUDGET_STOPPED),
    (S.RUNNING, S.CANCELLED),
    (S.AWAITING_GATE, S.RUNNING),
    (S.AWAITING_GATE, S.PAUSED),
    (S.AWAITING_GATE, S.CANCELLED),
    (S.AWAITING_GATE, S.FAILED),
    (S.PAUSED, S.RUNNING),
    (S.PAUSED, S.CANCELLED),
    (S.PAUSED, S.FAILED),
]


def _run(status: MissionRunStatus) -> MissionRun:
    return MissionRun(
        mission_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        sequence=1,
        trigger=MissionRunTrigger.MANUAL,
        status=status,
    )


def test_valid_transitions_match_contract():
    expected: dict[MissionRunStatus, set[MissionRunStatus]] = {s: set() for s in S}
    for source, target in _CONTRACT_TABLE:
        expected[source].add(target)

    assert set(VALID_RUN_TRANSITIONS) == set(S)
    for source in S:
        assert VALID_RUN_TRANSITIONS[source] == frozenset(expected[source]), source


def test_status_sets():
    assert ACTIVE_RUN_STATUSES == {S.PENDING, S.RUNNING, S.AWAITING_GATE, S.PAUSED}
    assert TERMINAL_RUN_STATUSES == set(S) - ACTIVE_RUN_STATUSES
    for status in TERMINAL_RUN_STATUSES:
        assert VALID_RUN_TRANSITIONS[status] == frozenset()


def test_transition_rejects_running_to_pending():
    run = _run(S.RUNNING)

    with pytest.raises(MissionRunStateError):
        run.transition_status(S.PENDING, None, None)

    assert run.status is S.RUNNING


def test_transition_sets_started_and_ended_at():
    run = _run(S.PENDING)
    assert run.started_at is None and run.ended_at is None

    run.transition_status(S.RUNNING, None, None)
    assert run.started_at is not None
    assert run.started_at.tzinfo is not None
    assert run.ended_at is None

    run.transition_status(S.FAILED, MissionRunStatusReason.TASK_FAILURES, "2 tasks failed")
    assert run.ended_at is not None
    assert run.ended_at >= run.started_at
    assert run.status is S.FAILED
    assert run.status_reason is MissionRunStatusReason.TASK_FAILURES
    assert run.status_detail == "2 tasks failed"


@pytest.mark.asyncio
async def test_enum_stores_name(db_session: AsyncSession, test_user):
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="MissionRun storage test",
        owner_id=test_user.id,
    )
    db_session.add(mission)
    await db_session.flush()
    plan = MissionPlan(mission_id=mission.id, gate_mode=GateMode.MANUAL)
    db_session.add(plan)
    await db_session.flush()
    run = MissionRun(
        mission_id=mission.id,
        plan_id=plan.id,
        sequence=1,
        trigger=MissionRunTrigger.MANUAL,
    )
    db_session.add(run)
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT status, trigger FROM mission_runs WHERE id = :id"), {"id": run.id}
        )
    ).one()

    assert row.status == "PENDING"
    assert row.trigger == "MANUAL"
