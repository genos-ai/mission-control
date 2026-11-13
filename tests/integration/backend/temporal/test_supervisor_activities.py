"""evaluate_post_run against the real database (Plan 88 step 88.2.6).

The reviewer is replaced by a recorder so the test sees the GateContext the
activity builds; everything else (run, tasks, ExecutionRecord) is real.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.agents.mission_control.gate_models import GateAction, GateDecision
from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer
from modules.backend.models.execution_record import ExecutionRecord
from modules.backend.models.llm_call import LlmCall
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import MissionRun, MissionRunTrigger
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.gate import GateContext
from modules.backend.schemas.task_failure import FailureClass, FailureOrigin
from modules.backend.services.mission_run import MissionRunService
from modules.backend.temporal.supervisor_activities import PostRunEvalInput, evaluate_post_run
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway
from tests.integration.backend.services.test_mission_schedule_service import RecordingBus

Factory = async_sessionmaker[AsyncSession]
AGENT = "system.summarization.agent"


@pytest.fixture
def gateway(monkeypatch) -> AsyncMock:
    fake = AsyncMock()
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=fake))
    return fake


@pytest.fixture
def contexts(monkeypatch) -> list[GateContext]:
    seen: list[GateContext] = []

    async def review(self, context: GateContext) -> GateDecision:
        seen.append(context)
        return GateDecision(action=GateAction.WAIT, reason="recorded", reviewer="test")

    monkeypatch.setattr(AutonomousPostRunReviewer, "review", review)
    return seen


@pytest.fixture
def activity_sessions(monkeypatch, db_session_factory: Factory) -> None:
    @asynccontextmanager
    async def session():
        async with db_session_factory() as s:
            yield s

    monkeypatch.setattr("modules.backend.core.database.get_async_session", session)


async def _failed_task(
    factory: Factory, plan_id: str, mission_id: str, run_id: str, fingerprint: str, reason: str
) -> str:
    async with factory() as session:
        repo = TaskRepository(session)
        task = await repo.create_task(
            plan_id=plan_id,
            mission_id=mission_id,
            agent=AGENT,
            description="failing task",
            status=TaskStatus.FAILED,
            mission_run_id=run_id,
        )
        task.failure_reason = reason
        task.failure_origin = FailureOrigin.AGENT
        task.failure_class = FailureClass.AGENT_REPORTED_FAILURE
        task.failure_fingerprint = fingerprint
        task.cost_usd = 0.5
        await session.commit()
        return task.id


async def test_post_run_context_carries_failure_digests(
    db_session_factory: Factory, committed_owner, gateway, contexts, activity_sessions
) -> None:
    user, mission, plan = await committed_owner()
    async with db_session_factory() as session:
        run = await MissionRunService(session, RecordingBus()).start_run(
            mission.id,
            trigger=MissionRunTrigger.MANUAL,
            objective=None,
            user_id=user.id,
            session_id=None,
        )
    async with db_session_factory() as session:
        begun = await MissionRunService(session, RecordingBus()).begin(run.id)
    wave = [
        await _failed_task(db_session_factory, plan.id, mission.id, run.id, "f1", "first"),
        await _failed_task(db_session_factory, plan.id, mission.id, run.id, "f2", "other"),
        await _failed_task(db_session_factory, plan.id, mission.id, run.id, "f1", "again"),
    ]
    async with db_session_factory() as session:
        for cost, run_id in ((1.0, run.id), (0.5, run.id), (2.0, None)):
            session.add(
                LlmCall(
                    agent_name=AGENT,
                    agent_role="worker",
                    model="test-model",
                    provider="test",
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=cost,
                    mission_id=mission.id,
                    mission_run_id=run_id,
                )
            )
        await session.commit()

    result = await evaluate_post_run(
        PostRunEvalInput(
            mission.id,
            run.id,
            begun.execution_record_id,
            2,
            begun.session_id,
            1,
            wave_task_ids=wave,
        )
    )

    assert result.action == "wait"
    [context] = contexts
    assert context.plan_task_summary["zero_completion_waves"] == 1
    failures = context.plan_task_summary["failures"]
    assert [(f["summary"], f["occurrences"]) for f in failures] == [("first", 2), ("other", 1)]
    assert failures[0]["origin"] == "agent"
    assert failures[0]["failure_class"] == "agent_reported_failure"
    assert context.plan_task_summary["failures_truncated"] == 0
    assert "max_supervisor_iterations" not in context.plan_task_summary
    # Run spend from the ledger; budget = spend + headroom under the 5.00 run cap.
    assert context.total_cost_usd == pytest.approx(1.5)
    assert context.budget_usd == pytest.approx(5.0)

    async with db_session_factory() as session:
        stored_run = await session.get(MissionRun, run.id)
        record = await session.get(ExecutionRecord, begun.execution_record_id)
    assert stored_run.iteration_count == 3
    assert record.failed_task_count == 3


async def test_stall_escalates_within_run_after_early_success(
    db_session_factory: Factory, committed_owner, gateway, activity_sessions
) -> None:
    """A completed task keeps the run's record above zero; failing waves still stall."""
    user, mission, plan = await committed_owner()
    async with db_session_factory() as session:
        (await session.get(MissionPlan, plan.id)).gate_mode = GateMode.AUTONOMOUS
        await session.commit()
    async with db_session_factory() as session:
        run = await MissionRunService(session, RecordingBus()).start_run(
            mission.id,
            trigger=MissionRunTrigger.MANUAL,
            objective=None,
            user_id=user.id,
            session_id=None,
        )
    async with db_session_factory() as session:
        begun = await MissionRunService(session, RecordingBus()).begin(run.id)
    async with db_session_factory() as session:
        await TaskRepository(session).create_task(
            plan_id=plan.id,
            mission_id=mission.id,
            agent=AGENT,
            description="early success",
            status=TaskStatus.COMPLETED,
            mission_run_id=run.id,
        )
        await session.commit()
    wave = [
        await _failed_task(db_session_factory, plan.id, mission.id, run.id, fingerprint, "boom")
        for fingerprint in ("f1", "f2", "f3")
    ]

    result = await evaluate_post_run(
        PostRunEvalInput(
            mission.id,
            run.id,
            begun.execution_record_id,
            3,
            begun.session_id,
            3,
            wave_task_ids=wave,
        )
    )

    assert result.action == "escalate"
    assert "Stall detected" in result.reason
    async with db_session_factory() as session:
        record = await session.get(ExecutionRecord, begun.execution_record_id)
    assert record.completed_task_count == 1


