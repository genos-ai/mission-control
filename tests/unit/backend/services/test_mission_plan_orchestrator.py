"""Tests for the pure/DB-only helpers of MissionPlanOrchestrator (Plan 84 Phase 2.3).

No LLM calls — targets the deterministic reconciliation, persistence, and
write-back logic. Uses real db_session per P12 (test against real
infrastructure), matching the sibling test_run_objective.py fixtures.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.protocols import NoOpEventBus
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.task import Task, TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.task_plan import TaskDefinition, TaskPlan
from modules.backend.services import mission_plan_taskio
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mission_context(db_session: AsyncSession, test_user) -> dict:
    """Create a real mission owned by the shared test user."""
    m = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for orchestrator helpers",
        owner_id=test_user.id,
    )
    db_session.add(m)
    await db_session.flush()
    db_session.add(
        MissionPlan(
            mission_id=m.id,
            gate_mode=GateMode.AUTONOMOUS,
            budget_per_run_usd=5.0,
            budget_per_month_usd=100.0,
            budget_lifetime_usd=10.0,
        )
    )
    await db_session.flush()
    return {"mission_id": m.id, "user_id": test_user.id}


@pytest.fixture
def mission_id(mission_context: dict) -> str:
    return mission_context["mission_id"]


@pytest.fixture
def orchestrator(db_session: AsyncSession) -> MissionPlanOrchestrator:
    return MissionPlanOrchestrator(db_session, event_bus=NoOpEventBus())


@pytest.fixture
def service(db_session: AsyncSession) -> MissionPlanService:
    return MissionPlanService(db_session)


@pytest.fixture
async def plan(service: MissionPlanService, mission_id: str) -> MissionPlan:
    return await service.get_or_create_plan(mission_id)


async def _make_task(
    db_session: AsyncSession,
    plan: MissionPlan,
    *,
    status: TaskStatus,
    description: str = "A task",
) -> Task:
    repo = TaskRepository(db_session)
    return await repo.create_task(
        plan_id=plan.id,
        mission_id=plan.mission_id,
        agent="system.summarization.agent",
        description=description,
        status=status,
    )


# ---------------------------------------------------------------------------
# _reconcile_tasks
# ---------------------------------------------------------------------------


class TestReconcileTasks:
    @pytest.mark.asyncio
    async def test_new_created_removed_cancelled_completed_untouched(
        self,
        orchestrator: MissionPlanOrchestrator,
        plan: MissionPlan,
        db_session: AsyncSession,
    ):
        continuing = await _make_task(db_session, plan, status=TaskStatus.PROPOSED)
        completed = await _make_task(db_session, plan, status=TaskStatus.COMPLETED)
        stale = await _make_task(db_session, plan, status=TaskStatus.QUEUED)
        await db_session.flush()

        new_task_id = str(uuid.uuid4())
        new_plan = TaskPlan(
            mission_id=plan.mission_id,
            tasks=[
                TaskDefinition(
                    task_id=continuing.id,
                    agent="system.summarization.agent",
                    description="Updated description",
                ),
                TaskDefinition(
                    task_id=new_task_id,
                    agent="system.summarization.agent",
                    description="Brand new task",
                ),
            ],
        )

        stats = await mission_plan_taskio.reconcile_tasks(
            orchestrator, plan, new_plan, mission_run_id=None
        )

        assert stats == {"cancelled": 1, "new": 1, "updated": 1}

        repo = TaskRepository(db_session)
        by_id = {t.id: t for t in await repo.get_by_plan_id(plan.id)}

        # Continuing task: updated in place, status untouched
        assert by_id[continuing.id].description == "Updated description"
        assert by_id[continuing.id].status == TaskStatus.PROPOSED

        # Removed non-terminal task: cancelled
        assert by_id[stale.id].status == TaskStatus.CANCELLED

        # Removed terminal (completed) task: untouched
        assert by_id[completed.id].status == TaskStatus.COMPLETED

        # New task: created as PROPOSED
        assert by_id[new_task_id].status == TaskStatus.PROPOSED
        assert by_id[new_task_id].description == "Brand new task"


# ---------------------------------------------------------------------------
# _persist_plan
# ---------------------------------------------------------------------------


class TestPersistPlan:
    @pytest.mark.asyncio
    async def test_bumps_version_and_persists_metadata(
        self,
        orchestrator: MissionPlanOrchestrator,
        plan: MissionPlan,
    ):
        original_version = plan.version
        candidate = TaskPlan(
            mission_id=plan.mission_id,
            summary="New plan summary",
            estimated_cost_usd=12.5,
            estimated_duration_seconds=600,
            tasks=[
                TaskDefinition(
                    task_id=str(uuid.uuid4()),
                    agent="system.summarization.agent",
                    description="Only task",
                )
            ],
        )

        stats = await orchestrator._persist_plan(plan, candidate, mission_run_id=None)

        assert stats["new"] == 1
        assert plan.version == original_version + 1
        assert plan.summary == "New plan summary"
        assert plan.estimated_cost_usd == 12.5
        assert plan.estimated_duration == 600
