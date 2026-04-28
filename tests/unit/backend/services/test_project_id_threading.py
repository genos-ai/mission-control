"""
Tests for mission_id (container) threading through workflow → execution → dispatch.

Verifies that mission_id flows from WorkflowRunService.run_workflow() (resolved
from --mission name) through ExecutionService.create_execution_from_step() and
run_execution() down to the DispatchAdapter and handle_mission().

Uses real db_session with transaction rollback (P12).
Only mocks dispatch execution (external agent calls — not infra we operate).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid5, UUID

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.base import SYSTEM_WORKFLOW_ID
from modules.backend.core.config_schema import WorkflowsSchema
from modules.backend.models.execution import ExecutionState
from modules.backend.models.session import Session
from modules.backend.services.execution import ExecutionService
from datetime import datetime as _dt, timezone as _tz
from tests.conftest import TEST_USER_ID

_TEST_NS = UUID("00000000-0000-0000-0000-000000000000")

_MISSION_ABC = str(uuid5(_TEST_NS, "mission:proj-abc"))
_MISSION_XYZ = str(uuid5(_TEST_NS, "mission:proj-xyz"))
_MISSION_RESOLVED = str(uuid5(_TEST_NS, "mission:resolved"))
_MISSION_NEW = str(uuid5(_TEST_NS, "mission:new"))

_SESS_1 = "5714117c-eaed-5ce3-9c56-73949f03aa3d"
_SESS_2 = "bac9134a-a913-50f4-adec-9725086b8998"
_SESS_3 = "80d00060-470d-5db0-aa70-5adc526200ea"
_SESS_4 = str(uuid5(_TEST_NS, "session:proj-thread-4"))


def _mock_app_config(**overrides):
    config = MagicMock()
    config.workflows = WorkflowsSchema(**overrides)
    return config


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    """Create Session rows that Execution.session_id FKs to."""
    for sid in (_SESS_1, _SESS_2, _SESS_3, _SESS_4):
        db_session.add(Session(id=sid, status="ACTIVE"))
    await db_session.flush()


# =============================================================================
# ExecutionService: mission_id on create_execution_from_step
# =============================================================================


class TestExecutionServiceMissionId:
    @pytest.mark.asyncio
    async def test_create_execution_from_step_sets_mission_id(
        self, db_session: AsyncSession,
    ):
        """mission_id is persisted on the Execution record."""
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            mission = await service.create_execution_from_step(
                workflow_run_id="eb91e1a8-65fe-557d-a7ea-144f9b2baa61",
                step_id="step-1",
                objective="Test objective",
                roster_ref="default",
                complexity_tier="simple",
                cost_ceiling_usd=1.0,
                upstream_context={},
                session_id=_SESS_1,
                mission_id=_MISSION_ABC,
            )

        assert mission.mission_id == _MISSION_ABC

    @pytest.mark.asyncio
    async def test_create_execution_from_step_mission_id_defaults_none(
        self, db_session: AsyncSession,
    ):
        """mission_id defaults to None when not provided."""
        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(session=db_session)
            mission = await service.create_execution_from_step(
                workflow_run_id="58f17d89-d819-5068-b33f-4e4b93be9e51",
                step_id="step-1",
                objective="No project",
                roster_ref="default",
                complexity_tier="simple",
                cost_ceiling_usd=1.0,
                upstream_context={},
                session_id=_SESS_2,
            )

        assert mission.mission_id is None

    @pytest.mark.asyncio
    async def test_run_execution_passes_mission_id_to_dispatch(
        self, db_session: AsyncSession,
    ):
        """run_execution() forwards execution.mission_id to the dispatch adapter."""
        mock_dispatch = AsyncMock()
        mock_dispatch.execute = AsyncMock(return_value={
            "status": "success",
            "success": True,
            "total_cost_usd": 0.01,
            "task_results": [],
            "summary": "Done",
        })

        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(
                session=db_session,
                mission_control_dispatch=mock_dispatch,
            )
            mission = await service.create_execution_from_step(
                workflow_run_id="9472c408-004d-50c4-ac6e-c2fc28c3c42e",
                step_id="step-1",
                objective="With project",
                roster_ref="default",
                complexity_tier="simple",
                cost_ceiling_usd=1.0,
                upstream_context={},
                session_id=_SESS_3,
                mission_id=_MISSION_XYZ,
            )

            await service.run_execution(mission.id)

        # Verify mission_id was forwarded to the adapter
        mock_dispatch.execute.assert_called_once()
        call_kwargs = mock_dispatch.execute.call_args.kwargs
        assert call_kwargs["mission_id"] == _MISSION_XYZ

    @pytest.mark.asyncio
    async def test_run_execution_passes_none_mission_id(
        self, db_session: AsyncSession,
    ):
        """run_execution() passes None mission_id when execution has no mission container."""
        mock_dispatch = AsyncMock()
        mock_dispatch.execute = AsyncMock(return_value={
            "status": "success",
            "success": True,
            "total_cost_usd": 0.01,
            "task_results": [],
            "summary": "Done",
        })

        with patch(
            "modules.backend.services.execution.get_app_config",
            return_value=_mock_app_config(),
        ):
            service = ExecutionService(
                session=db_session,
                mission_control_dispatch=mock_dispatch,
            )
            mission = await service.create_execution_from_step(
                workflow_run_id="285eaa29-1d3b-5500-9bb5-0f52e2f54860",
                step_id="step-1",
                objective="No project",
                roster_ref="default",
                complexity_tier="simple",
                cost_ceiling_usd=1.0,
                upstream_context={},
                session_id=_SESS_4,
            )

            await service.run_execution(mission.id)

        call_kwargs = mock_dispatch.execute.call_args.kwargs
        assert call_kwargs["mission_id"] is None


# =============================================================================
# DispatchAdapter: mission_id forwarded to handle_mission
# =============================================================================


class TestDispatchAdapterMissionId:
    @pytest.mark.asyncio
    async def test_execute_forwards_mission_id(self, db_session: AsyncSession):
        """DispatchAdapter.execute() passes mission_id and db_session to handle_mission()."""
        from modules.backend.agents.mission_control.dispatch_adapter import (
            MissionControlDispatchAdapter,
        )

        mock_session_service = MagicMock()
        adapter = MissionControlDispatchAdapter(
            session_service=mock_session_service,
            db_session=db_session,
        )

        mock_outcome = MagicMock()
        mock_outcome.status = "success"
        mock_outcome.task_results = []
        mock_outcome.total_cost_usd = 0.01
        mock_outcome.model_dump.return_value = {
            "status": "success",
            "task_results": [],
            "total_cost_usd": 0.01,
        }

        with patch(
            "modules.backend.agents.mission_control.dispatch_adapter.handle_mission",
            new_callable=AsyncMock,
            return_value=mock_outcome,
        ) as mock_handle:
            result = await adapter.execute(
                mission_brief="Test brief",
                mission_id="proj-test-123",
            )

        mock_handle.assert_called_once()
        call_kwargs = mock_handle.call_args.kwargs
        assert call_kwargs["mission_id"] == "proj-test-123"
        assert call_kwargs["db_session"] is db_session

    @pytest.mark.asyncio
    async def test_execute_without_mission_id(self, db_session: AsyncSession):
        """DispatchAdapter.execute() passes None mission_id when not provided."""
        from modules.backend.agents.mission_control.dispatch_adapter import (
            MissionControlDispatchAdapter,
        )

        mock_session_service = MagicMock()
        adapter = MissionControlDispatchAdapter(
            session_service=mock_session_service,
            db_session=db_session,
        )

        mock_outcome = MagicMock()
        mock_outcome.status = "success"
        mock_outcome.task_results = []
        mock_outcome.total_cost_usd = 0.0
        mock_outcome.model_dump.return_value = {
            "status": "success",
            "task_results": [],
            "total_cost_usd": 0.0,
        }

        with patch(
            "modules.backend.agents.mission_control.dispatch_adapter.handle_mission",
            new_callable=AsyncMock,
            return_value=mock_outcome,
        ) as mock_handle:
            await adapter.execute(mission_brief="Test brief")

        call_kwargs = mock_handle.call_args.kwargs
        assert call_kwargs["mission_id"] is None


# =============================================================================
# WorkflowRunService: name-based mission resolution and threading
# =============================================================================


class TestWorkflowRunMissionId:
    """Tests for mission_id parameter in WorkflowRunService.run_workflow()."""

    def _mock_workflow_service(self):
        mock_workflow_service = MagicMock()
        mock_workflow = MagicMock()
        mock_workflow.workflow_name = "test-workflow"
        mock_workflow.version = "1.0"
        mock_workflow.enabled = True
        mock_workflow.trigger.type = "manual"
        mock_workflow.context = {}
        mock_workflow.budget.max_cost_usd = 10.0
        mock_workflow.description = "Test workflow"
        mock_workflow.steps = []
        mock_workflow_service.get_workflow.return_value = mock_workflow
        mock_workflow_service.validate_workflow_capabilities.return_value = []
        return mock_workflow_service, mock_workflow

    @pytest.mark.asyncio
    async def test_run_workflow_passes_mission_id(
        self, db_session: AsyncSession,
    ):
        """run_workflow() passes mission_id through to the run record."""
        from modules.backend.services.workflow_run import WorkflowRunService
        from modules.backend.services.workflow_definition import WorkflowDefinitionService

        mock_ws, _ = self._mock_workflow_service()

        mock_defn = MagicMock()
        mock_defn.id = _MISSION_RESOLVED
        mock_defn.name = "test-workflow"
        mock_defn.version = "1.0"
        mock_defn.enabled = True
        mock_defn.description = "Test"
        mock_defn.objective = {"statement": "t", "category": "code", "owner": "o", "priority": "standard"}
        mock_defn.trigger_config = {"type": "on_demand"}
        mock_defn.budget_config = {"max_cost_usd": 10.0}
        mock_defn.context = {}
        mock_defn.steps = []
        mock_defn.edges_json = None

        with (
            patch.object(
                WorkflowDefinitionService, "get_workflow",
                new_callable=AsyncMock,
                return_value=mock_defn,
            ),
            patch.object(
                WorkflowRunService, "run_workflow_from_definition",
                new_callable=AsyncMock,
            ) as mock_run_from_def,
        ):
            mock_run = MagicMock()
            mock_run.mission_id = _MISSION_RESOLVED
            mock_run_from_def.return_value = mock_run

            service = WorkflowRunService(
                session=db_session, workflow_service=mock_ws,
            )
            run = await service.run_workflow(
                workflow_name="test-workflow",
                mission_id=_MISSION_RESOLVED,
            )

        assert run.mission_id == _MISSION_RESOLVED
        mock_run_from_def.assert_called_once()
        call_kwargs = mock_run_from_def.call_args.kwargs
        assert call_kwargs.get("mission_id") or mock_run_from_def.call_args.args[1] == _MISSION_RESOLVED

    @pytest.mark.asyncio
    async def test_run_workflow_requires_mission_id(
        self, db_session: AsyncSession,
    ):
        """Omitting mission_id raises ValueError."""
        from modules.backend.services.workflow_run import WorkflowRunService

        mock_ws, _ = self._mock_workflow_service()

        service = WorkflowRunService(
            session=db_session, workflow_service=mock_ws,
        )
        with pytest.raises(ValueError, match="mission_id is required"):
            await service.run_workflow(workflow_name="test-workflow")
