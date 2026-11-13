"""Tests for WorkflowRunService._persist_workflow_as_plan (Plan 88 step 88.0.6).

The plan's gate_mode is never rewritten by a workflow run, and only an
autonomous plan auto-approves the materialised tasks.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.workflow import WorkflowSchema
from modules.backend.services.workflow_run import WorkflowRunService


def _workflow() -> WorkflowSchema:
    return WorkflowSchema(
        workflow_name="test.persist.workflow",
        description="Two agent steps",
        objective={
            "statement": "Test objective",
            "category": "testing",
            "owner": "test-owner",
            "priority": "normal",
        },
        steps=[
            {"id": "step-one", "capability": "test.step_one"},
            {"id": "step-two", "capability": "test.step_two", "depends_on": ["step-one"]},
        ],
    )


async def _persist(db_session: AsyncSession, owner_id: str, gate_mode: GateMode):
    """Create a mission with the given gate_mode, persist the workflow, return (plan, tasks)."""
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Test mission for _persist_workflow_as_plan",
        owner_id=owner_id,
    )
    db_session.add(mission)
    await db_session.flush()
    plan = MissionPlan(
        mission_id=mission.id,
        gate_mode=gate_mode,
        budget_per_run_usd=5.0,
        budget_per_month_usd=100.0,
        budget_lifetime_usd=10.0,
    )
    db_session.add(plan)
    await db_session.flush()

    step_map = await WorkflowRunService(db_session)._persist_workflow_as_plan(
        mission.id, _workflow(), {}
    )
    assert len(step_map) == 2

    await db_session.refresh(plan)
    tasks = await TaskRepository(db_session).get_by_plan_id(plan.id)
    assert len(tasks) == 2
    return plan, tasks


@pytest.mark.asyncio
async def test_autonomous_gate_mode_preserved(db_session: AsyncSession, test_user):
    plan, _ = await _persist(db_session, test_user.id, GateMode.AUTONOMOUS)

    assert plan.gate_mode == GateMode.AUTONOMOUS


@pytest.mark.asyncio
async def test_autonomous_auto_approves_tasks(db_session: AsyncSession, test_user):
    _, tasks = await _persist(db_session, test_user.id, GateMode.AUTONOMOUS)

    assert {t.status for t in tasks} == {TaskStatus.APPROVED}


@pytest.mark.asyncio
async def test_manual_leaves_tasks_proposed(db_session: AsyncSession, test_user):
    plan, tasks = await _persist(db_session, test_user.id, GateMode.MANUAL)

    assert plan.gate_mode == GateMode.MANUAL
    assert {t.status for t in tasks} == {TaskStatus.PROPOSED}


@pytest.mark.asyncio
async def test_interactive_leaves_tasks_proposed(db_session: AsyncSession, test_user):
    _, tasks = await _persist(db_session, test_user.id, GateMode.INTERACTIVE)

    assert {t.status for t in tasks} == {TaskStatus.PROPOSED}