async def test_post_run_failures_scoped_to_the_wave(
    db_session_factory: Factory, committed_owner, gateway, contexts, activity_sessions
) -> None:
    """Drill p88-faildrill-b3: wave 1 failed a task, wave 2 completed its replacement.

    The reviewer was shown the wave-1 failure as current. Scoped to wave 2 it
    sees no failure and the completed replacement in the wave block.
    """
    user, mission, plan = await committed_owner()
    async with db_session_factory() as session:
        run = await MissionRunService(session, RecordingBus()).start_run(
            mission.id,
            trigger=MissionRunTrigger.MANUAL,
            objective=None,
            user_id=user.id,
            session_id=None,
        )
    async with db_session_factory() as session:
        begun = await MissionRunService(session, RecordingBus()).begin(run.id)
    await _failed_task(db_session_factory, plan.id, mission.id, run.id, "f1", "platform_defect")
    async with db_session_factory() as session:
        replacement = await TaskRepository(session).create_task(
            plan_id=plan.id,
            mission_id=mission.id,
            agent=AGENT,
            description="write the poem (replacement)",
            status=TaskStatus.COMPLETED,
            mission_run_id=run.id,
        )
        await session.commit()
        replacement_id = replacement.id

    await evaluate_post_run(
        PostRunEvalInput(
            mission.id,
            run.id,
            begun.execution_record_id,
            1,
            begun.session_id,
            0,
            wave_task_ids=[replacement_id],
        )
    )

    [context] = contexts
    summary = context.plan_task_summary
    assert summary["failures"] == []
    assert summary["failures_truncated"] == 0
    assert summary["wave"] == [
        {
            "task_id": replacement_id,
            "status": "completed",
            "description": "write the poem (replacement)",
        }
    ]
