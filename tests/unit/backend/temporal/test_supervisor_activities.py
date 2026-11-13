"""Tests for check_plan_active (Plan 88 step 88.4.2).

The activity runs against the real test database: get_async_session is bound
to the rolled-back db_session.
"""

from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.testing import ActivityEnvironment

from modules.backend.core.utils import utc_now
from modules.backend.models.mission import Mission, MissionPauseReason, MissionStatus
from modules.backend.temporal.supervisor_activities import check_plan_active
from tests.conftest import TEST_USER_ID

_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")


def _mid(tag: str) -> str:
    return str(uuid5(_TEST_NS, f"mission:check-plan-active-{tag}"))


async def _check(db_session: AsyncSession, mission_id: str) -> bool:
    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("modules.backend.core.database.get_async_session", _session):
        return await ActivityEnvironment().run(check_plan_active, mission_id)


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (MissionStatus.ACTIVE, None, True),
        (MissionStatus.PAUSED, MissionPauseReason.USER, False),
        (MissionStatus.ARCHIVED, None, False),
    ],
)
async def test_check_plan_active_reads_mission_status(
    test_user, db_session: AsyncSession, status, reason, expected
):
    mission_id = _mid(status.value)
    db_session.add(
        Mission(
            id=mission_id,
            name=f"cpa-{status.value}",
            description="test",
            owner_id=TEST_USER_ID,
            status=status,
            paused_reason=reason,
            paused_at=utc_now() if reason else None,
        )
    )
    await db_session.flush()

    assert await _check(db_session, mission_id) is expected
