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


@pytest.fixture(autouse=True)
async def _ensure_test_user(test_user):
    pass


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
            mission.id,
            "wf-1",
            "desc",
            _minimal_objective(),
            [_minimal_step()],
        )
        with pytest.raises(ConflictError, match="already exists"):
            await service.create_workflow(
                mission.id,
                "wf-1",
                "desc",
                _minimal_objective(),
                [_minimal_step()],
            )

    @pytest.mark.asyncio
    async def test_empty_steps_raises_validation(self, service, db_session):
        mission = await _seed_mission(db_session)
        with pytest.raises(ValidationError, match="at least one step"):
            await service.create_workflow(
                mission.id,
                "empty",
                "desc",
                _minimal_objective(),
                [],
            )


class TestGetWorkflow:
    @pytest.mark.asyncio
    async def test_found(self, service, db_session):
        mission = await _seed_mission(db_session)
        await service.create_workflow(
            mission.id,
            "wf-get",
            "desc",
            _minimal_objective(),
            [_minimal_step()],
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
        await service.create_workflow(
            mission.id,
            "a",
            "desc",
            _minimal_objective(),
            [_minimal_step()],
        )
        wf2 = await service.create_workflow(
            mission.id,
            "b",
            "desc",
            _minimal_objective(),
            [_minimal_step()],
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
            mission.id,
            "lockable",
            "desc",
            _minimal_objective(),
            [_minimal_step()],
        )
        assert wf.locked_at is None

        locked = await service.lock_workflow(wf.id)
        assert locked.locked_at is not None


class TestEdgeNormalisation:
    """Every write method on WorkflowDefinitionService must run edges
    through WorkflowEdgeSchema so that raw-dict callers cannot reintroduce
    the missing-edge-id regression that plan81_001 backfilled."""

    @pytest.mark.asyncio
    async def test_create_workflow_fills_missing_edge_ids(
        self,
        service,
        db_session,
    ):
        mission = await _seed_mission(db_session)
        wf = await service.create_workflow(
            mission_id=mission.id,
            name="edges-no-id",
            description="raw dicts without ids",
            objective=_minimal_objective(),
            steps=[
                _minimal_step(),
                {**_minimal_step(), "id": "step-2", "depends_on": ["step-1"]},
            ],
            edges_json=[
                {"source": "step-1", "target": "step-2"},
            ],
        )
        assert wf.edges_json == [
            {
                "id": "step-1->step-2",
                "source": "step-1",
                "target": "step-2",
                "source_handle": "output",
                "target_handle": "input",
                "label": None,
            },
        ]

    @pytest.mark.asyncio
    async def test_create_workflow_rejects_malformed_edge(
        self,
        service,
        db_session,
    ):
        mission = await _seed_mission(db_session)
        with pytest.raises(ValidationError, match="Invalid edge definition"):
            await service.create_workflow(
                mission_id=mission.id,
                name="bad-edge",
                description="edge missing source",
                objective=_minimal_objective(),
                steps=[_minimal_step()],
                edges_json=[{"target": "step-1"}],  # missing required `source`
            )

    @pytest.mark.asyncio
    async def test_create_workflow_preserves_valid_edges(
        self,
        service,
        db_session,
    ):
        mission = await _seed_mission(db_session)
        edges = [
            {
                "id": "custom-id",
                "source": "step-1",
                "target": "step-2",
                "source_handle": "passed",
                "target_handle": "input",
                "label": "ok",
            },
        ]
        wf = await service.create_workflow(
            mission_id=mission.id,
            name="edges-explicit",
            description="explicit edges round-trip",
            objective=_minimal_objective(),
            steps=[
                _minimal_step(),
                {**_minimal_step(), "id": "step-2", "depends_on": ["step-1"]},
            ],
            edges_json=edges,
        )
        assert wf.edges_json == edges

    @pytest.mark.asyncio
    async def test_save_graph_normalises_edges(self, service, db_session):
        mission = await _seed_mission(db_session)
        wf = await service.create_workflow(
            mission.id,
            "save-graph-norm",
            "desc",
            _minimal_objective(),
            [_minimal_step()],
        )
        steps = [
            _minimal_step(),
            {**_minimal_step(), "id": "step-2", "depends_on": ["step-1"]},
        ]
        updated, _warnings = await service.save_graph(
            workflow_id=wf.id,
            canvas_state={},
            edges_json=[{"source": "step-1", "target": "step-2"}],
            steps=steps,
        )
        assert updated.edges_json[0]["id"] == "step-1->step-2"

    @pytest.mark.asyncio
    async def test_update_workflow_normalises_edges(
        self,
        service,
        db_session,
    ):
        mission = await _seed_mission(db_session)
        wf = await service.create_workflow(
            mission.id,
            "update-norm",
            "desc",
            _minimal_objective(),
            [_minimal_step()],
        )
        updated = await service.update_workflow(
            wf.id,
            edges_json=[{"source": "step-1", "target": "step-1"}],
        )
        assert updated.edges_json[0]["id"] == "step-1->step-1"


class TestSeederEdgeIdNormalisation:
    """Persisted edges must always carry an `id` — the visual editor's React
    Flow drops edges sharing a synthesized key, so a YAML template that
    omits ids must not flow through untouched."""

    @pytest.mark.asyncio
    async def test_seed_deliberation_think_tank_persists_edge_ids(
        self,
        service,
        db_session,
    ):
        from pathlib import Path

        import yaml

        from modules.backend.schemas.workflow import WorkflowSchema

        yaml_path = (
            Path(__file__).resolve().parents[4]
            / "config/workflow_templates/deliberation.think-tank.workflow.yaml"
        )
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        schema = WorkflowSchema(**raw)

        # Simulate the seeder's persistence path (system template: mission_id=None).
        workflow = await service.create_workflow(
            mission_id=None,
            name="deliberation.think-tank-seedtest",
            description=schema.description,
            objective=schema.objective.model_dump(),
            steps=[s.model_dump() for s in schema.steps],
            edges_json=[e.model_dump() for e in schema.edges] if schema.edges else None,
            trigger_config=schema.trigger.model_dump(),
            budget_config=schema.budget.model_dump(),
            context=schema.context,
            designed_by="test:seeder",
        )

        assert workflow.edges_json, "Seeded workflow has no edges persisted"
        for edge in workflow.edges_json:
            assert edge.get("id"), f"Persisted edge missing id: {edge}"

        ids = [e["id"] for e in workflow.edges_json]
        assert len(ids) == len(set(ids)), (
            "Persisted edge ids are not unique — React Flow will drop "
            f"collisions: duplicates in {ids}"
        )
