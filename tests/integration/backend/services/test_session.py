"""Integration tests for SessionService — real database, no mocks."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import BudgetExceededError, NotFoundError
from modules.backend.models.mission import Mission
from modules.backend.models.session import SessionStatus
from modules.backend.models.user import User
from modules.backend.schemas.session import SessionCreate
from modules.backend.services.session import SessionService


class TestCreateSession:
    async def test_create_basic_session(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
        regular_user: User,
    ):
        service = SessionService(db_session)
        data = SessionCreate(mission_id=test_mission.id)
        session = await service.create_session(data, user_id=regular_user.id)

        assert session.id is not None
        assert session.status == SessionStatus.ACTIVE.value
        assert session.mission_id == test_mission.id
        assert session.user_id == regular_user.id
        assert session.expires_at is not None

    async def test_create_session_with_goal(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        data = SessionCreate(
            mission_id=test_mission.id,
            goal="Investigate production bug",
            agent_id="mission.director",
        )
        session = await service.create_session(data)

        assert session.goal == "Investigate production bug"
        assert session.agent_id == "mission.director"

    async def test_create_session_with_cost_budget(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        data = SessionCreate(
            mission_id=test_mission.id,
            cost_budget_usd=5.0,
        )
        session = await service.create_session(data)

        assert session.cost_budget_usd is not None
        assert session.cost_budget_usd <= 5.0


class TestGetSession:
    async def test_get_existing_session(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        created = await service.create_session(
            SessionCreate(mission_id=test_mission.id),
        )

        fetched = await service.get_session(created.id)
        assert fetched.id == created.id

    async def test_get_nonexistent_session_raises(self, db_session: AsyncSession):
        service = SessionService(db_session)
        with pytest.raises(NotFoundError):
            await service.get_session("00000000-0000-0000-0000-000000000000")


class TestEnsureSession:
    async def test_returns_existing_session_id(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        created = await service.create_session(
            SessionCreate(mission_id=test_mission.id),
        )

        result_id = await service.ensure_session(created.id)
        assert result_id == created.id

    async def test_creates_new_session_when_none(self, db_session: AsyncSession):
        service = SessionService(db_session)
        result_id = await service.ensure_session(
            None,
            agent_id="mission.director",
            goal="auto-created",
        )

        assert result_id is not None
        # Verify the session actually exists
        session = await service.get_session(result_id)
        assert session.goal == "auto-created"


class TestCostTracking:
    async def test_update_cost(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        session = await service.create_session(
            SessionCreate(mission_id=test_mission.id),
        )

        await service.update_cost(
            session.id,
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
        )

        updated = await service.get_session(session.id)
        assert updated.total_input_tokens == 1000
        assert updated.total_output_tokens == 500
        assert updated.total_cost_usd == pytest.approx(0.05, abs=1e-6)

    async def test_cost_accumulates(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        session = await service.create_session(
            SessionCreate(mission_id=test_mission.id),
        )

        await service.update_cost(session.id, input_tokens=100, output_tokens=50, cost_usd=0.01)
        await service.update_cost(session.id, input_tokens=200, output_tokens=100, cost_usd=0.02)

        updated = await service.get_session(session.id)
        assert updated.total_input_tokens == 300
        assert updated.total_output_tokens == 150
        assert updated.total_cost_usd == pytest.approx(0.03, abs=1e-6)

    async def test_enforce_budget_raises_when_exceeded(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        session = await service.create_session(
            SessionCreate(mission_id=test_mission.id, cost_budget_usd=0.10),
        )

        # Push cost over budget
        await service.update_cost(session.id, input_tokens=5000, output_tokens=2000, cost_usd=0.15)

        with pytest.raises(BudgetExceededError):
            await service.enforce_budget(session.id)


class TestListSessions:
    async def test_list_by_mission(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = SessionService(db_session)
        await service.create_session(SessionCreate(mission_id=test_mission.id))
        await service.create_session(SessionCreate(mission_id=test_mission.id))

        sessions, total = await service.list_sessions(mission_id=test_mission.id)
        assert len(sessions) >= 2
        assert total >= 2

    async def test_list_by_user(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
        regular_user: User,
    ):
        service = SessionService(db_session)
        await service.create_session(
            SessionCreate(mission_id=test_mission.id),
            user_id=regular_user.id,
        )

        sessions, total = await service.list_sessions(user_id=regular_user.id)
        assert len(sessions) >= 1
        assert total >= 1
        assert all(s.user_id == regular_user.id for s in sessions)
