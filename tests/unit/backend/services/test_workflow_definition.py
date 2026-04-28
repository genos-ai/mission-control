"""Tests for WorkflowDefinitionService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole
from modules.backend.services.workflow_definition import WorkflowDefinitionService
from tests.conftest import TEST_USER_ID


async def _seed_mission(db_session: AsyncSession) -> Mission:
    """Create a minimal mission for workflow tests."""
    mission = Mission(
        name="wf-test-mission",
        description="Workflow test mission",
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


def _minimal_step():
    return {
        "id": "step-1",
        "capability": "code.quality",
        "description": "Run quality check",
        "roster": "default",
        "complexity_tier": "simple",
        "environment": "local",
        "input": {},
    }


def _minimal_objective():
    return {
        "statement": "Improve code quality",
        "category": "code",
        "owner": TEST_USER_ID,
        "priority": "standard",
    }


@pytest.fixture
def service(db_session: AsyncSession) -> WorkflowDefinitionService:
    return WorkflowDefinitionService(db_session)


class TestCreateWorkflow:
    @pytest.mark.asyncio
    async def test_creates_workflow(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await service.create_workflow(
            mission_id=mission.id,
            name="quality-check",
            description="Run quality checks",
            objective=_minimal_objective(),
            steps=[_minimal_step()],
        )
        assert wf.name == "quality-check"
        assert wf.mission_id == mission.id
        assert len(wf.steps) == 1

    @pytest.mark.asyncio
    async def test_duplicate_name_raises_conflict(self, service, db_session):
        mission = await _seed_mission(db_session)
        await service.create_workflow(
            mission.id, "wf-1", "desc", _minimal_objective(), [_minimal_step()],
        )
        with pytest.raises(ConflictError, match="already exists"):
            await service.create_workflow(
                mission.id, "wf-1", "desc", _minimal_objective(), [_minimal_step()],
            )

    @pytest.mark.asyncio
    async def test_empty_steps_raises_validation(self, service, db_session):
        mission = await _seed_mission(db_session)
        with pytest.raises(ValidationError, match="at least one step"):
            await service.create_workflow(
                mission.id, "empty", "desc", _minimal_objective(), [],
            )


class TestGetWorkflow:
    @pytest.mark.asyncio
    async def test_found(self, service, db_session):
        mission = await _seed_mission(db_session)
        await service.create_workflow(
            mission.id, "wf-get", "desc", _minimal_objective(), [_minimal_step()],
        )
        result = await service.get_workflow(mission.id, "wf-get")
        assert result.name == "wf-get"

    @pytest.mark.asyncio
    async def test_not_found(self, service, db_session):
        mission = await _seed_mission(db_session)
        with pytest.raises(NotFoundError):
            await service.get_workflow(mission.id, "nonexistent")


class TestListWorkflows:
    @pytest.mark.asyncio
    async def test_list_enabled(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf1 = await service.create_workflow(
            mission.id, "a", "desc", _minimal_objective(), [_minimal_step()],
        )
        wf2 = await service.create_workflow(
            mission.id, "b", "desc", _minimal_objective(), [_minimal_step()],
        )
        await service.update_workflow(wf2.id, enabled=False)

        results = await service.list_workflows(mission.id, enabled_only=True)
        assert len(results) == 1
        assert results[0].name == "a"


class TestLockWorkflow:
    @pytest.mark.asyncio
    async def test_lock_sets_timestamp(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await service.create_workflow(
            mission.id, "lockable", "desc", _minimal_objective(), [_minimal_step()],
        )
        assert wf.locked_at is None

        locked = await service.lock_workflow(wf.id)
        assert locked.locked_at is not None
