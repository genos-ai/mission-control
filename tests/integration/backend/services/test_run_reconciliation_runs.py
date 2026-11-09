"""Mission-run reconciliation over committed rows (Plan 88 step 88.1.10a, contract 3.5.1).

The reconciler clock is frozen in 2001 and the test run is backdated against
it, so the dev database's own active rows (all newer than the cutoff) are
never candidates.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
)
from modules.backend.services.run_reconciliation import RunReconciliationService
from modules.backend.temporal.workflow_gateway import WorkflowState
from tests.integration.backend.services.test_claim_occurrence import (
    CLAIM_MODULE,
    HOUR,
    T,
    _claim,
    _runs,
    _schedule,
)
from tests.integration.backend.services.test_mission_schedule_service import (
    FakeScheduleGateway,
    RecordingBus,
)

RECONCILER_NOW = datetime(2001, 1, 1, tzinfo=timezone.utc)
GRACE = 600


@pytest.fixture
def schedule_gateway() -> FakeScheduleGateway:
    return FakeScheduleGateway(interval=HOUR)


@pytest.fixture
def set_claim_now(monkeypatch):
    def apply(now: datetime) -> None:
        monkeypatch.setattr(f"{CLAIM_MODULE}.utc_now", lambda: now)

    apply(T + timedelta(seconds=10))
    return apply


class NotFoundGateway:
    """Every workflow id resolves NOT_FOUND."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def state(self, workflow_id: str) -> WorkflowState:
        self.calls.append(workflow_id)
        return WorkflowState.NOT_FOUND


async def test_pending_run_without_workflow_failed_after_grace_and_next_tick_runs(
    db_session_factory, schedule_gateway, committed_owner, set_claim_now, monkeypatch
) -> None:
    user, mission, _plan = await committed_owner()
    schedule_id = await _schedule(db_session_factory, user, mission, watermark=T - HOUR)

    first = await _claim(db_session_factory, schedule_gateway, schedule_id, T)
    assert first.outcome == "run"
    run_id = first.run.id
    async with db_session_factory() as session:
        await session.execute(
            update(MissionRun)
            .where(MissionRun.id == run_id)
            .values(updated_at=RECONCILER_NOW - timedelta(seconds=700))
        )
        await session.commit()

    monkeypatch.setattr(
        "modules.backend.services.run_reconciliation.utc_now", lambda: RECONCILER_NOW
    )
    workflow_gateway = NotFoundGateway()
    async with db_session_factory() as session:
        stats = await RunReconciliationService(
            session, workflow_gateway, RecordingBus()  # type: ignore[arg-type]
        ).reconcile(GRACE)

    assert workflow_gateway.calls == [first.run.temporal_workflow_id]
    assert stats.examined_mission_runs == 1
    assert stats.failed_mission_runs == 1
    (failed,) = await _runs(db_session_factory, mission.id)
    assert failed.status == MissionRunStatus.FAILED
    assert failed.status_reason == MissionRunStatusReason.ORPHANED_WORKFLOW_NOT_FOUND

    set_claim_now(T + HOUR + timedelta(seconds=10))
    second = await _claim(db_session_factory, schedule_gateway, schedule_id, T + HOUR)

    assert second.outcome == "run"
    assert second.run.status == MissionRunStatus.PENDING
