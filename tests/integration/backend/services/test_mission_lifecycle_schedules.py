"""Mission pause slots across resume and the next claim (Plan 88 step 88.4.5, contract 3.2.2).

Real database, FakeScheduleGateway on an hourly grid, a mocked workflow
gateway and patched clocks in the lifecycle and claim modules.
"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from modules.backend.models.mission import MissionPauseReason
from modules.backend.models.mission_run import MissionRunStatus, MissionRunStatusReason
from modules.backend.services.mission_lifecycle import MissionLifecycleService
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from tests.integration.backend.services.test_claim_occurrence import (
    HOUR,
    T,
    _claim,
    _runs,
    _schedule,
    _schedule_row,
)
from tests.integration.backend.services.test_mission_schedule_service import (
    FakeScheduleGateway,
    RecordingBus,
)

LIFECYCLE_MODULE = "modules.backend.services.mission_lifecycle"
CLAIM_MODULE = "modules.backend.services.mission_schedule_claim"


@pytest.fixture
def gateway(monkeypatch) -> FakeScheduleGateway:
    fake = FakeScheduleGateway(interval=HOUR)
    monkeypatch.setattr(TemporalScheduleGateway, "create", AsyncMock(return_value=fake))
    workflows = AsyncMock()
    workflows.signal.return_value = WorkflowState.NOT_FOUND
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=workflows))
    return fake


@pytest.fixture
def owner(committed_owner):
    return committed_owner


async def test_mission_pause_slots_backfilled(
    db_session_factory, gateway, owner, monkeypatch
) -> None:
    user, mission, _ = await owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T)

    monkeypatch.setattr(f"{LIFECYCLE_MODULE}.utc_now", lambda: T)
    async with db_session_factory() as session:
        await MissionLifecycleService(session, RecordingBus()).pause_mission(
            mission.id, reason=MissionPauseReason.USER, user_id=user.id
        )

    resumed_at = T + 5 * HOUR
    monkeypatch.setattr(f"{LIFECYCLE_MODULE}.utc_now", lambda: resumed_at)
    async with db_session_factory() as session:
        await MissionLifecycleService(session, RecordingBus()).resume_mission(mission.id, user.id)

    missed = await _runs(db_session_factory, mission.id)
    assert [r.scheduled_for for r in missed] == [T + i * HOUR for i in range(1, 6)]
    assert {(r.status, r.status_reason) for r in missed} == {
        (MissionRunStatus.MISSED, MissionRunStatusReason.NOT_FIRED)
    }
    assert [r.sequence for r in missed] == [1, 2, 3, 4, 5]
    assert (await _schedule_row(db_session_factory, schedule_id)).last_claimed_scheduled_for == (
        resumed_at
    )

    tick = T + 6 * HOUR
    monkeypatch.setattr(f"{CLAIM_MODULE}.utc_now", lambda: tick + timedelta(seconds=10))
    claim = await _claim(db_session_factory, gateway, schedule_id, tick)

    assert claim.outcome == "run"
    runs = await _runs(db_session_factory, mission.id)
    assert len(runs) == 6
    assert sum(1 for r in runs if r.status == MissionRunStatus.MISSED) == 5
    assert runs[-1].scheduled_for == tick
    assert runs[-1].status == MissionRunStatus.PENDING
