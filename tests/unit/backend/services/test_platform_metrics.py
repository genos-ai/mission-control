"""Tests for PlatformMetricsService."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.execution_record import (
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskExecution,
    TaskExecutionStatus,
)
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole, MissionStatus
from modules.backend.models.session import Session, SessionStatus
from modules.backend.services.platform_metrics import PlatformMetricsService
from tests.conftest import TEST_USER_ID


@pytest.fixture(autouse=True)
async def _ensure_test_user(test_user):
    pass


@pytest.fixture
def service(db_session: AsyncSession) -> PlatformMetricsService:
    return PlatformMetricsService(db_session)


async def _seed_mission(db: AsyncSession) -> Mission:
    m = Mission(
        name="metrics-test",
        description="For metrics tests",
        owner_id=TEST_USER_ID,
        status=MissionStatus.ACTIVE,
        default_roster="default",
    )
    db.add(m)
    await db.flush()
    member = MissionMember(
        mission_id=m.id,
        user_id=TEST_USER_ID,
        role=MissionMemberRole.OWNER,
    )
    db.add(member)
    await db.flush()
    return m


async def _seed_session(db: AsyncSession) -> Session:
    s = Session(status=SessionStatus.ACTIVE)
    db.add(s)
    await db.flush()
    return s


async def _seed_execution_record(
    db: AsyncSession,
    mission_id: str,
    session_id: str,
    *,
    cost: float = 0.01,
    status: ExecutionRecordStatus = ExecutionRecordStatus.COMPLETED,
) -> ExecutionRecord:
    er = ExecutionRecord(
        mission_id=mission_id,
        session_id=session_id,
        status=status,
        roster_name="default",
        objective_category="code",
        total_cost_usd=cost,
    )
    db.add(er)
    await db.flush()
    return er


async def _seed_task_execution(
    db: AsyncSession,
    execution_record_id: str,
    *,
    agent_name: str = "test.agent",
    cost: float = 0.005,
    duration: float = 1.5,
) -> TaskExecution:
    te = TaskExecution(
        execution_record_id=execution_record_id,
        # task_id is a native UUID column (Plan 72) — must be a real UUID.
        task_id=str(uuid.uuid4()),
        agent_name=agent_name,
        status=TaskExecutionStatus.COMPLETED,
        cost_usd=cost,
        duration_seconds=duration,
    )
    db.add(te)
    await db.flush()
    return te


class TestGetOverview:
    @pytest.mark.asyncio
    async def test_empty_db_returns_zeros(self, service):
        overview = await service.get_overview()
        assert overview["counts"]["missions"] == 0
        assert overview["counts"]["sessions"] == 0
        assert overview["total_cost_usd"] == 0.0
        assert "generated_at" in overview

    @pytest.mark.asyncio
    async def test_with_data(self, service, db_session):
        mission = await _seed_mission(db_session)
        session = await _seed_session(db_session)
        await _seed_execution_record(db_session, mission.id, session.id, cost=1.50)
        await _seed_execution_record(db_session, mission.id, session.id, cost=0.50)

        overview = await service.get_overview()
        assert overview["counts"]["missions"] == 1
        assert overview["counts"]["sessions"] == 1
        assert overview["counts"]["execution_records"] == 2
        assert abs(overview["total_cost_usd"] - 2.0) < 0.001


class TestGetCostSummary:
    @pytest.mark.asyncio
    async def test_cost_by_agent(self, service, db_session):
        mission = await _seed_mission(db_session)
        session = await _seed_session(db_session)
        er = await _seed_execution_record(db_session, mission.id, session.id)
        await _seed_task_execution(db_session, er.id, agent_name="agent.a", cost=0.10)
        await _seed_task_execution(db_session, er.id, agent_name="agent.b", cost=0.20)

        costs = await service.get_cost_summary()
        assert len(costs["by_agent"]) == 2
        names = [a["agent_name"] for a in costs["by_agent"]]
        assert "agent.a" in names
        assert "agent.b" in names

    @pytest.mark.asyncio
    async def test_cost_by_status(self, service, db_session):
        mission = await _seed_mission(db_session)
        session = await _seed_session(db_session)
        await _seed_execution_record(
            db_session, mission.id, session.id, status=ExecutionRecordStatus.COMPLETED, cost=1.0
        )
        await _seed_execution_record(
            db_session, mission.id, session.id, status=ExecutionRecordStatus.FAILED, cost=0.5
        )

        costs = await service.get_cost_summary()
        statuses = {s["status"] for s in costs["by_status"]}
        assert "completed" in statuses
        assert "failed" in statuses


class TestGetAgentUtilisation:
    @pytest.mark.asyncio
    async def test_utilisation_stats(self, service, db_session):
        mission = await _seed_mission(db_session)
        session = await _seed_session(db_session)
        er = await _seed_execution_record(db_session, mission.id, session.id)
        await _seed_task_execution(db_session, er.id, agent_name="agent.x", cost=0.10, duration=2.0)
        await _seed_task_execution(db_session, er.id, agent_name="agent.x", cost=0.20, duration=3.0)

        utilisation = await service.get_agent_utilisation()
        assert len(utilisation) == 1
        assert utilisation[0]["agent_name"] == "agent.x"
        assert utilisation[0]["total_runs"] == 2
        assert abs(utilisation[0]["total_cost_usd"] - 0.30) < 0.001


class TestGetRecentActivity:
    @pytest.mark.asyncio
    async def test_recent_executions(self, service, db_session):
        mission = await _seed_mission(db_session)
        session = await _seed_session(db_session)
        await _seed_execution_record(db_session, mission.id, session.id)

        activity = await service.get_recent_activity(limit=5)
        assert len(activity["recent_executions"]) == 1
        assert "recent_workflow_runs" in activity
