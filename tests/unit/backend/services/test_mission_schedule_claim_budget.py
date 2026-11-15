"""The claim_occurrence activity syncs a budget-paused mission after the commit (Plan 88 88.4.6).

The claim's budget rule itself runs against the real database in
tests/integration/backend/services/test_mission_schedule_claim_budget.py.
Here the schedule service and session are fakes: the sync must see no open
transaction, so the Temporal schedule call never runs inside the claim's.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from modules.backend.schemas.mission_schedule import OccurrenceClaim
from modules.backend.temporal.mission_run_models import ClaimOccurrenceInput
from modules.backend.temporal.mission_schedule_activities import claim_occurrence

_MOD = "modules.backend.temporal.mission_schedule_activities"
MISSION_ID = str(uuid.uuid4())


class _Session:
    """Tracks whether a transaction is open: claim work opens one, commit closes it."""

    def __init__(self) -> None:
        self.open = False

    def in_transaction(self) -> bool:
        return self.open

    async def commit(self) -> None:
        self.open = False


async def _claim(*, paused: bool) -> AsyncMock:
    session = _Session()

    async def _claim_occurrence(schedule_id, scheduled_for):
        session.open = True  # the claim's reads and writes
        await session.commit()  # claim_occurrence commits before it returns
        session.open = True  # a later autobegin, closed by the activity's commit
        return OccurrenceClaim(
            outcome="skipped",
            run=SimpleNamespace(id=str(uuid.uuid4()), mission_id=MISSION_ID),
            run_input=None,
            notifications=[],
            mission_paused=paused,
        )

    in_transaction_at_sync: list[bool] = []

    async def _sync(mission_id):
        in_transaction_at_sync.append(session.in_transaction())

    svc = MagicMock(
        claim_occurrence=AsyncMock(side_effect=_claim_occurrence),
        sync_mission=AsyncMock(side_effect=_sync),
    )

    @asynccontextmanager
    async def _service():
        yield svc, session

    with patch(f"{_MOD}.schedule_service", _service):
        await ActivityEnvironment().run(
            claim_occurrence,
            ClaimOccurrenceInput(
                mission_schedule_id=str(uuid.uuid4()),
                scheduled_for=datetime(2027, 3, 1, 12, tzinfo=timezone.utc),
            ),
        )
    svc.in_transaction_at_sync = in_transaction_at_sync
    return svc


async def test_sync_called_after_commit_not_inside():
    svc = await _claim(paused=True)

    svc.sync_mission.assert_awaited_once_with(MISSION_ID)
    assert svc.in_transaction_at_sync == [False]


async def test_no_sync_when_the_claim_paused_nothing():
    svc = await _claim(paused=False)

    svc.sync_mission.assert_not_awaited()
