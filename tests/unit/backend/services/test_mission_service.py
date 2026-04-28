"""Tests for MissionService.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.models.mission import MissionMemberRole, MissionStatus
from modules.backend.services.mission import MissionService
from tests.conftest import TEST_USER_ID, TEST_USER_ID_2


@pytest.fixture(autouse=True)
async def _ensure_test_users(test_user, test_user_2):
    """Ensure test users exist — missions FK to users via MissionMember."""


@pytest.fixture
def service(db_session: AsyncSession) -> MissionService:
    return MissionService(db_session)


class TestCreateMission:
    @pytest.mark.asyncio
    async def test_creates_mission(self, service):
        mission = await service.create_mission(
            name="test-mission",
            description="A test mission",
            owner_id=TEST_USER_ID,
        )
        assert mission.id is not None
        assert mission.name == "test-mission"
        assert mission.description == "A test mission"
        assert mission.owner_id == TEST_USER_ID
        assert mission.status == MissionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_creates_owner_membership(self, service):
        mission = await service.create_mission(
            name="test-membership",
            description="Test membership creation",
            owner_id=TEST_USER_ID,
        )
        members = await service._member_repo.get_members(mission.id)
        assert len(members) == 1
        assert members[0].user_id == TEST_USER_ID
        assert members[0].role == MissionMemberRole.OWNER

    @pytest.mark.asyncio
    async def test_duplicate_name_raises_conflict(self, service):
        await service.create_mission(
            name="unique-name",
            description="First mission",
            owner_id=TEST_USER_ID,
        )
        with pytest.raises(ConflictError, match="already exists"):
            await service.create_mission(
                name="unique-name",
                description="Second mission",
                owner_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_optional_fields(self, service):
        mission = await service.create_mission(
            name="full-mission",
            description="With all fields",
            owner_id=TEST_USER_ID,
            team_id="team-alpha",
            default_roster="research",
            budget_ceiling_usd=50.0,
            repo_url="https://github.com/test/repo",
            repo_root="/home/test/repo",
        )
        assert mission.team_id == "team-alpha"
        assert mission.default_roster == "research"
        assert mission.budget_ceiling_usd == 50.0
        assert mission.repo_url == "https://github.com/test/repo"
        assert mission.repo_root == "/home/test/repo"


class TestGetMission:
    @pytest.mark.asyncio
    async def test_get_by_id(self, service):
        created = await service.create_mission(
            name="get-test", description="Get test", owner_id=TEST_USER_ID,
        )
        result = await service.get_mission(created.id)
        assert result.name == "get-test"

    @pytest.mark.asyncio
    async def test_get_not_found_raises(self, service):
        with pytest.raises(NotFoundError):
            await service.get_mission("00000000-0000-0000-0000-000000000000")

    @pytest.mark.asyncio
    async def test_get_by_name(self, service):
        await service.create_mission(
            name="named-mission", description="Named", owner_id=TEST_USER_ID,
        )
        result = await service.get_mission_by_name("named-mission")
        assert result is not None
        assert result.name == "named-mission"

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, service):
        result = await service.get_mission_by_name("no-such-mission")
        assert result is None


class TestListMissions:
    @pytest.mark.asyncio
    async def test_list_active(self, service):
        await service.create_mission(
            name="active-one", description="Active", owner_id=TEST_USER_ID,
        )
        await service.create_mission(
            name="active-two", description="Active", owner_id=TEST_USER_ID,
        )
        missions = await service.list_missions()
        assert len(missions) >= 2

    @pytest.mark.asyncio
    async def test_list_by_owner(self, service):
        await service.create_mission(
            name="owner-a", description="A", owner_id=TEST_USER_ID_2,
        )
        await service.create_mission(
            name="owner-b", description="B", owner_id=TEST_USER_ID,
        )
        alice_missions = await service.list_missions(owner_id=TEST_USER_ID_2)
        assert all(m.owner_id == TEST_USER_ID_2 for m in alice_missions)


class TestUpdateMission:
    @pytest.mark.asyncio
    async def test_update_description(self, service):
        mission = await service.create_mission(
            name="update-test", description="Original", owner_id=TEST_USER_ID,
        )
        updated = await service.update_mission(
            mission.id, description="Updated description",
        )
        assert updated.description == "Updated description"


class TestArchiveMission:
    @pytest.mark.asyncio
    async def test_archive(self, service):
        mission = await service.create_mission(
            name="archive-test", description="To archive", owner_id=TEST_USER_ID,
        )
        archived = await service.archive_mission(mission.id)
        assert archived.status == MissionStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_archived_not_in_active_list(self, service):
        mission = await service.create_mission(
            name="archived-hidden", description="Hidden", owner_id=TEST_USER_ID,
        )
        await service.archive_mission(mission.id)
        active = await service.list_missions(owner_id=TEST_USER_ID, status="active")
        assert all(m.id != mission.id for m in active)
