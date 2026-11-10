"""Per-task loaders in mission_plan_taskio (Plan 88, 88.2.3).

task_definition_from_row builds one TaskDefinition from a Task row, and
load_dependency_outputs reads the outputs of a task's direct dependencies.
Runs against the real test database (P12).
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.task import Task, TaskDependency, TaskStatus
from modules.backend.schemas.task_plan import TaskDefinition
from modules.backend.services.mission_plan_taskio import (
    load_dependency_outputs,
    task_definition_from_row,
)


async def _seed(db_session) -> dict[str, str]:
    """A mission plan with tasks a, b (both upstream of c) and an unrelated d."""
    mission_id = str(uuid4())
    plan_id = str(uuid4())
    ids = {name: str(uuid4()) for name in ("a", "b", "c", "d")}
    db_session.add(
        Mission(id=mission_id, name=f"taskio-{mission_id}", description="t", owner_id=str(uuid4()))
    )
    db_session.add(MissionPlan(id=plan_id, mission_id=mission_id, gate_mode=GateMode.AUTONOMOUS))
    summaries = {
        "a": json.dumps({"result": "from a"}),
        "b": "plain text",
        "c": None,
        "d": json.dumps({"result": "unrelated"}),
    }
    for name, task_id in ids.items():
        db_session.add(
            Task(
                id=task_id,
                mission_id=mission_id,
                plan_id=plan_id,
                agent="agent_a",
                description=f"task {name}",
                instructions="Do it",
                status=TaskStatus.COMPLETED if summaries[name] else TaskStatus.APPROVED,
                result_summary=summaries[name],
            )
        )
    await db_session.flush()
    for upstream in ("a", "b"):
        db_session.add(
            TaskDependency(id=str(uuid4()), task_id=ids["c"], depends_on_id=ids[upstream])
        )
    await db_session.flush()
    return ids


@pytest.mark.asyncio
async def test_load_dependency_outputs_reads_direct_dependencies(db_session):
    ids = await _seed(db_session)

    outputs = await load_dependency_outputs(db_session, ids["c"])

    assert outputs == {ids["a"]: {"result": "from a"}, ids["b"]: {"result": "plain text"}}


@pytest.mark.asyncio
async def test_load_dependency_outputs_empty_without_dependencies(db_session):
    ids = await _seed(db_session)

    assert await load_dependency_outputs(db_session, ids["a"]) == {}


@pytest.mark.asyncio
async def test_task_definition_from_row(db_session):
    ids = await _seed(db_session)
    row = (
        await db_session.execute(
            select(Task).where(Task.id == ids["c"]).options(selectinload(Task.dependencies))
        )
    ).scalar_one()

    definition = task_definition_from_row(row)

    assert isinstance(definition, TaskDefinition)
    assert definition.task_id == ids["c"]
    assert definition.agent == "agent_a"
    assert sorted(definition.dependencies) == sorted([ids["a"], ids["b"]])
