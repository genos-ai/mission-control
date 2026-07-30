"""Tests for reconcile_orphaned_workflow_runs (Plan 84 Phase 3.3).

Uses a real db_session per P12. Temporal resumes its own dispatched runs
(Plan 84 Phase 3.1), so this reconciler only needs to catch WorkflowRun
rows genuinely stuck in RUNNING/PENDING at startup — pre-Temporal orphans
and Temporal-worker loss.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
from modules.backend.services.mission_plan_crash_recovery import (
    ORPHAN_FAILURE_REASON,
    reconcile_orphaned_workflow_runs,
)


@pytest.fixture
async def mission_id(db_session: AsyncSession, test_user) -> str:
    """Create a real mission — WorkflowRun.mission_id is FK-constrained."""
    from modules.backend.models.mission import Mission

    m = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for crash recovery",
        owner_id=test_user.id,
    )
    db_session.add(m)
    await db_session.flush()
    return m.id


async def _make_run(
    db_session: AsyncSession,
    *,
    status: WorkflowRunState,
    mission_id: str | None = None,
) -> WorkflowRun:
    run = WorkflowRun(
        workflow_name="test.workflow",
        workflow_version=1,
        status=status,
        triggered_by="user:test",
        mission_id=mission_id,
    )
    db_session.add(run)
    await db_session.flush()
    return run


class TestReconcileOrphanedWorkflowRuns:
    @pytest.mark.asyncio
    async def test_running_run_marked_failed(self, db_session: AsyncSession):
        run = await _make_run(db_session, status=WorkflowRunState.RUNNING)

        count = await reconcile_orphaned_workflow_runs(db_session)

        assert count == 1
        await db_session.refresh(run)
        assert run.status == WorkflowRunState.FAILED
        assert run.completed_at is not None
        assert run.error_data["message"] == ORPHAN_FAILURE_REASON
        assert ORPHAN_FAILURE_REASON in run.result_summary

    @pytest.mark.asyncio
    async def test_pending_run_marked_failed(self, db_session: AsyncSession):
        run = await _make_run(db_session, status=WorkflowRunState.PENDING)

        count = await reconcile_orphaned_workflow_runs(db_session)

        assert count == 1
        await db_session.refresh(run)
        assert run.status == WorkflowRunState.FAILED

    @pytest.mark.asyncio
    async def test_completed_run_untouched(self, db_session: AsyncSession):
        run = await _make_run(db_session, status=WorkflowRunState.COMPLETED)

        count = await reconcile_orphaned_workflow_runs(db_session)

        assert count == 0
        await db_session.refresh(run)
        assert run.status == WorkflowRunState.COMPLETED

    @pytest.mark.asyncio
    async def test_no_orphans_returns_zero(self, db_session: AsyncSession):
        count = await reconcile_orphaned_workflow_runs(db_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_emits_failed_event_when_mission_id_present(
        self, db_session: AsyncSession, mission_id: str
    ):
        run = await _make_run(db_session, status=WorkflowRunState.RUNNING, mission_id=mission_id)
        event_bus = AsyncMock()

        count = await reconcile_orphaned_workflow_runs(db_session, event_bus)

        assert count == 1
        event_bus.publish_to_mission.assert_awaited_once()
        called_mission_id, event = event_bus.publish_to_mission.call_args[0]
        assert called_mission_id == mission_id
        assert event.workflow_run_id == run.id
        assert event.event_type == "workflow.run.failed"

    @pytest.mark.asyncio
    async def test_skips_event_emission_without_mission_id(self, db_session: AsyncSession):
        await _make_run(db_session, status=WorkflowRunState.RUNNING, mission_id=None)
        event_bus = AsyncMock()

        count = await reconcile_orphaned_workflow_runs(db_session, event_bus)

        assert count == 1
        event_bus.publish_to_mission.assert_not_awaited()
