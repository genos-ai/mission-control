"""Per-task loaders in mission_plan_taskio (Plan 88, 88.2.3).

task_definition_from_row builds one TaskDefinition from a Task row, and
load_dependency_outputs reads the outputs of a task's direct dependencies.
load_prior_outputs is bounded to one run and assert_run_local_dependencies
rejects run tasks that depend on unfinished tasks outside the run (88.3.5).
Runs against the real test database (P12).
"""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from modules.backend.core.exceptions import ValidationError
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import MissionRun, MissionRunStatus, MissionRunTrigger
from modules.backend.models.task import Task, TaskDependency, TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.task_plan import TaskDefinition
from modules.backend.services.mission_plan_taskio import (
    assert_run_local_dependencies,
    load_dependency_outputs,
    load_prior_outputs,
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
async def test_load_dependency_outputs_skips_failed_dependency_with_stale_output(db_session):
    """A dependency that completed once, then failed on a re-run, keeps its old result_summary."""
    ids = await _seed(db_session)
    task_a = await db_session.get(Task, ids["a"])
    task_a.status = TaskStatus.FAILED
    await db_session.flush()

    outputs = await load_dependency_outputs(db_session, ids["c"])

    assert outputs == {ids["b"]: {"result": "plain text"}}


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


async def _two_run_seed(db_session) -> dict[str, str]:
    """Runs 1 (succeeded) and 2 (running) of one mission, each with a COMPLETED task."""
    mission_id = str(uuid4())
    plan_id = str(uuid4())
    db_session.add(
        Mission(id=mission_id, name=f"taskio-{mission_id}", description="t", owner_id=str(uuid4()))
    )
    db_session.add(MissionPlan(id=plan_id, mission_id=mission_id, gate_mode=GateMode.AUTONOMOUS))
    await db_session.flush()
    ids = {"mission": mission_id, "plan": plan_id}
    for seq, status in ((1, MissionRunStatus.SUCCEEDED), (2, MissionRunStatus.RUNNING)):
        run = MissionRun(
            mission_id=mission_id,
            plan_id=plan_id,
            sequence=seq,
            trigger=MissionRunTrigger.MANUAL,
            status=status,
        )
        db_session.add(run)
        await db_session.flush()
        ids[f"run{seq}"] = run.id
        ids[f"done{seq}"] = await _add_task(
            db_session, ids, run.id, TaskStatus.COMPLETED, json.dumps({"result": f"run {seq}"})
        )
    return ids


async def _add_task(db_session, ids, run_id, status, summary=None) -> str:
    task_id = str(uuid4())
    db_session.add(
        Task(
            id=task_id,
            mission_id=ids["mission"],
            plan_id=ids["plan"],
            mission_run_id=run_id,
            agent="agent_a",
            description="t",
            instructions="Do it",
            status=status,
            result_summary=summary,
        )
    )
    await db_session.flush()
    return task_id


async def _depend(db_session, task_id: str, depends_on_id: str) -> None:
    db_session.add(TaskDependency(id=str(uuid4()), task_id=task_id, depends_on_id=depends_on_id))
    await db_session.flush()


@pytest.mark.asyncio
async def test_load_prior_outputs_only_current_run(db_session):
    ids = await _two_run_seed(db_session)
    orchestrator = SimpleNamespace(_task_repo=TaskRepository(db_session))

    outputs = await load_prior_outputs(orchestrator, ids["run2"])

    assert outputs == {ids["done2"]: {"result": "run 2"}}


@pytest.mark.asyncio
async def test_dependency_on_unfinished_task_of_other_run_rejected(db_session):
    ids = await _two_run_seed(db_session)
    foreign = await _add_task(db_session, ids, ids["run1"], TaskStatus.FAILED)
    task = await _add_task(db_session, ids, ids["run2"], TaskStatus.APPROVED)
    await _depend(db_session, task, foreign)

    with pytest.raises(ValidationError) as err:
        await assert_run_local_dependencies(TaskRepository(db_session), ids["run2"])

    assert str(err.value) == (
        f"Task {task} depends on unfinished task {foreign} outside run {ids['run2']}"
    )


@pytest.mark.asyncio
async def test_dependency_on_unfinished_backlog_task_rejected(db_session):
    ids = await _two_run_seed(db_session)
    backlog = await _add_task(db_session, ids, None, TaskStatus.APPROVED)
    task = await _add_task(db_session, ids, ids["run2"], TaskStatus.APPROVED)
    await _depend(db_session, task, backlog)

    with pytest.raises(ValidationError):
        await assert_run_local_dependencies(TaskRepository(db_session), ids["run2"])


@pytest.mark.asyncio
async def test_dependency_on_completed_task_of_earlier_run_allowed(db_session):
    ids = await _two_run_seed(db_session)
    task = await _add_task(db_session, ids, ids["run2"], TaskStatus.APPROVED)
    await _depend(db_session, task, ids["done1"])
    local = await _add_task(db_session, ids, ids["run2"], TaskStatus.APPROVED)
    await _depend(db_session, local, task)

    await assert_run_local_dependencies(TaskRepository(db_session), ids["run2"])
