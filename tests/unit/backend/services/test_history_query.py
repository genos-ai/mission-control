"""Tests for HistoryQueryService.

Per P12: tests run against the live platform. Uses real db_session fixture
with transaction rollback for isolation.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.execution_record import (
    FailureTier,
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskAttempt,
    TaskAttemptStatus,
    TaskExecution,
    TaskExecutionStatus,
)
from modules.backend.models.mission import Mission
from modules.backend.models.session import Session
from modules.backend.services.history_query import HistoryQueryService
from uuid import uuid5, UUID
from tests.conftest import TEST_USER_ID

_NS = UUID("00000000-0000-0000-0000-000000000000")
_MID = lambda tag: str(uuid5(_NS, f"mission:hist-{tag}"))
_NIL_UUID = "00000000-0000-0000-0000-000000000000"
_SESS_HIST = "5714117c-eaed-5ce3-9c56-73949f03aa3d"

# All mission_id slugs used in this file.
_MISSION_SLUGS = [
    "proj-1", "proj-exec", "proj-tags", "proj-limit", "proj-a", "proj-b",
    "proj-fail", "proj-fail-tag", "proj-fail-lim", "proj-ok",
    "proj-sum", "proj-sum-lim",
    "proj-sf", "proj-sf2", "proj-sf3", "proj-sf4", "proj-sf5",
]


@pytest.fixture
def history_service(db_session: AsyncSession) -> HistoryQueryService:
    return HistoryQueryService(db_session)


@pytest.fixture(autouse=True)
async def _ensure_parent_rows(test_user, db_session: AsyncSession):
    """Create Session + Mission rows that child tables FK to."""
    db_session.add(Session(id=_SESS_HIST, status="ACTIVE"))
    for slug in _MISSION_SLUGS:
        db_session.add(
            Mission(id=_MID(slug), name=slug, description="test", owner_id=TEST_USER_ID)
        )
    await db_session.flush()


async def _create_mission(
    db: AsyncSession,
    mission_id: str = _MID("proj-1"),
    status: ExecutionRecordStatus = ExecutionRecordStatus.COMPLETED,
    objective: str = "Test mission",
    cost: float = 0.5,
) -> ExecutionRecord:
    """Helper to create an ExecutionRecord."""
    record = ExecutionRecord(
        session_id="5714117c-eaed-5ce3-9c56-73949f03aa3d",
        mission_id=mission_id,
        status=status,
        objective_statement=objective,
        total_cost_usd=cost,
        started_at="2025-01-01T00:00:00Z",
        completed_at="2025-01-01T00:01:00Z",
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


async def _create_execution(
    db: AsyncSession,
    execution_record_id: str,
    task_id: str = "task-1",
    agent_name: str = "analyzer",
    status: TaskExecutionStatus = TaskExecutionStatus.COMPLETED,
    domain_tags: list[str] | None = None,
    cost_usd: float = 0.1,
    duration_seconds: float = 5.0,
) -> TaskExecution:
    """Helper to create a TaskExecution."""
    execution = TaskExecution(
        execution_record_id=execution_record_id,
        task_id=task_id,
        agent_name=agent_name,
        status=status,
        cost_usd=cost_usd,
        duration_seconds=duration_seconds,
        domain_tags=domain_tags,
        completed_at="2025-01-01T00:00:30Z",
    )
    db.add(execution)
    await db.flush()
    await db.refresh(execution)
    return execution


async def _create_failed_attempt(
    db: AsyncSession,
    task_execution_id: str,
    attempt_number: int = 1,
    failure_reason: str = "Schema validation failed",
) -> TaskAttempt:
    """Helper to create a failed TaskAttempt."""
    attempt = TaskAttempt(
        task_execution_id=task_execution_id,
        attempt_number=attempt_number,
        status=TaskAttemptStatus.FAILED,
        failure_tier=FailureTier.TIER_1_STRUCTURAL,
        failure_reason=failure_reason,
        feedback_provided="Fix the output schema",
    )
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


class TestGetRecentTaskExecutions:
    @pytest.mark.asyncio
    async def test_returns_executions_for_project(
        self, history_service, db_session,
    ):
        mission = await _create_mission(db_session, mission_id=_MID("proj-exec"))
        await _create_execution(
            db_session, mission.id, task_id="t1", domain_tags=["api"],
        )
        await _create_execution(
            db_session, mission.id, task_id="t2", domain_tags=["auth"],
        )

        results = await history_service.get_recent_task_executions(_MID("proj-exec"))
        assert len(results) == 2
        assert all(r["agent_name"] == "analyzer" for r in results)

    @pytest.mark.asyncio
    async def test_filters_by_domain_tags(self, history_service, db_session):
        mission = await _create_mission(db_session, mission_id=_MID("proj-tags"))
        await _create_execution(
            db_session, mission.id, task_id="t1", domain_tags=["api", "auth"],
        )
        await _create_execution(
            db_session, mission.id, task_id="t2", domain_tags=["frontend"],
        )

        results = await history_service.get_recent_task_executions(
            _MID("proj-tags"), domain_tags=["auth"],
        )
        assert len(results) == 1
        assert results[0]["task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_respects_limit(self, history_service, db_session):
        mission = await _create_mission(db_session, mission_id=_MID("proj-limit"))
        for i in range(5):
            await _create_execution(
                db_session, mission.id, task_id=f"t{i}",
            )

        results = await history_service.get_recent_task_executions(
            _MID("proj-limit"), limit=2,
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_for_unknown_project(self, history_service):
        results = await history_service.get_recent_task_executions(_NIL_UUID)
        assert results == []

    @pytest.mark.asyncio
    async def test_excludes_other_projects(self, history_service, db_session):
        m1 = await _create_mission(db_session, mission_id=_MID("proj-a"))
        m2 = await _create_mission(db_session, mission_id=_MID("proj-b"))
        await _create_execution(db_session, m1.id, task_id="a-task")
        await _create_execution(db_session, m2.id, task_id="b-task")

        results = await history_service.get_recent_task_executions(_MID("proj-a"))
        assert len(results) == 1
        assert results[0]["task_id"] == "a-task"


class TestGetRecentFailures:
    @pytest.mark.asyncio
    async def test_returns_failed_attempts(self, history_service, db_session):
        mission = await _create_mission(db_session, mission_id=_MID("proj-fail"))
        execution = await _create_execution(
            db_session, mission.id, domain_tags=["api"],
        )
        await _create_failed_attempt(
            db_session, execution.id, failure_reason="Missing required field",
        )

        failures = await history_service.get_recent_failures(_MID("proj-fail"))
        assert len(failures) == 1
        assert failures[0]["failure_reason"] == "Missing required field"
        assert failures[0]["failure_tier"] == FailureTier.TIER_1_STRUCTURAL

    @pytest.mark.asyncio
    async def test_filters_by_domain_tags(self, history_service, db_session):
        mission = await _create_mission(db_session, mission_id=_MID("proj-fail-tag"))
        exec_api = await _create_execution(
            db_session, mission.id, task_id="api-task", domain_tags=["api"],
        )
        exec_ui = await _create_execution(
            db_session, mission.id, task_id="ui-task", domain_tags=["frontend"],
        )
        await _create_failed_attempt(db_session, exec_api.id)
        await _create_failed_attempt(db_session, exec_ui.id)

        failures = await history_service.get_recent_failures(
            _MID("proj-fail-tag"), domain_tags=["api"],
        )
        assert len(failures) == 1
        assert failures[0]["task_id"] == "api-task"

    @pytest.mark.asyncio
    async def test_respects_limit(self, history_service, db_session):
        mission = await _create_mission(db_session, mission_id=_MID("proj-fail-lim"))
        execution = await _create_execution(db_session, mission.id)
        for i in range(5):
            await _create_failed_attempt(
                db_session, execution.id, attempt_number=i + 1,
            )

        failures = await history_service.get_recent_failures(
            _MID("proj-fail-lim"), limit=2,
        )
        assert len(failures) == 2

    @pytest.mark.asyncio
    async def test_empty_when_no_failures(self, history_service, db_session):
        mission = await _create_mission(db_session, mission_id=_MID("proj-ok"))
        await _create_execution(db_session, mission.id)

        failures = await history_service.get_recent_failures(_MID("proj-ok"))
        assert failures == []


class TestGetMissionSummaries:
    @pytest.mark.asyncio
    async def test_returns_summaries(self, history_service, db_session):
        await _create_mission(
            db_session, mission_id=_MID("proj-sum"), objective="Build API",
        )
        await _create_mission(
            db_session, mission_id=_MID("proj-sum"), objective="Fix auth",
            status=ExecutionRecordStatus.FAILED,
        )

        summaries = await history_service.get_mission_summaries(_MID("proj-sum"))
        assert len(summaries) == 2
        objectives = {s["objective"] for s in summaries}
        assert objectives == {"Build API", "Fix auth"}

    @pytest.mark.asyncio
    async def test_respects_limit(self, history_service, db_session):
        for i in range(5):
            await _create_mission(
                db_session, mission_id=_MID("proj-sum-lim"), objective=f"Mission {i}",
            )

        summaries = await history_service.get_mission_summaries(
            _MID("proj-sum-lim"), limit=3,
        )
        assert len(summaries) == 3

    @pytest.mark.asyncio
    async def test_empty_for_unknown_project(self, history_service):
        summaries = await history_service.get_mission_summaries(_NIL_UUID)
        assert summaries == []


class TestSummarizedFiltering:
    """Tests that summarized missions are excluded from default queries."""

    @pytest.mark.asyncio
    async def test_executions_exclude_summarized_by_default(
        self, history_service, db_session,
    ):
        m1 = await _create_mission(db_session, mission_id=_MID("proj-sf"))
        m2 = await _create_mission(db_session, mission_id=_MID("proj-sf"))
        m2.summarized = True
        await db_session.flush()

        await _create_execution(db_session, m1.id, task_id="active-task")
        await _create_execution(db_session, m2.id, task_id="summarized-task")

        results = await history_service.get_recent_task_executions(_MID("proj-sf"))
        assert len(results) == 1
        assert results[0]["task_id"] == "active-task"

    @pytest.mark.asyncio
    async def test_executions_include_summarized_when_requested(
        self, history_service, db_session,
    ):
        m1 = await _create_mission(db_session, mission_id=_MID("proj-sf2"))
        m2 = await _create_mission(db_session, mission_id=_MID("proj-sf2"))
        m2.summarized = True
        await db_session.flush()

        await _create_execution(db_session, m1.id, task_id="active")
        await _create_execution(db_session, m2.id, task_id="old")

        results = await history_service.get_recent_task_executions(
            _MID("proj-sf2"), include_summarized=True,
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_failures_exclude_summarized_by_default(
        self, history_service, db_session,
    ):
        m1 = await _create_mission(db_session, mission_id=_MID("proj-sf3"))
        m2 = await _create_mission(db_session, mission_id=_MID("proj-sf3"))
        m2.summarized = True
        await db_session.flush()

        e1 = await _create_execution(db_session, m1.id, task_id="active")
        e2 = await _create_execution(db_session, m2.id, task_id="old")
        await _create_failed_attempt(db_session, e1.id)
        await _create_failed_attempt(db_session, e2.id)

        failures = await history_service.get_recent_failures(_MID("proj-sf3"))
        assert len(failures) == 1
        assert failures[0]["task_id"] == "active"

    @pytest.mark.asyncio
    async def test_mission_summaries_exclude_summarized_by_default(
        self, history_service, db_session,
    ):
        m1 = await _create_mission(
            db_session, mission_id=_MID("proj-sf4"), objective="Active",
        )
        m2 = await _create_mission(
            db_session, mission_id=_MID("proj-sf4"), objective="Old",
        )
        m2.summarized = True
        await db_session.flush()

        summaries = await history_service.get_mission_summaries(_MID("proj-sf4"))
        assert len(summaries) == 1
        assert summaries[0]["objective"] == "Active"

    @pytest.mark.asyncio
    async def test_mission_summaries_include_summarized_when_requested(
        self, history_service, db_session,
    ):
        m1 = await _create_mission(
            db_session, mission_id=_MID("proj-sf5"), objective="Active",
        )
        m2 = await _create_mission(
            db_session, mission_id=_MID("proj-sf5"), objective="Old",
        )
        m2.summarized = True
        await db_session.flush()

        summaries = await history_service.get_mission_summaries(
            _MID("proj-sf5"), include_summarized=True,
        )
        assert len(summaries) == 2
