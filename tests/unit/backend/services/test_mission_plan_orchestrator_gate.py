"""Gate handling in MissionPlanOrchestrator.run_objective (Plan 88 steps 88.0.5, 88.1.0).

refine() is patched to create real PROPOSED task rows; everything else
runs against the real db_session.
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.protocols import NoOpEventBus
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator


@pytest.fixture
async def mission_context(db_session: AsyncSession, test_user) -> dict:
    """A real mission with a MANUAL plan, owned by the shared test user."""
    m = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for fail-closed gate handling",
        owner_id=test_user.id,
        budget_ceiling_usd=10.0,
    )
    db_session.add(m)
    await db_session.flush()
    db_session.add(MissionPlan(mission_id=m.id, gate_mode=GateMode.MANUAL, budget_usd_ceiling=10.0))
    await db_session.flush()
    return {"mission_id": m.id, "user_id": test_user.id}


@pytest.fixture
def orchestrator(db_session: AsyncSession) -> MissionPlanOrchestrator:
    return MissionPlanOrchestrator(db_session, event_bus=NoOpEventBus())


def _mock_refine(orchestrator: MissionPlanOrchestrator, db_session: AsyncSession, count: int):
    """refine() replacement: persist ``count`` PROPOSED tasks and bump the version."""

    async def mock_refine(plan_id, instructions, uid, **kwargs):
        plan = await orchestrator._repo.get_by_id(plan_id)
        repo = TaskRepository(db_session)
        for i in range(count):
            await repo.create_task(
                plan_id=plan.id,
                mission_id=plan.mission_id,
                agent="system.summarization.agent",
                description=f"Test task {i + 1}",
                instructions=f"Do thing {i + 1}",
                status=TaskStatus.PROPOSED,
            )
        plan.version += 1
        await db_session.flush()
        await db_session.refresh(plan, ["tasks"])
        return plan

    return mock_refine


@pytest.mark.asyncio
async def test_run_objective_rejects_invalid_gate_mode_override(
    orchestrator: MissionPlanOrchestrator, mission_context: dict
):
    with pytest.raises(ValidationError):
        await orchestrator.run_objective(
            mission_id=mission_context["mission_id"],
            objective="Test objective",
            user_id=mission_context["user_id"],
            gate_mode="bogus",
        )


@pytest.mark.asyncio
async def test_run_objective_manual_gate_mode_leaves_tasks_proposed(
    orchestrator: MissionPlanOrchestrator,
    mission_context: dict,
    db_session: AsyncSession,
):
    with patch.object(
        orchestrator, "refine", side_effect=_mock_refine(orchestrator, db_session, 2)
    ):
        result = await orchestrator.run_objective(
            mission_id=mission_context["mission_id"],
            objective="Test objective",
            user_id=mission_context["user_id"],
        )

    assert result["outcome_status"] == "awaiting_approval"
    tasks = await TaskRepository(db_session).get_by_plan_id(result["plan_id"])
    assert len(tasks) == 2
    assert all(t.status == TaskStatus.PROPOSED for t in tasks)
