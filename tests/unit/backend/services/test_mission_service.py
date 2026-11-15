"""Tests for MissionService.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.models.mission import MissionMemberRole, MissionStatus
from modules.backend.models.notification import MissionNotificationRecipient
from modules.backend.models.user_channel_identity import ChannelKind
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.services import mission as mission_module
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
            gate_mode="manual",
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
            gate_mode="manual",
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
            gate_mode="manual",
            name="unique-name",
            description="First mission",
            owner_id=TEST_USER_ID,
        )
        with pytest.raises(ConflictError, match="already exists"):
            await service.create_mission(
                gate_mode="manual",
                name="unique-name",
                description="Second mission",
                owner_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_optional_fields(self, service):
        mission = await service.create_mission(
            gate_mode="manual",
            name="full-mission",
            description="With all fields",
            owner_id=TEST_USER_ID,
            team_id="team-alpha",
            default_roster="research",
            budget_per_run_usd=5.0,
            budget_per_month_usd=50.0,
            budget_lifetime_usd=500.0,
            repo_url="https://github.com/test/repo",
            repo_root="/home/test/repo",
        )
        assert mission.team_id == "team-alpha"
        assert mission.default_roster == "research"
        plan = await MissionPlanRepository(service.session).get_by_mission_id_required(mission.id)
        assert (
            plan.budget_per_run_usd,
            plan.budget_per_month_usd,
            plan.budget_lifetime_usd,
        ) == (5.0, 50.0, 500.0)
        assert mission.repo_url == "https://github.com/test/repo"
        assert mission.repo_root == "/home/test/repo"

    @pytest.mark.asyncio
    async def test_omitted_caps_take_configured_defaults(self, service):
        mission = await service.create_mission(
            gate_mode="manual",
            name="default-caps",
            description="Caps from missions.budgets",
            owner_id=TEST_USER_ID,
        )
        plan = await MissionPlanRepository(service.session).get_by_mission_id_required(mission.id)
        budgets = get_app_config().missions.budgets
        assert plan.budget_per_run_usd == budgets.default_per_run_usd
        assert plan.budget_per_month_usd == budgets.default_per_month_usd
        assert plan.budget_lifetime_usd is None

    @pytest.mark.asyncio
    async def test_invalid_caps_rejected_before_insert(self, service):
        with pytest.raises(ValidationError, match="per-month cap must be at least"):
            await service.create_mission(
                gate_mode="manual",
                name="bad-caps",
                description="Month below run",
                owner_id=TEST_USER_ID,
                budget_per_run_usd=10.0,
                budget_per_month_usd=5.0,
            )
        assert await service.get_mission_by_name("bad-caps") is None


async def _recipients(service: MissionService, mission_id: str) -> list:
    rows = await service.session.execute(
        select(MissionNotificationRecipient).where(
            MissionNotificationRecipient.mission_id == mission_id
        )
    )
    return list(rows.scalars().all())


class TestOwnerRecipient:
    @pytest.mark.asyncio
    async def test_create_mission_adds_owner_telegram_recipient(self, service):
        mission = await service.create_mission(
            gate_mode="manual",
            name="recipient-owner",
            description="Owner gets the default kinds",
            owner_id=TEST_USER_ID,
        )
        [recipient] = await _recipients(service, mission.id)
        assert recipient.user_id == TEST_USER_ID
        assert recipient.channel == ChannelKind.TELEGRAM
        assert recipient.kinds == list(get_app_config().notifications.default_kinds)

    @pytest.mark.asyncio
    async def test_create_mission_non_user_owner_no_recipient(self, service, monkeypatch):
        # A non-user owner already fails create_mission at the owner membership FK
        # (mission_members.user_id -> users), so the rule is exercised directly.
        mission = await service.create_mission(
            gate_mode="manual",
            name="recipient-non-user",
            description="Only the real owner is subscribed",
            owner_id=TEST_USER_ID,
        )
        fake_logger = MagicMock()
        monkeypatch.setattr(mission_module, "logger", fake_logger)

        for owner_id in ("cli-admin", str(uuid.uuid4())):
            await service._add_owner_recipient(mission.id, owner_id)
            fake_logger.warning.assert_called_with(
                "mission.recipient_skipped",
                extra={"mission_id": mission.id, "owner_id": owner_id},
            )
        assert [r.user_id for r in await _recipients(service, mission.id)] == [TEST_USER_ID]


class TestGetMission:
    @pytest.mark.asyncio
    async def test_get_by_id(self, service):
        created = await service.create_mission(
            gate_mode="manual",
            name="get-test",
            description="Get test",
            owner_id=TEST_USER_ID,
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
            gate_mode="manual",
            name="named-mission",
            description="Named",
            owner_id=TEST_USER_ID,
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
            gate_mode="manual",
            name="active-one",
            description="Active",
            owner_id=TEST_USER_ID,
        )
        await service.create_mission(
            gate_mode="manual",
            name="active-two",
            description="Active",
            owner_id=TEST_USER_ID,
        )
        missions = await service.list_missions()
        assert len(missions) >= 2

    @pytest.mark.asyncio
    async def test_list_by_owner(self, service):
        await service.create_mission(
            gate_mode="manual",
            name="owner-a",
            description="A",
            owner_id=TEST_USER_ID_2,
        )
        await service.create_mission(
            gate_mode="manual",
            name="owner-b",
            description="B",
            owner_id=TEST_USER_ID,
        )
        alice_missions = await service.list_missions(owner_id=TEST_USER_ID_2)
        assert all(m.owner_id == TEST_USER_ID_2 for m in alice_missions)


class TestUpdateMission:
    @pytest.mark.asyncio
    async def test_update_description(self, service):
        mission = await service.create_mission(
            gate_mode="manual",
            name="update-test",
            description="Original",
            owner_id=TEST_USER_ID,
        )
        updated = await service.update_mission(
            mission.id,
            description="Updated description",
        )
        assert updated.description == "Updated description"


class TestArchivedMissionListing:
    # Archiving itself is MissionLifecycleService.archive_mission (88.4.5).
    @pytest.mark.asyncio
    async def test_archived_not_in_active_list(self, service):
        mission = await service.create_mission(
            gate_mode="manual",
            name="archived-hidden",
            description="Hidden",
            owner_id=TEST_USER_ID,
        )
        await service.update_mission(mission.id, status=MissionStatus.ARCHIVED)
        active = await service.list_missions(owner_id=TEST_USER_ID, status="active")
        assert all(m.id != mission.id for m in active)
