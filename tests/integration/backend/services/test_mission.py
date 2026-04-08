"""Integration tests for MissionService — real database, no mocks."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import NotFoundError
from modules.backend.models.mission import Mission, MissionStatus
from modules.backend.models.user import User
from modules.backend.services.mission import MissionService


class TestCreateMission:
    async def test_create_basic_mission(
        self, db_session: AsyncSession, regular_user: User,
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            name="new-mission",
            description="A new test mission",
            owner_id=regular_user.id,
        )

        assert mission.id is not None
        assert mission.name == "new-mission"
        assert mission.description == "A new test mission"
        assert mission.owner_id == regular_user.id
        assert mission.status == MissionStatus.ACTIVE

    async def test_create_mission_with_all_fields(
        self, db_session: AsyncSession, regular_user: User,
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            name="full-mission",
            description="Mission with all fields",
            brief="Strategic brief for agents",
            owner_id=regular_user.id,
            default_roster="research",
            budget_ceiling_usd=50.0,
            repo_url="https://github.com/test/repo",
            tier="user",
        )

        assert mission.brief == "Strategic brief for agents"
        assert mission.default_roster == "research"
        assert mission.budget_ceiling_usd == 50.0
        assert mission.repo_url == "https://github.com/test/repo"


class TestGetMission:
    async def test_get_existing_mission(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        service = MissionService(db_session)
        result = await service.get_mission(test_mission.id)
        assert result.id == test_mission.id
        assert result.name == "test-mission"

    async def test_get_nonexistent_mission_raises(self, db_session: AsyncSession):
        service = MissionService(db_session)
        with pytest.raises(NotFoundError):
            await service.get_mission("nonexistent-id")


class TestResolveMission:
    async def test_resolve_by_id(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        service = MissionService(db_session)
        result = await service.resolve_mission(test_mission.id)
        assert result.id == test_mission.id

    async def test_resolve_by_name(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        service = MissionService(db_session)
        result = await service.resolve_mission("test-mission")
        assert result.id == test_mission.id

    async def test_resolve_nonexistent_raises(self, db_session: AsyncSession):
        service = MissionService(db_session)
        with pytest.raises(NotFoundError):
            await service.resolve_mission("no-such-mission")


class TestListMissions:
    async def test_list_all(
        self, db_session: AsyncSession, test_mission: Mission, archived_mission: Mission,
    ):
        service = MissionService(db_session)
        # list_missions with no owner_id returns active missions
        missions = await service.list_missions()
        active_ids = {m.id for m in missions}
        assert test_mission.id in active_ids
        # archived mission is not returned by list_active
        assert archived_mission.id not in active_ids

    async def test_list_by_owner(
        self, db_session: AsyncSession, regular_user: User, test_mission: Mission,
    ):
        service = MissionService(db_session)
        missions = await service.list_missions(owner_id=regular_user.id)
        assert any(m.id == test_mission.id for m in missions)


class TestUpdateMission:
    async def test_update_description(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        service = MissionService(db_session)
        updated = await service.update_mission(
            test_mission.id, description="Updated description",
        )
        assert updated.description == "Updated description"

    async def test_update_budget(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        service = MissionService(db_session)
        updated = await service.update_mission(
            test_mission.id, budget_ceiling_usd=100.0,
        )
        assert updated.budget_ceiling_usd == 100.0


class TestDeleteMission:
    async def test_delete_mission(
        self, db_session: AsyncSession, regular_user: User,
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            name="delete-me",
            description="Temporary mission",
            owner_id=regular_user.id,
        )
        mission_id = mission.id

        name = await service.delete_mission(mission_id)
        assert name == "delete-me"

        with pytest.raises(NotFoundError):
            await service.get_mission(mission_id)
