"""Integration tests for ExecutionService — real database, no mocks.

Tests focus on database persistence, state transitions, and query
methods. Dispatch (run_execution) is not tested here because it
requires LLM/agent infrastructure — that's covered by unit tests
with mocked dispatch adapters.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.models.execution import Execution, ExecutionState
from modules.backend.models.mission import Mission
from modules.backend.models.user import User
from modules.backend.core.utils import utc_now
from modules.backend.services.execution import ExecutionService


def _make_service(db_session: AsyncSession) -> ExecutionService:
    """Create an ExecutionService without dispatch adapter."""
    return ExecutionService(session=db_session)


class TestCreateAdhocExecution:
    async def test_create_basic(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="Run unit tests",
            triggered_by="user:user-001",
            session_id="sess-1",
            mission_id=test_mission.id,
        )

        assert execution.id is not None
        assert execution.objective == "Run unit tests"
        assert execution.status == ExecutionState.PENDING
        assert execution.triggered_by == "user:user-001"
        assert execution.session_id == "sess-1"
        assert execution.mission_id == test_mission.id
        assert execution.trigger_type == "on_demand"
        assert execution.roster_ref == "default"

    async def test_create_with_custom_params(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="Deploy to staging",
            triggered_by="user:admin-001",
            roster_ref="devops",
            complexity_tier="complex",
            cost_ceiling_usd=25.0,
            upstream_context={"branch": "main"},
            mission_id=test_mission.id,
        )

        assert execution.roster_ref == "devops"
        assert execution.complexity_tier == "complex"
        assert execution.cost_ceiling_usd == 25.0
        assert execution.upstream_context == {"branch": "main"}

    async def test_create_auto_generates_session_id(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="Quick check",
            triggered_by="user:user-001",
            mission_id=test_mission.id,
        )

        assert execution.session_id is not None
        assert len(execution.session_id) > 0

    async def test_create_without_mission(self, db_session: AsyncSession):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="Standalone task",
            triggered_by="system",
            session_id="sess-standalone",
        )

        assert execution.id is not None
        assert execution.mission_id is None


class TestCreateFromStep:
    async def test_create_from_workflow_step(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_execution_from_step(
            workflow_run_id="wfr-001",
            step_id="step-001",
            objective="Analyze codebase",
            roster_ref="default",
            complexity_tier="simple",
            cost_ceiling_usd=5.0,
            upstream_context={},
            session_id="sess-wf",
            mission_id=test_mission.id,
        )

        assert execution.workflow_run_id == "wfr-001"
        assert execution.workflow_step_id == "step-001"
        assert execution.trigger_type == "workflow"
        assert execution.status == ExecutionState.PENDING


class TestGetExecution:
    async def test_get_existing(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        created = await svc.create_adhoc_execution(
            objective="Find it",
            triggered_by="user:user-001",
            session_id="sess-get",
            mission_id=test_mission.id,
        )

        found = await svc.get_execution(created.id)
        assert found.id == created.id
        assert found.objective == "Find it"

    async def test_get_nonexistent_raises(self, db_session: AsyncSession):
        svc = _make_service(db_session)
        with pytest.raises(NotFoundError):
            await svc.get_execution("nonexistent-id")

    async def test_get_or_none_returns_none(self, db_session: AsyncSession):
        svc = _make_service(db_session)
        result = await svc.get_execution_or_none("nonexistent-id")
        assert result is None

    async def test_get_or_none_returns_execution(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        created = await svc.create_adhoc_execution(
            objective="Optional find",
            triggered_by="user:user-001",
            session_id="sess-opt",
            mission_id=test_mission.id,
        )

        found = await svc.get_execution_or_none(created.id)
        assert found is not None
        assert found.id == created.id


class TestStateTransitions:
    async def test_cancel_pending_execution(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="To be cancelled",
            triggered_by="user:user-001",
            session_id="sess-cancel",
            mission_id=test_mission.id,
        )

        cancelled = await svc.cancel_execution(execution.id, reason="No longer needed")
        assert cancelled.status == ExecutionState.CANCELLED
        assert cancelled.error_data is not None
        assert cancelled.error_data.get("cancelled_reason") == "No longer needed"
        assert cancelled.completed_at is not None

    async def test_fail_execution(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="Will fail",
            triggered_by="user:user-001",
            session_id="sess-fail",
            mission_id=test_mission.id,
        )
        # Manually transition to RUNNING first
        execution.status = ExecutionState.RUNNING
        execution.started_at = utc_now()
        await db_session.flush()

        failed = await svc.fail_execution(
            execution.id, error="Something broke",
            error_data={"trace": "stack trace here"},
        )
        assert failed.status == ExecutionState.FAILED
        assert failed.error_data is not None
        assert "trace" in failed.error_data

    async def test_complete_execution(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="Will complete",
            triggered_by="user:user-001",
            session_id="sess-complete",
            mission_id=test_mission.id,
        )
        # Manually transition to RUNNING
        execution.status = ExecutionState.RUNNING
        execution.started_at = utc_now()
        await db_session.flush()

        completed = await svc.complete_execution(execution.id)
        assert completed.status == ExecutionState.COMPLETED
        assert completed.completed_at is not None


class TestListExecutions:
    async def test_list_by_mission(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        await svc.create_adhoc_execution(
            objective="Task A",
            triggered_by="user:user-001",
            session_id="sess-a",
            mission_id=test_mission.id,
        )
        await svc.create_adhoc_execution(
            objective="Task B",
            triggered_by="user:user-001",
            session_id="sess-b",
            mission_id=test_mission.id,
        )

        executions, total = await svc.list_executions(
            mission_id=test_mission.id,
        )
        assert total >= 2
        assert all(e.mission_id == test_mission.id for e in executions)

    async def test_list_by_status(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        await svc.create_adhoc_execution(
            objective="Pending task",
            triggered_by="user:user-001",
            session_id="sess-pending",
            mission_id=test_mission.id,
        )

        executions, total = await svc.list_executions(
            status="pending", mission_id=test_mission.id,
        )
        assert total >= 1
        assert all(
            e.status == ExecutionState.PENDING for e in executions
        )

    async def test_list_with_pagination(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        for i in range(5):
            await svc.create_adhoc_execution(
                objective=f"Task {i}",
                triggered_by="user:user-001",
                session_id=f"sess-page-{i}",
                mission_id=test_mission.id,
            )

        page1, total = await svc.list_executions(
            mission_id=test_mission.id, limit=2, offset=0,
        )
        page2, _ = await svc.list_executions(
            mission_id=test_mission.id, limit=2, offset=2,
        )

        assert len(page1) == 2
        assert len(page2) == 2
        assert total >= 5
        # Pages should not overlap
        page1_ids = {e.id for e in page1}
        page2_ids = {e.id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)


class TestOutputExtraction:
    async def test_extract_with_summary_key(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="Generate report",
            triggered_by="user:user-001",
            session_id="sess-extract",
            mission_id=test_mission.id,
        )
        execution.execution_outcome = {
            "summary": "All tests passed",
            "task_results": [],
        }
        await db_session.flush()

        outputs = svc.extract_outputs(
            execution,
            output_mapping={"summary_key": "summary"},
        )
        assert outputs.get("summary") == "All tests passed"

    async def test_extract_no_mapping_returns_empty(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="No mapping",
            triggered_by="user:user-001",
            session_id="sess-nomap",
            mission_id=test_mission.id,
        )

        outputs = svc.extract_outputs(execution, output_mapping=None)
        assert outputs == {}

    async def test_extract_no_outcome_returns_empty(
        self, db_session: AsyncSession, test_mission: Mission,
    ):
        svc = _make_service(db_session)
        execution = await svc.create_adhoc_execution(
            objective="No outcome",
            triggered_by="user:user-001",
            session_id="sess-noout",
            mission_id=test_mission.id,
        )

        outputs = svc.extract_outputs(
            execution,
            output_mapping={"summary_key": "summary"},
        )
        assert outputs == {}
