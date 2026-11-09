"""Tests for the MissionSchedule model (Plan 88 step 88.1.3)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission
from modules.backend.models.mission_schedule import (
    MissionSchedule,
    MissionScheduleKind,
)


@pytest.mark.asyncio
async def test_temporal_schedule_id_set_at_insert(db_session: AsyncSession, test_user):
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="MissionSchedule storage test",
        owner_id=test_user.id,
    )
    db_session.add(mission)
    await db_session.flush()
    schedule = MissionSchedule(
        mission_id=mission.id,
        name="daily",
        kind=MissionScheduleKind.OBJECTIVE,
        objective_template="Report for {scheduled_for}",
        cron_expression="0 9 * * *",
        time_zone_name="Europe/London",
        catch_up_window_seconds=3600,
        created_by_user_id=test_user.id,
    )
    db_session.add(schedule)
    await db_session.flush()

    row = (
        await db_session.execute(
            text(
                "SELECT temporal_schedule_id, kind, status, temporal_sync_state "
                "FROM mission_schedules WHERE id = :id"
            ),
            {"id": schedule.id},
        )
    ).one()

    assert row.temporal_schedule_id == f"mission-schedule-{schedule.id}"
    assert row.temporal_schedule_id == schedule.temporal_id
    assert row.kind == "OBJECTIVE"
    assert row.status == "ACTIVE"
    assert row.temporal_sync_state == "PENDING"
