"""Tests for WorkflowScheduleService."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config_schema import WorkflowsSchema
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.models.workflow_definition import WorkflowDefinition
from modules.backend.services.workflow_schedule import WorkflowScheduleService, _validate_cron
from tests.conftest import TEST_USER_ID


def _mock_app_config(**overrides) -> MagicMock:
    """Create a mock AppConfig with a real WorkflowsSchema."""
    config = MagicMock()
    config.workflows = WorkflowsSchema(**{"default_step_model": "quick", **overrides})
    return config


async def _seed_mission(db_session: AsyncSession, name: str = "schedule-test") -> Mission:
    """Create a minimal mission for schedule tests."""
    mission = Mission(
        name=name,
        description="Schedule test mission",
        owner_id=TEST_USER_ID,
        status="active",
        default_roster="default",
    )
    db_session.add(mission)
    await db_session.flush()

    member = MissionMember(
        mission_id=mission.id,
        user_id=TEST_USER_ID,
        role=MissionMemberRole.OWNER,
    )
    db_session.add(member)
    await db_session.flush()
    return mission


async def _seed_workflow_definition(
    db_session: AsyncSession,
    mission_id: str,
) -> WorkflowDefinition:
    """Create a minimal workflow definition for schedule tests."""

    wf = WorkflowDefinition(
        mission_id=mission_id,
        name="test-workflow",
        description="Test workflow",
        objective={"statement": "test", "category": "code"},
        steps=[{"id": "s1", "capability": "code.quality"}],
        trigger_config={"type": "schedule"},
        budget_config={"max_cost_usd": 10.0},
    )
    db_session.add(wf)
    await db_session.flush()
    return wf


@pytest.fixture(autouse=True)
async def _ensure_test_user(test_user):
    pass


@pytest.fixture
def service(db_session: AsyncSession) -> WorkflowScheduleService:
    return WorkflowScheduleService(db_session)


@pytest.fixture(autouse=True)
def _patch_config():
    """Patch get_app_config for all tests."""
    with patch(
        "modules.backend.services.workflow_schedule.get_app_config",
        return_value=_mock_app_config(),
    ):
        yield


class TestValidateCron:
    def test_valid_standard(self):
        _validate_cron("0 5 * * *")

    def test_valid_complex(self):
        _validate_cron("*/15 0-23 1,15 * 1-5")

    def test_invalid_field_count(self):
        with pytest.raises(ValidationError, match="5 fields"):
            _validate_cron("0 5 *")

    def test_invalid_characters(self):
        with pytest.raises(ValidationError, match="Invalid cron"):
            _validate_cron("0 5 * * abc")


class TestCreateSchedule:
    @pytest.mark.asyncio
    async def test_creates_schedule(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)

        schedule = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
            description="Daily at 5am",
        )
        assert schedule.cron_expression == "0 5 * * *"
        assert schedule.enabled is True
        assert schedule.iteration_count == 0
        assert schedule.next_fire_at is not None
        assert schedule.description == "Daily at 5am"

    @pytest.mark.asyncio
    async def test_invalid_cron_raises(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)

        with pytest.raises(ValidationError, match="5 fields"):
            await service.create_schedule(
                workflow_definition_id=wf.id,
                mission_id=mission.id,
                cron_expression="bad",
                created_by=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_nonexistent_workflow_raises(self, service, db_session):
        mission = await _seed_mission(db_session)

        with pytest.raises(NotFoundError, match="not found"):
            await service.create_schedule(
                workflow_definition_id="00000000-0000-0000-0000-000000000000",
                mission_id=mission.id,
                cron_expression="0 5 * * *",
                created_by=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_budget_exceeds_cap_raises(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)

        with pytest.raises(ValidationError, match="exceeds platform cap"):
            await service.create_schedule(
                workflow_definition_id=wf.id,
                mission_id=mission.id,
                cron_expression="0 5 * * *",
                created_by=TEST_USER_ID,
                budget_per_run_usd=999.99,
            )

    @pytest.mark.asyncio
    async def test_create_rejects_other_missions_definition(self, service, db_session):
        mission_a = await _seed_mission(db_session)
        mission_b = await _seed_mission(db_session, name="schedule-test-b")
        wf_b = await _seed_workflow_definition(db_session, mission_b.id)

        with pytest.raises(NotFoundError, match=f"Workflow definition '{wf_b.id}' not found"):
            await service.create_schedule(
                workflow_definition_id=wf_b.id,
                mission_id=mission_a.id,
                cron_expression="0 5 * * *",
                created_by=TEST_USER_ID,
            )


class TestGetSchedule:
    @pytest.mark.asyncio
    async def test_found(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)
        created = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )

        result = await service.get_schedule(mission.id, created.id)
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_not_found(self, service, db_session):
        mission = await _seed_mission(db_session)
        with pytest.raises(NotFoundError, match="not found"):
            await service.get_schedule(mission.id, "00000000-0000-0000-0000-000000000000")

    @pytest.mark.asyncio
    async def test_get_schedule_other_mission_raises_not_found(self, service, db_session):
        mission_a = await _seed_mission(db_session)
        mission_b = await _seed_mission(db_session, name="schedule-test-b")
        wf_b = await _seed_workflow_definition(db_session, mission_b.id)
        created = await service.create_schedule(
            workflow_definition_id=wf_b.id,
            mission_id=mission_b.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )

        with pytest.raises(NotFoundError, match="not found"):
            await service.get_schedule(mission_a.id, created.id)


class TestListByMission:
    @pytest.mark.asyncio
    async def test_list_enabled(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)

        s1 = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )
        s2 = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 12 * * *",
            created_by=TEST_USER_ID,
        )
        await service.toggle_enabled(mission.id, s2.id, False)

        results = await service.list_by_mission(mission.id, enabled_only=True)
        assert len(results) == 1
        assert results[0].id == s1.id


class TestToggleEnabled:
    @pytest.mark.asyncio
    async def test_disable_and_enable(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)
        created = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )

        disabled = await service.toggle_enabled(mission.id, created.id, False)
        assert disabled.enabled is False

        enabled = await service.toggle_enabled(mission.id, created.id, True)
        assert enabled.enabled is True
        assert enabled.next_fire_at is not None


class TestUpdateSchedule:
    @pytest.mark.asyncio
    async def test_update_cron_recomputes_next_fire(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)
        created = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )
        original_next = created.next_fire_at

        updated = await service.update_schedule(
            mission.id,
            created.id,
            cron_expression="0 12 * * *",
        )
        assert updated.cron_expression == "0 12 * * *"
        assert updated.next_fire_at != original_next

    @pytest.mark.asyncio
    async def test_update_schedule_enable_recomputes_next_fire_at(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)
        created = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )
        stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await service.update_schedule(mission.id, created.id, enabled=False, next_fire_at=stale)
        fresh = datetime(2030, 6, 1, 5, 0, tzinfo=timezone.utc)

        with patch(
            "modules.backend.services.workflow_schedule._compute_next_fire",
            return_value=fresh,
        ) as compute:
            updated = await service.update_schedule(mission.id, created.id, enabled=True)

        assert updated.enabled is True
        assert updated.next_fire_at == fresh
        compute.assert_called_once()
        assert compute.call_args.args[0] == "0 5 * * *"

    @pytest.mark.asyncio
    async def test_update_schedule_disable_does_not_recompute(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)
        created = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )
        original_next = created.next_fire_at

        with patch("modules.backend.services.workflow_schedule._compute_next_fire") as compute:
            updated = await service.update_schedule(mission.id, created.id, enabled=False)

        assert updated.enabled is False
        assert updated.next_fire_at == original_next
        compute.assert_not_called()


class TestDeleteSchedule:
    @pytest.mark.asyncio
    async def test_delete(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await _seed_workflow_definition(db_session, mission.id)
        created = await service.create_schedule(
            workflow_definition_id=wf.id,
            mission_id=mission.id,
            cron_expression="0 5 * * *",
            created_by=TEST_USER_ID,
        )

        await service.delete_schedule(mission.id, created.id)
        with pytest.raises(NotFoundError):
            await service.get_schedule(mission.id, created.id)
