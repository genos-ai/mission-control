"""claim_occurrence's budget rule (Plan 88 step 88.4.6, contract 3.3.2).

A breached monthly or lifetime cap records the tick as
SKIPPED/BUDGET_CAP_REACHED, pauses the mission inside the claim transaction
and returns a BUDGET_PAUSED notification. Real database, FakeScheduleGateway
and a patched claim clock; the ledger rows carry the real time, so they fall
in the current calendar month that BudgetService reads.
"""

from datetime import datetime, timedelta, timezone

import pytest

from modules.backend.events.mission_run_types import MissionLifecycleChangedEvent
from modules.backend.models.llm_call import LlmCall
from modules.backend.models.mission import Mission, MissionPauseReason, MissionStatus
from modules.backend.models.mission_plan import MissionPlan
from modules.backend.models.mission_run import MissionRunStatus, MissionRunStatusReason
from modules.backend.models.mission_schedule import MissionSchedule, MissionScheduleKind
from modules.backend.services.mission_schedule import MissionScheduleService
from modules.backend.services.mission_schedule_claim import BUDGET_PAUSED, RUN_SKIPPED
from tests.integration.backend.services.test_mission_schedule_service import (
    FakeScheduleGateway,
    RecordingBus,
)

UTC = timezone.utc
T = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture
def owner(committed_owner):
    return committed_owner


@pytest.fixture(autouse=True)
def _now(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.backend.services.mission_schedule_claim.utc_now",
        lambda: T + timedelta(seconds=10),
    )


async def _setup(factory, owner, *, spent: float, lifetime: float | None = None) -> tuple:
    user, mission, plan = await owner()
    async with factory() as session:
        if lifetime is not None:
            stored = await session.get(MissionPlan, plan.id)
            stored.budget_lifetime_usd = lifetime
        schedule = MissionSchedule(
            mission_id=mission.id,
            name="hourly",
            kind=MissionScheduleKind.OBJECTIVE,
            objective_template="Run {sequence}",
            cron_expression="0 * * * *",
            time_zone_name="UTC",
            catch_up_window_seconds=7200,
            last_claimed_scheduled_for=T - HOUR,
            created_by_user_id=user.id,
        )
        session.add(schedule)
        session.add(
            LlmCall(
                agent_name="test.agent",
                agent_role="worker",
                model="test-model",
                provider="test",
                input_tokens=1,
                output_tokens=1,
                cost_usd=spent,
                mission_id=mission.id,
                mission_run_id=None,
            )
        )
        await session.commit()
        return mission, schedule.id


async def test_monthly_breach_skips_and_pauses_and_returns_notification(
    db_session_factory, owner
) -> None:
    mission, schedule_id = await _setup(db_session_factory, owner, spent=100.0)
    bus = RecordingBus()

    async with db_session_factory() as session:
        claim = await MissionScheduleService(
            session, FakeScheduleGateway(interval=HOUR), bus
        ).claim_occurrence(schedule_id, T)

    assert claim.outcome == "skipped"
    assert claim.run.status == MissionRunStatus.SKIPPED
    assert claim.run.status_reason == MissionRunStatusReason.BUDGET_CAP_REACHED
    assert claim.run_input is None
    assert claim.mission_paused is True
    assert [n.kind for n in claim.notifications] == [RUN_SKIPPED, BUDGET_PAUSED]
    paused = claim.notifications[1]
    assert paused.mission_run_id is None
    assert paused.subject_id == f"{schedule_id}:{T.isoformat()}"
    assert paused.payload == {"cap": "budget_monthly_cap"}
    async with db_session_factory() as session:
        stored = await session.get(Mission, mission.id)
    assert stored.status == MissionStatus.PAUSED
    assert stored.paused_reason == MissionPauseReason.BUDGET_MONTHLY_CAP
    assert stored.paused_by_user_id is None
    (changed,) = [e for e in bus.events if isinstance(e, MissionLifecycleChangedEvent)]
    assert (changed.to_status, changed.paused_reason) == ("paused", "budget_monthly_cap")


async def test_lifetime_breach_pauses_with_lifetime_reason(db_session_factory, owner) -> None:
    mission, schedule_id = await _setup(db_session_factory, owner, spent=10.0, lifetime=10.0)

    async with db_session_factory() as session:
        claim = await MissionScheduleService(
            session, FakeScheduleGateway(interval=HOUR), RecordingBus()
        ).claim_occurrence(schedule_id, T)

    assert claim.run.status_reason == MissionRunStatusReason.BUDGET_CAP_REACHED
    assert claim.notifications[-1].payload == {"cap": "budget_lifetime_cap"}
    async with db_session_factory() as session:
        stored = await session.get(Mission, mission.id)
    assert stored.paused_reason == MissionPauseReason.BUDGET_LIFETIME_CAP


async def test_under_caps_runs(db_session_factory, owner) -> None:
    mission, schedule_id = await _setup(db_session_factory, owner, spent=99.0)

    async with db_session_factory() as session:
        claim = await MissionScheduleService(
            session, FakeScheduleGateway(interval=HOUR), RecordingBus()
        ).claim_occurrence(schedule_id, T)

    assert claim.outcome == "run"
    assert claim.mission_paused is False
    async with db_session_factory() as session:
        assert (await session.get(Mission, mission.id)).status == MissionStatus.ACTIVE
