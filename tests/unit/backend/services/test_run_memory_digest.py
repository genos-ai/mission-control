"""Tests for RunMemoryService.write_digest and get_digest (Plan 88, 88.3.7).

Runs against the real test database (P12). Most tests use the rolled-back
db_session, where the service's commits stay inside the test transaction.
The row-lock test needs rows a second connection can see, so it commits and
deletes its own rows. The narrator is an AsyncMock.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.core import security
from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ExternalServiceError, MissionRunStateError
from modules.backend.core.utils import utc_now
from modules.backend.models.execution_record import (
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskExecution,
)
from modules.backend.models.mission import Mission
from modules.backend.models.mission_artifact import MissionArtifact
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_run_digest import DigestGenerator
from modules.backend.models.task import Task, TaskStatus
from modules.backend.models.user import User
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.run_memory import (
    DigestHeadlineOut,
    DigestNarrative,
    DigestOpenItemOut,
)
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.services.run_memory import RunMemoryService
from tests.conftest import TEST_USER_ID

_MOD = "modules.backend.services.run_memory"
_AGENT = "system.summarization.agent"
_END = {
    "status": MissionRunStatus.SUCCEEDED,
    "reason": MissionRunStatusReason.NO_FURTHER_WORK,
}


async def _mission(db: AsyncSession, owner_id: str = TEST_USER_ID) -> tuple[str, str]:
    mission_id, plan_id = str(uuid4()), str(uuid4())
    db.add(Mission(id=mission_id, name=f"dig-{mission_id}", description="t", owner_id=owner_id))
    db.add(MissionPlan(id=plan_id, mission_id=mission_id, gate_mode=GateMode.AUTONOMOUS))
    await db.flush()
    return mission_id, plan_id


async def _run(
    db: AsyncSession,
    mission_id: str,
    plan_id: str,
    *,
    status: MissionRunStatus = MissionRunStatus.RUNNING,
    start: int | None = 0,
    objective: str | None = None,
) -> str:
    run = MissionRun(
        mission_id=mission_id,
        plan_id=plan_id,
        sequence=1,
        trigger=MissionRunTrigger.MANUAL,
        status=status,
        context_version_start=start,
        started_at=utc_now() if start is not None else None,
        objective=objective,
    )
    db.add(run)
    await db.flush()
    return run.id


async def _task(
    db: AsyncSession,
    mission_id: str,
    plan_id: str,
    run_id: str,
    status: TaskStatus,
    *,
    result_summary: str | None = None,
    failure_reason: str | None = None,
    description: str | None = None,
) -> str:
    task = await TaskRepository(db).create_task(
        plan_id=plan_id,
        mission_id=mission_id,
        agent=_AGENT,
        description=description or f"{status.value} task",
        status=status,
        mission_run_id=run_id,
    )
    task.result_summary = result_summary
    task.failure_reason = failure_reason
    await db.flush()
    return task.id


@pytest.fixture
async def mission(test_user, db_session: AsyncSession) -> tuple[str, str]:
    return await _mission(db_session)


def _narrator(narrative: DigestNarrative | None = None, cost: float = 0.12) -> AsyncMock:
    narrative = narrative or DigestNarrative(summary="Narrated.", open_items=[], headlines=[])
    return AsyncMock(return_value=(narrative, cost))


@pytest.mark.asyncio
async def test_digest_written_once_and_replay_returns_same_row(db_session, mission):
    run_id = await _run(db_session, *mission)
    narrator = _narrator()
    svc = RunMemoryService(db_session)

    first = await svc.write_digest(run_id, narrator=narrator, **_END)
    second = await svc.write_digest(run_id, narrator=narrator, **_END)

    assert first.id == second.id
    assert narrator.await_count == 1
    assert DigestGenerator(first.generator) == DigestGenerator.AGENT
    assert float(first.generation_cost_usd) == pytest.approx(0.12)
    assert first.schema_version == 1


@pytest.mark.asyncio
async def test_no_narrator_makes_no_llm_call(db_session, mission):
    run_id = await _run(db_session, *mission)

    digest = await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    assert DigestGenerator(digest.generator) == DigestGenerator.DETERMINISTIC
    assert float(digest.generation_cost_usd) == 0
    assert digest.summary.startswith("Run #1 ended succeeded (no_further_work). 0/0 tasks")


@pytest.mark.asyncio
async def test_narrator_failure_falls_back_to_deterministic(db_session, mission):
    run_id = await _run(db_session, *mission)
    narrator = AsyncMock(side_effect=ExternalServiceError("provider down"))
    bus = AsyncMock()

    digest = await RunMemoryService(db_session, event_bus=bus).write_digest(
        run_id, narrator=narrator, **_END
    )

    narrator.assert_awaited_once()
    events = [c.args[1] for c in bus.publish_to_mission.await_args_list]
    assert [e.event_type for e in events] == [
        "system.info",
        "mission_run.digest_written",
    ]
    assert events[0].level == "warning"
    assert events[1].generator == "deterministic"
    assert DigestGenerator(digest.generator) == DigestGenerator.DETERMINISTIC
    assert float(digest.generation_cost_usd) == 0
    assert digest.summary.startswith("Run #1 ended")


@pytest.mark.asyncio
async def test_narrative_merged_into_draft(db_session, mission):
    mission_id, plan_id = mission
    run_id = await _run(db_session, mission_id, plan_id, objective="Ship it")
    done = await _task(
        db_session,
        mission_id,
        plan_id,
        run_id,
        TaskStatus.COMPLETED,
        result_summary="raw",
    )
    failed = await _task(
        db_session,
        mission_id,
        plan_id,
        run_id,
        TaskStatus.FAILED,
        failure_reason="boom",
    )
    duplicate = f"{_AGENT} failed: boom"
    narrator = _narrator(
        DigestNarrative(
            summary="The run shipped half.",
            open_items=[
                DigestOpenItemOut(text=duplicate, source_task_id=failed),
                DigestOpenItemOut(text="Retry the failed task", source_task_id=failed),
            ],
            headlines=[DigestHeadlineOut(task_id=done, headline="Shipped the API")],
        )
    )

    digest = await RunMemoryService(db_session).write_digest(run_id, narrator=narrator, **_END)

    kwargs = narrator.await_args.kwargs
    assert kwargs["objective"] == "Ship it"
    assert kwargs["mission_run_id"] == run_id
    assert [e["task_id"] for e in kwargs["task_excerpts"]] == [done, failed]
    assert "Objective: Ship it" in kwargs["draft"]["summary"]
    assert digest.summary == "The run shipped half."
    assert [i["text"] for i in digest.open_items] == [
        duplicate,
        "Retry the failed task",
    ]
    headlines = {o["task_id"]: o["headline"] for o in digest.outcomes}
    assert headlines == {done: "Shipped the API", failed: "boom"}


@pytest.mark.asyncio
async def test_digest_context_changes_are_run_window(db_session, mission):
    mission_id, plan_id = mission
    manager = MissionContextManager(db_session)
    await manager.create_context(mission_id, "dig", "desc")
    _, current = await manager.get_context_with_version(mission_id)
    for v in range(current + 1, 7):
        await manager.apply_updates(
            mission_id,
            [
                {
                    "op": "add",
                    "path": f"architecture.components.c{v}",
                    "value": v,
                    "reason": "r",
                }
            ],
            agent_id="test",
            task_id=None,
            mission_run_id=None,
            reason="test",
        )
    run_id = await _run(db_session, mission_id, plan_id, start=3)

    digest = await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    assert [c["version"] for c in digest.context_changes] == [4, 5, 6]
    assert {c["change_type"] for c in digest.context_changes} == {"add"}


@pytest.mark.asyncio
async def test_sets_context_version_end(db_session, mission):
    mission_id, plan_id = mission
    await MissionContextManager(db_session).create_context(mission_id, "dig", "desc")
    run_id = await _run(db_session, mission_id, plan_id)

    await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    run = await db_session.get(MissionRun, run_id)
    await db_session.refresh(run)
    assert run.context_version_end == 1


@pytest.mark.asyncio
async def test_outcomes_capped_at_max_outcomes(db_session, mission):
    mission_id, plan_id = mission
    run_id = await _run(db_session, mission_id, plan_id)
    ids = [
        await _task(db_session, mission_id, plan_id, run_id, TaskStatus.COMPLETED) for _ in range(3)
    ]
    real = get_app_config().missions
    cfg = SimpleNamespace(
        missions=SimpleNamespace(
            digest=real.digest.model_copy(update={"max_outcomes": 2}),
            context_packet=real.context_packet,
        )
    )

    with patch(f"{_MOD}.get_app_config", return_value=cfg):
        digest = await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    assert [o["task_id"] for o in digest.outcomes] == ids[:2]
    assert digest.metrics["task_count"] == 3


@pytest.mark.asyncio
async def test_outcome_status_is_lowercase_value(db_session, mission):
    mission_id, plan_id = mission
    run_id = await _run(db_session, mission_id, plan_id)
    await _task(
        db_session,
        mission_id,
        plan_id,
        run_id,
        TaskStatus.COMPLETED,
        result_summary='{"summary": "Parsed headline", "result": "ignored"}',
    )

    digest = await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    assert digest.outcomes[0]["status"] == "completed"
    assert digest.outcomes[0]["headline"] == "Parsed headline"


@pytest.mark.asyncio
async def test_open_items_include_failed_and_unexecuted_tasks(db_session, mission):
    mission_id, plan_id = mission
    run_id = await _run(db_session, mission_id, plan_id)
    failed = await _task(
        db_session,
        mission_id,
        plan_id,
        run_id,
        TaskStatus.FAILED,
        failure_reason="timeout",
    )
    await _task(db_session, mission_id, plan_id, run_id, TaskStatus.COMPLETED)
    proposed = await _task(
        db_session,
        mission_id,
        plan_id,
        run_id,
        TaskStatus.PROPOSED,
        description="Write docs",
    )
    approved = await _task(
        db_session,
        mission_id,
        plan_id,
        run_id,
        TaskStatus.APPROVED,
        description="Deploy",
    )

    digest = await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    assert digest.open_items == [
        {"text": f"{_AGENT} failed: timeout", "source_task_id": failed},
        {"text": "Not executed: Write docs", "source_task_id": proposed},
        {"text": "Not executed: Deploy", "source_task_id": approved},
    ]
    assert digest.metrics["completed_task_count"] == 1
    assert digest.metrics["failed_task_count"] == 1


@pytest.mark.asyncio
async def test_decisions_empty_in_phase_3(db_session, mission):
    run_id = await _run(db_session, *mission)

    digest = await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    assert digest.decisions == []


@pytest.mark.asyncio
async def test_digest_rejected_for_pending_run(db_session, mission):
    run_id = await _run(db_session, *mission, status=MissionRunStatus.PENDING, start=None)
    narrator = _narrator()

    with pytest.raises(MissionRunStateError):
        await RunMemoryService(db_session).write_digest(run_id, narrator=narrator, **_END)
    narrator.assert_not_awaited()


@pytest.mark.asyncio
async def test_artifact_ids_linked_via_task_execution(db_session, mission):
    mission_id, plan_id = mission
    run_id = await _run(db_session, mission_id, plan_id)
    task_id = await _task(db_session, mission_id, plan_id, run_id, TaskStatus.COMPLETED)
    record = ExecutionRecord(
        mission_id=mission_id,
        mission_run_id=run_id,
        status=ExecutionRecordStatus.RUNNING,
    )
    db_session.add(record)
    await db_session.flush()
    execution = TaskExecution(
        execution_record_id=record.id,
        task_id=task_id,
        agent_name=_AGENT,
        status="completed",
        cost_usd=0.0,
        mission_run_id=run_id,
    )
    db_session.add(execution)
    await db_session.flush()
    artifact = MissionArtifact(
        mission_id=mission_id,
        task_execution_id=execution.id,
        agent_id=_AGENT,
        artifact_type="report",
        title="Report",
        content_type="markdown",
        content_text="body",
    )
    unlinked = MissionArtifact(
        mission_id=mission_id,
        agent_id=_AGENT,
        artifact_type="report",
        title="Other",
        content_type="markdown",
        content_text="body",
    )
    db_session.add_all([artifact, unlinked])
    await db_session.flush()

    digest = await RunMemoryService(db_session).write_digest(run_id, narrator=None, **_END)

    assert digest.outcomes[0]["artifact_ids"] == [artifact.id]


@pytest.mark.asyncio
async def test_get_digest_other_mission_returns_none(db_session, mission):
    run_id = await _run(db_session, *mission)
    other_mission, _ = await _mission(db_session)
    svc = RunMemoryService(db_session)
    digest = await svc.write_digest(run_id, narrator=None, **_END)

    assert (await svc.get_digest(mission[0], run_id)).id == digest.id
    assert await svc.get_digest(other_mission, run_id) is None


@pytest.mark.asyncio
async def test_no_row_lock_held_during_narrator_call(
    db_session_factory: async_sessionmaker[AsyncSession],
):
    """Committed rows, so a second connection can try to lock the run mid-call."""
    suffix = uuid4().hex
    async with db_session_factory() as setup:
        user = User(
            email=f"digest-{suffix}@test.dev",
            display_name="Digest Test",
            hashed_password=security.hash_password("digest-test-password"),
            system_role="user",
            is_active=True,
        )
        setup.add(user)
        await setup.flush()
        user_id = user.id
        mission_id, plan_id = await _mission(setup, owner_id=user_id)
        run_id = await _run(setup, mission_id, plan_id)
        await setup.commit()

    async def _lock_from_another_session(**_: object):
        async with db_session_factory() as other:
            locked = await other.execute(
                text("SELECT id FROM mission_runs WHERE id = :run FOR UPDATE NOWAIT"),
                {"run": run_id},
            )
            assert str(locked.scalar_one()) == run_id
            await other.rollback()
        return DigestNarrative(summary="ok", open_items=[], headlines=[]), 0.0

    narrator = AsyncMock(side_effect=_lock_from_another_session)
    try:
        async with db_session_factory() as session:
            digest = await RunMemoryService(session).write_digest(run_id, narrator=narrator, **_END)
        narrator.assert_awaited_once()
        assert DigestGenerator(digest.generator) == DigestGenerator.AGENT
    finally:
        async with db_session_factory() as cleanup:
            await cleanup.execute(delete(Task).where(Task.mission_id == mission_id))
            await cleanup.execute(delete(MissionRun).where(MissionRun.mission_id == mission_id))
            await cleanup.execute(delete(Mission).where(Mission.id == mission_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()
        async with db_session_factory() as check:
            assert await check.scalar(select(Mission.id).where(Mission.id == mission_id)) is None
