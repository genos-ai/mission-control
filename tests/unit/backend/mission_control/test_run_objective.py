"""Tests for the MissionPlanService helpers the Plan 62 execution path used.

run_objective itself was deleted in Plan 88 step 88.1.7 (runs start through
MissionRunService). Covers the concurrency guard, approve_all_proposed and
the plan budget inherited from the mission. Uses real db_session per
project testing principles.

Plan 72 contract: tasks are first-class rows in the `tasks` table with
native UUID ids, created via TaskRepository. plan_task_states and
MissionPlan.task_plan_json no longer exist.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.task import Task, TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.services.mission_plan import MissionPlanService

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
        budget_ceiling_usd=10.0,
    )
    db_session.add(m)
    await db_session.flush()
    db_session.add(
        MissionPlan(mission_id=m.id, gate_mode=GateMode.AUTONOMOUS, budget_usd_ceiling=10.0)
    )
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
# Plan budget
# ---------------------------------------------------------------------------


class TestPlanBudget:
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
