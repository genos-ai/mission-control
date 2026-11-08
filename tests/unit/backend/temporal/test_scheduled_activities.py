"""Tests for find_ready_plans (Plan 88 step 88.0.5): NULL gate_mode is not autonomous.

The activity's own session is replaced by the test's rolled-back db_session.
Assertions are scoped to the plan the test creates, because the shared
database may hold other ready plans.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.testing import ActivityEnvironment

from modules.backend.models.mission import Mission
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.temporal.scheduled_activities import find_ready_plans


async def _ready_plan_id(db_session: AsyncSession, owner_id: str, gate_mode: str | None) -> str:
    """Create an active mission whose plan has one APPROVED task; return the plan id."""
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for find_ready_plans",
        owner_id=owner_id,
        gate_mode=gate_mode,
        budget_ceiling_usd=10.0,
    )
    db_session.add(mission)
    await db_session.flush()
    plan = await MissionPlanService(db_session).get_or_create_plan(mission.id)
    await TaskRepository(db_session).create_task(
        plan_id=plan.id,
        mission_id=mission.id,
        agent="system.summarization.agent",
        description="Approved task",
        instructions="Do the thing",
        status=TaskStatus.APPROVED,
    )
    await db_session.flush()
    return plan.id


async def _find_ready_plan_ids(db_session: AsyncSession) -> set[str]:
    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("modules.backend.core.database.get_async_session", _session):
        plans = await ActivityEnvironment().run(find_ready_plans)
    return {p["plan_id"] for p in plans}


@pytest.mark.asyncio
async def test_find_ready_plans_excludes_null_gate_mode(db_session: AsyncSession, test_user):
    plan_id = await _ready_plan_id(db_session, test_user.id, gate_mode=None)

    assert plan_id not in await _find_ready_plan_ids(db_session)


@pytest.mark.asyncio
async def test_find_ready_plans_includes_autonomous(db_session: AsyncSession, test_user):
    plan_id = await _ready_plan_id(db_session, test_user.id, gate_mode="autonomous")

    assert plan_id in await _find_ready_plan_ids(db_session)
