"""Tests for MissionPlanOrchestrator.run_objective() — Plan 62 unified execution path.

Tests concurrency guard, gate mode handling, async dispatch, budget
propagation, and approve_all_proposed. Uses real db_session per project
testing principles.

Plan 72 contract: tasks are first-class rows in the `tasks` table with
native UUID ids, created via TaskRepository. plan_task_states and
MissionPlan.task_plan_json no longer exist.
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError
from modules.backend.core.protocols import NoOpEventBus
from modules.backend.models.mission_plan import MissionPlan
from modules.backend.models.task import Task, TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.services import mission_plan_dispatch
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mission_context(db_session: AsyncSession, test_user) -> dict:
    """Create a real mission owned by the shared test user."""
    from modules.backend.models.mission import Mission

    m = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for run_objective",
        owner_id=test_user.id,
        gate_mode="autonomous",
        budget_ceiling_usd=10.0,
    )
    db_session.add(m)
    await db_session.flush()
    return {"mission_id": m.id, "user_id": test_user.id}


@pytest.fixture
def mission_id(mission_context: dict) -> str:
    return mission_context["mission_id"]


@pytest.fixture
def user_id(mission_context: dict) -> str:
    return mission_context["user_id"]


@pytest.fixture
def service(db_session: AsyncSession) -> MissionPlanService:
    return MissionPlanService(db_session)


@pytest.fixture
def orchestrator(db_session: AsyncSession) -> MissionPlanOrchestrator:
    return MissionPlanOrchestrator(db_session, event_bus=NoOpEventBus())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_tasks(
    db_session: AsyncSession,
    plan: MissionPlan,
    count: int,
    *,
    status: TaskStatus = TaskStatus.PROPOSED,
    chain: bool = True,
) -> list[Task]:
    """Create N Task rows for the plan (Plan 72: real rows, UUID ids).

    When chain=True each task depends on the previous one.
    """
    repo = TaskRepository(db_session)
    tasks: list[Task] = []
    for i in range(count):
        task = await repo.create_task(
            plan_id=plan.id,
            mission_id=plan.mission_id,
            agent="system.summarization.agent",
            description=f"Test task {i + 1}",
            instructions=f"Do thing {i + 1}",
            status=status,
        )
        if chain and tasks:
            await repo.set_dependencies(task.id, [tasks[-1].id])
        tasks.append(task)
    return tasks


def _mock_refine(orchestrator, db_session, task_count, created_tasks=None):
    """Build a refine() replacement that creates real Task rows.

    Mirrors the documented refine() contract: persist PROPOSED tasks,
    bump the plan version, and return the plan with its tasks
    relationship freshly loaded. The explicit relationship refresh is
    needed because the identity-mapped plan was loaded (with an empty
    tasks collection) by get_or_create_plan earlier in the same session.
    """

    async def mock_refine(plan_id, instructions, uid, **kwargs):
        plan = await orchestrator._repo.get_by_id(plan_id)
        tasks = await _create_tasks(db_session, plan, task_count)
        if created_tasks is not None:
            created_tasks.extend(tasks)
        plan.version += 1
        await db_session.flush()
        await db_session.refresh(plan, ["tasks"])
        return plan

    return mock_refine


# ---------------------------------------------------------------------------
# Concurrency guard
# ---------------------------------------------------------------------------


class TestConcurrencyGuard:
    @pytest.mark.asyncio
    async def test_rejects_when_queued_tasks(
        self,
        service: MissionPlanService,
        mission_id: str,
        db_session: AsyncSession,
    ):
        """ConflictError raised when plan has tasks in QUEUED state."""
        plan = await service.get_or_create_plan(mission_id)
        await _create_tasks(db_session, plan, 1, status=TaskStatus.QUEUED)

        with pytest.raises(ConflictError, match="in-progress"):
            await service.check_no_active_tasks(plan.id)

    @pytest.mark.asyncio
    async def test_rejects_when_running_tasks(
        self,
        service: MissionPlanService,
        mission_id: str,
        db_session: AsyncSession,
    ):
        """ConflictError raised when plan has tasks in RUNNING state."""
        plan = await service.get_or_create_plan(mission_id)
        await _create_tasks(db_session, plan, 1, status=TaskStatus.RUNNING)

        with pytest.raises(ConflictError, match="in-progress"):
            await service.check_no_active_tasks(plan.id)

    @pytest.mark.asyncio
    async def test_allows_when_only_terminal_tasks(
        self,
        service: MissionPlanService,
        mission_id: str,
        db_session: AsyncSession,
    ):
        """No error when all tasks are in terminal states."""
        plan = await service.get_or_create_plan(mission_id)
        await _create_tasks(db_session, plan, 1, status=TaskStatus.COMPLETED)

        # Should not raise
        await service.check_no_active_tasks(plan.id)

    @pytest.mark.asyncio
    async def test_allows_empty_plan(
        self,
        service: MissionPlanService,
        mission_id: str,
    ):
        """No error when plan has no tasks at all."""
        plan = await service.get_or_create_plan(mission_id)
        await service.check_no_active_tasks(plan.id)


# ---------------------------------------------------------------------------
# approve_all_proposed
# ---------------------------------------------------------------------------


class TestApproveAllProposed:
    @pytest.mark.asyncio
    async def test_approves_all_proposed_tasks(
        self,
        service: MissionPlanService,
        mission_id: str,
        user_id: str,
        db_session: AsyncSession,
    ):
        plan = await service.get_or_create_plan(mission_id)
        tasks = await _create_tasks(db_session, plan, 2)

        approved = await service.approve_all_proposed(plan.id, user_id)

        assert set(approved) == {t.id for t in tasks}
        for task in tasks:
            assert task.status == TaskStatus.APPROVED
            assert task.approved_by_user_id == user_id

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_proposed(
        self,
        service: MissionPlanService,
        mission_id: str,
        user_id: str,
    ):
        plan = await service.get_or_create_plan(mission_id)
        approved = await service.approve_all_proposed(plan.id, user_id)
        assert approved == []


# ---------------------------------------------------------------------------
# run_objective — interactive gate mode
# ---------------------------------------------------------------------------


class TestRunObjectiveInteractive:
    @pytest.mark.asyncio
    async def test_interactive_stops_after_refine(
        self,
        orchestrator: MissionPlanOrchestrator,
        mission_id: str,
        user_id: str,
        db_session: AsyncSession,
    ):
        """Interactive gate mode creates plan but does not dispatch."""
        mock_refine = _mock_refine(orchestrator, db_session, task_count=2)

        with patch.object(orchestrator, "refine", side_effect=mock_refine):
            result = await orchestrator.run_objective(
                mission_id=mission_id,
                objective="Test objective",
                user_id=user_id,
                gate_mode="interactive",
            )

        assert result["outcome_status"] == "awaiting_approval"
        assert result["task_count"] == 2
        assert result["dispatched_task_ids"] == []
        assert result["total_cost_usd"] == 0.0

        # Tasks stay PROPOSED — nothing was approved or dispatched
        tasks = await TaskRepository(db_session).get_by_plan_id(result["plan_id"])
        assert len(tasks) == 2
        assert all(t.status == TaskStatus.PROPOSED for t in tasks)


# ---------------------------------------------------------------------------
# run_objective — async dispatch
# ---------------------------------------------------------------------------


class TestRunObjectiveDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_returns_dispatching(
        self,
        orchestrator: MissionPlanOrchestrator,
        mission_id: str,
        user_id: str,
        db_session: AsyncSession,
    ):
        """run_objective approves tasks and dispatches via Temporal."""
        created: list[Task] = []
        mock_refine = _mock_refine(orchestrator, db_session, task_count=1, created_tasks=created)

        async def mock_temporal(*args, **kwargs):
            return "mock-workflow-id"

        with (
            patch.object(orchestrator, "refine", side_effect=mock_refine),
            patch.object(
                mission_plan_dispatch, "start_temporal_run_workflow", side_effect=mock_temporal
            ),
        ):
            result = await orchestrator.run_objective(
                mission_id=mission_id,
                objective="Quick task",
                user_id=user_id,
            )

        assert result["outcome_status"] == "dispatching"
        assert result["workflow_id"] == "mock-workflow-id"
        assert result["plan_id"] is not None
        assert result["dispatched_task_ids"] == [created[0].id]
        assert created[0].status == TaskStatus.APPROVED


# ---------------------------------------------------------------------------
# run_objective — budget propagation
# ---------------------------------------------------------------------------


class TestRunObjectiveBudget:
    @pytest.mark.asyncio
    async def test_budget_inherited_from_mission(
        self,
        service: MissionPlanService,
        mission_id: str,
        db_session: AsyncSession,
    ):
        """Budget ceiling propagates from mission to plan."""
        plan = await service.get_or_create_plan(mission_id)
        assert plan.budget_usd_ceiling == 10.0  # inherited from fixture

    @pytest.mark.asyncio
    async def test_budget_override(
        self,
        orchestrator: MissionPlanOrchestrator,
        service: MissionPlanService,
        mission_id: str,
        user_id: str,
        db_session: AsyncSession,
    ):
        """Explicit budget_ceiling_usd overrides mission default."""
        mock_refine = _mock_refine(orchestrator, db_session, task_count=1)

        async def mock_temporal(*args, **kwargs):
            return "mock-workflow-id"

        with (
            patch.object(orchestrator, "refine", side_effect=mock_refine),
            patch.object(
                mission_plan_dispatch, "start_temporal_run_workflow", side_effect=mock_temporal
            ),
        ):
            await orchestrator.run_objective(
                mission_id=mission_id,
                objective="Budget test",
                user_id=user_id,
                budget_ceiling_usd=25.0,
            )

        # Verify plan has the overridden budget
        plan = await service.get_or_create_plan(mission_id)
        assert plan.budget_usd_ceiling == 25.0
