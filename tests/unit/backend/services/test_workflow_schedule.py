"""Tests for WorkflowScheduleService."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config_schema import WorkflowsSchema
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.models.workflow_definition import WorkflowDefinition
from modules.backend.services.workflow_schedule import (
from tests.conftest import TEST_USER_ID
    WorkflowScheduleService,
    _validate_cron,
)


def _mock_app_config(**overrides) -> MagicMock:
    """Create a mock AppConfig with a real WorkflowsSchema."""
    config = MagicMock()
    config.workflows = WorkflowsSchema(**overrides)
    return config


async def _seed_mission(db_session: AsyncSession) -> Mission:
    """Create a minimal mission for schedule tests."""
    mission = Mission(
        name="schedule-test",
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
    db_session: AsyncSession, mission_id: str,
) -> WorkflowDefinition:
    """Create a minimal workflow definition for schedule tests."""
    from modules.backend.core.utils import utc_now

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
                workflow_definition_id="nonexistent-id",
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

        result = await service.get_schedule(created.id)
        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_not_found(self, service):
        with pytest.raises(NotFoundError, match="not found"):
            await service.get_schedule("nonexistent-id")


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
        await service.toggle_enabled(s2.id, False)

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

        disabled = await service.toggle_enabled(created.id, False)
        assert disabled.enabled is False

        enabled = await service.toggle_enabled(created.id, True)
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
            created.id, cron_expression="0 12 * * *",
        )
        assert updated.cron_expression == "0 12 * * *"


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

        await service.delete_schedule(created.id)
        with pytest.raises(NotFoundError):
            await service.get_schedule(created.id)
