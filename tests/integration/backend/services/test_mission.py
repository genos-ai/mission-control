"""Integration tests for MissionService — real database, no mocks."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import security
from modules.backend.core.exceptions import ExternalServiceError, NotFoundError
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole, MissionStatus
from modules.backend.models.mission_run import MissionRun, MissionRunStatus, MissionRunTrigger
from modules.backend.models.user import User
from modules.backend.repositories.mission import MissionRepository
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.temporal.workflow_gateway import WorkflowState
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

_NS = UUID("00000000-0000-0000-0000-000000000000")
_CONNECT = "modules.backend.temporal.workflow_gateway.TemporalWorkflowGateway.connect"


class TestCreateMission:
    async def test_create_basic_mission(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            gate_mode="manual",
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
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            gate_mode="manual",
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
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = MissionService(db_session)
        result = await service.get_mission(test_mission.id)
        assert result.id == test_mission.id
        assert result.name == "test-mission"

    async def test_get_nonexistent_mission_raises(self, db_session: AsyncSession):
        service = MissionService(db_session)
        with pytest.raises(NotFoundError):
            await service.get_mission("00000000-0000-0000-0000-000000000000")


class TestResolveMission:
    async def test_resolve_by_id(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = MissionService(db_session)
        result = await service.resolve_mission(test_mission.id)
        assert result.id == test_mission.id

    async def test_resolve_by_name(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = MissionService(db_session)
        result = await service.resolve_mission("test-mission")
        assert result.id == test_mission.id

    async def test_resolve_nonexistent_raises(self, db_session: AsyncSession):
        service = MissionService(db_session)
        with pytest.raises(NotFoundError):
            await service.resolve_mission("00000000-0000-0000-0000-ffffffffffff")


class TestListMissions:
    async def test_list_all(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
        archived_mission: Mission,
    ):
        service = MissionService(db_session)
        # list_missions with no owner_id returns active missions
        missions = await service.list_missions()
        active_ids = {m.id for m in missions}
        assert test_mission.id in active_ids
        # archived mission is not returned by list_active
        assert archived_mission.id not in active_ids

    async def test_list_by_owner(
        self,
        db_session: AsyncSession,
        regular_user: User,
        test_mission: Mission,
    ):
        service = MissionService(db_session)
        missions = await service.list_missions(owner_id=regular_user.id)
        assert any(m.id == test_mission.id for m in missions)


class TestUpdateMission:
    async def test_update_description(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = MissionService(db_session)
        updated = await service.update_mission(
            test_mission.id,
            description="Updated description",
        )
        assert updated.description == "Updated description"

    async def test_update_budget(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
    ):
        service = MissionService(db_session)
        updated = await service.update_mission(
            test_mission.id,
            budget_ceiling_usd=100.0,
        )
        assert updated.budget_ceiling_usd == 100.0


class TestDeleteMission:
    async def test_delete_mission(
        self,
        db_session: AsyncSession,
        regular_user: User,
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            gate_mode="manual",
            name="delete-me",
            description="Temporary mission",
            owner_id=regular_user.id,
        )
        mission_id = mission.id

        name = await service.delete_mission(mission_id)
        assert name == "delete-me"

        with pytest.raises(NotFoundError):
            await service.get_mission(mission_id)


async def _other_user(db_session: AsyncSession, key: str, system_role: str = "user") -> User:
    user = User(
        id=str(uuid5(_NS, f"user:p88-operator-{key}")),
        email=f"p88-operator-{key}@test.dev",
        display_name=f"Operator test {key}",
        hashed_password=security.hash_password("operator-password-123"),
        system_role=system_role,
        is_active=True,
    )
    user = await db_session.merge(user)
    await db_session.flush()
    return user


class TestIsOperator:
    @pytest.mark.parametrize(
        ("caller", "expected"),
        [
            ("platform_admin", True),
            ("mission_owner", True),
            ("member_owner", True),
            ("member_maintainer", True),
            ("member_viewer", False),
            ("non_member", False),
        ],
    )
    async def test_is_operator_matrix(
        self,
        db_session: AsyncSession,
        test_mission: Mission,
        regular_user: User,
        caller: str,
        expected: bool,
    ):
        if caller == "mission_owner":
            user = regular_user
        elif caller == "platform_admin":
            user = await _other_user(db_session, caller, system_role="admin")
        else:
            user = await _other_user(db_session, caller)
            roles = {
                "member_owner": MissionMemberRole.OWNER,
                "member_maintainer": MissionMemberRole.MAINTAINER,
                "member_viewer": MissionMemberRole.VIEWER,
            }
            if caller in roles:
                db_session.add(
                    MissionMember(mission_id=test_mission.id, user_id=user.id, role=roles[caller])
                )
                await db_session.flush()

        assert await MissionService(db_session).is_operator(test_mission.id, user) is expected

    async def test_is_operator_unknown_mission_raises_not_found(
        self, db_session: AsyncSession, regular_user: User
    ):
        with pytest.raises(NotFoundError):
            await MissionService(db_session).is_operator(
                "00000000-0000-0000-0000-000000000000", regular_user
            )


class TestDeleteMissionTemporal:
    async def test_delete_mission_terminates_mission_run_workflow(
        self, db_session: AsyncSession, regular_user: User
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            gate_mode="manual",
            name="p88-delete-terminates",
            description="tmp",
            owner_id=regular_user.id,
        )
        mission_id = mission.id
        plan = await MissionPlanService(db_session).get_or_create_plan(mission_id)
        run = MissionRun(
            mission_id=mission_id,
            plan_id=plan.id,
            sequence=await MissionRepository(db_session).increment_run_sequence(mission_id),
            trigger=MissionRunTrigger.MANUAL,
            status=MissionRunStatus.RUNNING,
        )
        db_session.add(run)
        await db_session.flush()
        run.temporal_workflow_id = mission_run_workflow_id(run.id)
        await db_session.flush()
        run_wid = run.temporal_workflow_id

        gateway = MagicMock()
        gateway.terminate = AsyncMock(return_value=WorkflowState.RUNNING)
        with patch(_CONNECT, AsyncMock(return_value=gateway)):
            await service.delete_mission(mission_id)

        gateway.terminate.assert_awaited_once_with(
            run_wid, reason="Mission p88-delete-terminates deleted"
        )
        with pytest.raises(NotFoundError):
            await service.get_mission(mission_id)

    async def test_delete_mission_aborts_when_temporal_unavailable(
        self, db_session: AsyncSession, regular_user: User
    ):
        service = MissionService(db_session)
        mission = await service.create_mission(
            gate_mode="manual",
            name="p88-delete-aborts",
            description="tmp",
            owner_id=regular_user.id,
        )
        mission_id = mission.id
        await MissionPlanService(db_session).get_or_create_plan(mission_id)

        with patch(_CONNECT, AsyncMock(side_effect=ExternalServiceError("Temporal unavailable"))):
            with pytest.raises(ExternalServiceError):
                await service.delete_mission(mission_id)

        assert (await service.get_mission(mission_id)).id == mission_id
