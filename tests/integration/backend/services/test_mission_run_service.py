"""MissionRunService (Plan 88 step 88.1.7, contract 3.5.1).

Real database with committed rows; TemporalWorkflowGateway is an AsyncMock.
Each service call runs in its own session, as the activities do.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.core.decision_reasoning import decode_decision_reasoning
from modules.backend.core.exceptions import (
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    RunStartRejectedError,
    ValidationError,
)
from modules.backend.events.mission_run_types import MissionRunBudgetBreachedEvent
from modules.backend.models.execution_record import (
    DecisionType,
    ExecutionDecision,
    ExecutionRecord,
    ExecutionRecordStatus,
)
from modules.backend.models.llm_call import LlmCall
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_run_digest import DigestGenerator, MissionRunDigest
from modules.backend.models.task import Task, TaskStatus
from modules.backend.models.user import User
from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.task_plan import TaskDefinition, TaskPlan
from modules.backend.services import mission_plan_taskio
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator
from modules.backend.services.mission_run import MissionRunService
from modules.backend.services.mission_run_lifecycle import RUN_FAILED, RUN_SUCCEEDED
from modules.backend.services.run_memory import RunMemoryService
from modules.backend.services.token_economics import TokenEconomicsService
from modules.backend.temporal.mission_run_models import TasksApprovedSignal
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from modules.backend.temporal.workflow_ids import mission_run_workflow_id
from tests.integration.backend.services.test_mission_schedule_service import RecordingBus

Factory = async_sessionmaker[AsyncSession]
AGENT = "system.summarization.agent"


@pytest.fixture
def gateway(monkeypatch) -> AsyncMock:
    """The gateway every MissionRunService call connects to."""
    fake = AsyncMock()
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=fake))
    return fake


@pytest.fixture
def owner(committed_owner):
    return committed_owner


def _svc(session: AsyncSession) -> MissionRunService:
    return MissionRunService(session, RecordingBus())


async def _start(
    factory: Factory, mission: Mission, user: User, objective: str | None = None
) -> MissionRun:
    async with factory() as session:
        return await _svc(session).start_run(
            mission.id,
            trigger=MissionRunTrigger.MANUAL,
            objective=objective,
            user_id=user.id,
            session_id=None,
        )


async def _begin(factory: Factory, run_id: str):
    async with factory() as session:
        return await _svc(session).begin(run_id)


async def _run(factory: Factory, run_id: str) -> MissionRun:
    async with factory() as session:
        return await session.get(MissionRun, run_id)


async def _task(
    factory: Factory,
    plan: MissionPlan,
    status: TaskStatus,
    run_id: str | None = None,
) -> str:
    async with factory() as session:
        task = await TaskRepository(session).create_task(
            plan_id=plan.id,
            mission_id=plan.mission_id,
            agent=AGENT,
            description=f"{status.value} task",
            instructions="Do it",
            status=status,
            mission_run_id=run_id,
        )
        await session.commit()
        return task.id


async def _tasks(factory: Factory, *task_ids: str) -> list[Task]:
    async with factory() as session:
        return [await session.get(Task, tid) for tid in task_ids]


async def _set_gate_mode(factory: Factory, plan: MissionPlan, name: str) -> None:
    async with factory() as session:
        await session.execute(
            text("UPDATE mission_plans SET gate_mode = :mode WHERE id = :id"),
            {"mode": name, "id": plan.id},
        )
        await session.commit()


async def _end(factory: Factory, run_id: str) -> None:
    async with factory() as session:
        await _svc(session).transition(
            run_id, MissionRunStatus.FAILED, MissionRunStatusReason.START_FAILED, "test end"
        )


# ── start_run ─────────────────────────────────────────────────────────────


async def test_start_run_conflict_when_active(db_session_factory, gateway, owner) -> None:
    user, mission, _ = await owner()
    first = await _start(db_session_factory, mission, user)

    with pytest.raises(ConflictError, match="run #1 is pending"):
        await _start(db_session_factory, mission, user)

    assert first.status == MissionRunStatus.PENDING
    gateway.start_mission_run.assert_awaited_once()


async def test_conflict_leaves_no_sequence_gap(db_session_factory, gateway, owner) -> None:
    user, mission, _ = await owner()
    first = await _start(db_session_factory, mission, user)
    with pytest.raises(ConflictError):
        await _start(db_session_factory, mission, user)

    await _end(db_session_factory, first.id)
    second = await _start(db_session_factory, mission, user)

    assert (first.sequence, second.sequence) == (1, 2)
    async with db_session_factory() as session:
        assert (await session.get(Mission, mission.id)).run_sequence_counter == 2


async def test_start_run_failed_start_marks_start_failed(
    db_session_factory, gateway, owner
) -> None:
    user, mission, _ = await owner()
    gateway.start_mission_run.side_effect = RuntimeError(
        "server rejected Bearer abc.def-ghi credentials"
    )

    with pytest.raises(ExternalServiceError):
        await _start(db_session_factory, mission, user)

    async with db_session_factory() as session:
        (run,) = (
            (await session.execute(select(MissionRun).where(MissionRun.mission_id == mission.id)))
            .scalars()
            .all()
        )
    assert run.status == MissionRunStatus.FAILED
    assert run.status_reason == MissionRunStatusReason.START_FAILED
    assert "Bearer <redacted>" in run.status_detail
    assert "abc.def-ghi" not in run.status_detail


async def test_workflow_id_format(db_session_factory, gateway, owner) -> None:
    user, mission, plan = await owner()
    run = await _start(db_session_factory, mission, user)

    gateway.start_mission_run.assert_awaited_once()
    (inp,) = gateway.start_mission_run.await_args.args
    assert inp.mission_run_id == run.id
    assert (inp.mission_id, inp.plan_id) == (mission.id, plan.id)
    assert run.temporal_workflow_id == mission_run_workflow_id(run.id)


# ── begin ─────────────────────────────────────────────────────────────────


async def test_begin_invalid_gate_mode_fails_closed(db_session_factory, gateway, owner) -> None:
    user, mission, plan = await owner()
    run = await _start(db_session_factory, mission, user)
    await _set_gate_mode(db_session_factory, plan, "INTERACTIVE")

    with pytest.raises(RunStartRejectedError):
        await _begin(db_session_factory, run.id)

    stored = await _run(db_session_factory, run.id)
    assert stored.status == MissionRunStatus.FAILED
    assert stored.status_reason == MissionRunStatusReason.INVALID_GATE_MODE


async def test_begin_owner_not_user_fails_start_failed(db_session_factory, gateway, owner) -> None:
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    async with db_session_factory() as session:
        await session.execute(
            update(Mission).where(Mission.id == mission.id).values(owner_id="cli-user")
        )
        await session.commit()

    with pytest.raises(RunStartRejectedError):
        await _begin(db_session_factory, run.id)

    stored = await _run(db_session_factory, run.id)
    assert stored.status == MissionRunStatus.FAILED
    assert stored.status_reason == MissionRunStatusReason.START_FAILED
    assert stored.status_detail == "owner not a platform user"


async def test_begin_snapshots_run_cap(db_session_factory, gateway, owner) -> None:
    user, mission, plan = await owner()
    run = await _start(db_session_factory, mission, user)
    assert run.budget_cap_usd is None
    async with db_session_factory() as session:
        await session.execute(
            update(MissionPlan).where(MissionPlan.id == plan.id).values(budget_per_run_usd=7.25)
        )
        await session.commit()

    await _begin(db_session_factory, run.id)

    stored = await _run(db_session_factory, run.id)
    assert stored.status == MissionRunStatus.RUNNING
    assert stored.budget_cap_usd == pytest.approx(7.25)


async def test_begin_adopts_backlog_and_is_idempotent(db_session_factory, gateway, owner) -> None:
    user, mission, plan = await owner()
    approved = await _task(db_session_factory, plan, TaskStatus.APPROVED)
    proposed = await _task(db_session_factory, plan, TaskStatus.PROPOSED)
    run = await _start(db_session_factory, mission, user)

    first = await _begin(db_session_factory, run.id)
    second = await _begin(db_session_factory, run.id)

    assert first == second
    assert first.gate_mode == GateMode.MANUAL.value
    assert first.context_version_start == 0
    assert first.previous_run_id is None
    stored = await _run(db_session_factory, run.id)
    assert stored.status == MissionRunStatus.RUNNING
    assert stored.session_id == first.session_id
    adopted, left = await _tasks(db_session_factory, approved, proposed)
    assert adopted.mission_run_id == run.id
    assert left.mission_run_id is None


async def test_begin_sets_context_version_start_to_current_mcd_version(
    db_session_factory, gateway, owner
) -> None:
    user, mission, _ = await owner()
    async with db_session_factory() as session:
        manager = MissionContextManager(session)
        await manager.create_context(mission.id, mission.name, "watermark")
        for path in ("architecture.data_flow", "architecture.components.api"):
            await manager.apply_updates(
                mission.id,
                [{"op": "add", "path": path, "value": "x"}],
                agent_id=None,
                task_id=None,
                mission_run_id=None,
                reason="watermark test",
            )
        await session.commit()
    run = await _start(db_session_factory, mission, user)

    begun = await _begin(db_session_factory, run.id)

    assert begun.context_version_start == 3
    stored = await _run(db_session_factory, run.id)
    assert stored.context_version_start == 3


async def test_begin_skips_backlog_when_workflow_run_active(
    db_session_factory, gateway, owner
) -> None:
    user, mission, plan = await owner()
    approved = await _task(db_session_factory, plan, TaskStatus.APPROVED)
    async with db_session_factory() as session:
        session.add(
            WorkflowRun(
                workflow_name="test.workflow",
                workflow_version=1,
                status=WorkflowRunState.RUNNING,
                trigger_type="on_demand",
                triggered_by="test",
                context={},
                total_cost_usd=0.0,
                mission_id=mission.id,
            )
        )
        await session.commit()
    run = await _start(db_session_factory, mission, user)

    await _begin(db_session_factory, run.id)

    (task,) = await _tasks(db_session_factory, approved)
    assert task.mission_run_id is None


async def test_begin_creates_one_execution_record(db_session_factory, gateway, owner) -> None:
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)

    await _begin(db_session_factory, run.id)
    await _begin(db_session_factory, run.id)

    async with db_session_factory() as session:
        records = (
            (
                await session.execute(
                    select(ExecutionRecord).where(ExecutionRecord.mission_run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(records) == 1
    assert records[0].temporal_workflow_id == mission_run_workflow_id(run.id)
    assert records[0].status == ExecutionRecordStatus.RUNNING
    assert records[0].task_params == {"mission_run_id": run.id}


async def test_run_detail_carries_execution_record_id(db_session_factory, gateway, owner) -> None:
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)

    async with db_session_factory() as session:
        before = await _svc(session).get_run_detail(mission.id, str(run.sequence))
    assert before.execution_record_id is None

    begun = await _begin(db_session_factory, run.id)
    async with db_session_factory() as session:
        after = await _svc(session).get_run_detail(mission.id, run.id)
    assert after.execution_record_id == begun.execution_record_id


# ── run-scoped planning ───────────────────────────────────────────────────


async def test_refine_scoped_to_run(db_session_factory, gateway, owner, monkeypatch) -> None:
    user, mission, plan = await owner()
    first = await _start(db_session_factory, mission, user)
    done = await _task(db_session_factory, plan, TaskStatus.COMPLETED, first.id)
    await _end(db_session_factory, first.id)
    backlog = await _task(db_session_factory, plan, TaskStatus.PROPOSED)
    second = await _start(db_session_factory, mission, user, objective="Write the report")
    begun = await _begin(db_session_factory, second.id)

    captured: list[dict] = []

    async def fake_planner(**kwargs) -> dict:
        captured.append(kwargs)
        return {"task_plan": {"not": "a plan"}}

    monkeypatch.setattr(
        "modules.backend.agents.mission_control.helpers.agent_executor._call_planning_agent",
        fake_planner,
    )
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.roster.derive_roster_from_team",
        AsyncMock(return_value=MagicMock()),
    )
    async with db_session_factory() as session:
        result = await _svc(session).plan(second.id, begun.session_id)

    assert result.status == "failed"
    assert captured
    assert captured[0]["mission_run_id"] == second.id
    task_ids = {t["task_id"] for t in captured[0]["current_plan"]["tasks"]}
    assert backlog in task_ids
    assert done not in task_ids


async def test_reconcile_does_not_cancel_other_runs_tasks(
    db_session_factory, gateway, owner
) -> None:
    user, mission, plan = await owner()
    first = await _start(db_session_factory, mission, user)
    other = await _task(db_session_factory, plan, TaskStatus.PROPOSED, first.id)
    await _end(db_session_factory, first.id)
    second = await _start(db_session_factory, mission, user)
    new_task_id = "00000000-0000-4000-8000-0000000000aa"
    new_plan = TaskPlan(
        mission_id=mission.id,
        tasks=[TaskDefinition(task_id=new_task_id, agent=AGENT, description="New task")],
    )

    async with db_session_factory() as session:
        orchestrator = MissionPlanOrchestrator(session, event_bus=RecordingBus())
        loaded = await orchestrator._repo.get_by_id(plan.id)
        await mission_plan_taskio.reconcile_tasks(
            orchestrator, loaded, new_plan, mission_run_id=None
        )
        await session.commit()

    kept, created = await _tasks(db_session_factory, other, new_task_id)
    assert kept.status == TaskStatus.PROPOSED
    assert kept.mission_run_id == first.id
    assert created.mission_run_id == second.id


async def test_refine_committing_after_its_run_ended_goes_to_backlog(
    db_session_factory, gateway, owner
) -> None:
    # Failure drill B: the refine resolved its run while the run was active,
    # the run ended during planning, then the refine committed. Its task must
    # go to the backlog (3.5.1), not stay on the ended run where no run adopts it.
    user, mission, plan = await owner()
    run = await _start(db_session_factory, mission, user)
    await _end(db_session_factory, run.id)
    new_task_id = "00000000-0000-4000-8000-0000000000bb"
    new_plan = TaskPlan(
        mission_id=mission.id,
        tasks=[TaskDefinition(task_id=new_task_id, agent=AGENT, description="New task")],
    )

    async with db_session_factory() as session:
        orchestrator = MissionPlanOrchestrator(session, event_bus=RecordingBus())
        loaded = await orchestrator._repo.get_by_id(plan.id)
        await mission_plan_taskio.reconcile_tasks(
            orchestrator, loaded, new_plan, mission_run_id=run.id
        )
        await session.commit()

    (created,) = await _tasks(db_session_factory, new_task_id)
    assert created.status == TaskStatus.PROPOSED
    assert created.mission_run_id is None


async def test_objective_plan_prompt_carries_previous_run_brief(
    db_session_factory, gateway, owner, monkeypatch
) -> None:
    """88.3.5: the planner's instructions are the run memory brief, then the objective."""
    user, mission, _ = await owner()
    first = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, first.id)
    await _end(db_session_factory, first.id)
    async with db_session_factory() as session:
        session.add(
            MissionRunDigest(
                mission_run_id=first.id,
                mission_id=mission.id,
                schema_version=1,
                generator=DigestGenerator.DETERMINISTIC,
                summary="First run summary",
                outcomes=[],
                open_items=[{"text": "Chase the vendor", "source_task_id": None}],
                metrics={},
            )
        )
        await session.commit()
    second = await _start(db_session_factory, mission, user, objective="Write the report")
    begun = await _begin(db_session_factory, second.id)

    captured: list[dict] = []

    async def fake_planner(**kwargs) -> dict:
        captured.append(kwargs)
        return {"task_plan": {"not": "a plan"}}

    monkeypatch.setattr(
        "modules.backend.agents.mission_control.helpers.agent_executor._call_planning_agent",
        fake_planner,
    )
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.roster.derive_roster_from_team",
        AsyncMock(return_value=MagicMock()),
    )
    async with db_session_factory() as session:
        await _svc(session).plan(second.id, begun.session_id)

    instructions = captured[0]["refinement_instructions"]
    assert instructions.startswith(f"## Previous run (#{first.sequence}, failed, digest:")
    assert "First run summary" in instructions
    assert "- Chase the vendor" in instructions
    assert instructions.endswith("\n\n## Objective\nWrite the report")


async def test_objective_plan_validates_against_run_headroom(
    db_session_factory, gateway, owner, monkeypatch
) -> None:
    """88.4.1 review: the objective refine is validated against the run's headroom.

    Per-run cap 5, per-month cap 6, 4 already spent this month by an earlier
    run: the planner's budget is min(5 - 0, 6 - 4) = 2, not a workflow default.
    """
    user, mission, plan = await owner()
    async with db_session_factory() as session:
        await session.execute(
            text(
                "UPDATE mission_plans SET budget_per_run_usd = 5.0, "
                "budget_per_month_usd = 6.0, budget_lifetime_usd = NULL WHERE id = :id"
            ),
            {"id": plan.id},
        )
        session.add(
            LlmCall(
                agent_name="test.agent",
                agent_role="worker",
                model="test-model",
                provider="test",
                input_tokens=1,
                output_tokens=1,
                cost_usd=4.0,
                mission_id=mission.id,
                mission_run_id=None,
            )
        )
        await session.commit()
    run = await _start(db_session_factory, mission, user, objective="Write the report")
    begun = await _begin(db_session_factory, run.id)

    budgets: list[float] = []

    async def fake_refine(self, plan_id, instructions, user_id, **kwargs):
        budgets.append(kwargs["mission_budget_usd"])

    monkeypatch.setattr(MissionPlanOrchestrator, "refine", fake_refine)
    async with db_session_factory() as session:
        result = await _svc(session).plan(run.id, begun.session_id)

    assert result.status == "planned"
    assert budgets == [pytest.approx(2.0)]


async def test_plan_rejects_dependency_on_unfinished_task_of_other_run(
    db_session_factory, gateway, owner
) -> None:
    user, mission, plan = await owner()
    first = await _start(db_session_factory, mission, user)
    foreign = await _task(db_session_factory, plan, TaskStatus.FAILED, first.id)
    await _end(db_session_factory, first.id)
    second = await _start(db_session_factory, mission, user)
    begun = await _begin(db_session_factory, second.id)
    local = await _task(db_session_factory, plan, TaskStatus.APPROVED, second.id)
    async with db_session_factory() as session:
        await TaskRepository(session).set_dependencies(local, [foreign])
        await session.commit()

    async with db_session_factory() as session:
        result = await _svc(session).plan(second.id, begun.session_id)

    assert result.status == "failed"
    assert result.detail == (
        f"Task {local} depends on unfinished task {foreign} outside run {second.id}"
    )


# ── cancel ────────────────────────────────────────────────────────────────


async def test_cancel_other_missions_run_404(db_session_factory, gateway, owner) -> None:
    user, mission, _ = await owner()
    _, other_mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)

    async with db_session_factory() as session:
        with pytest.raises(NotFoundError):
            await _svc(session).cancel_run(
                other_mission.id, run.id, user.id, MissionRunStatusReason.CANCELLED_BY_USER
            )

    assert (await _run(db_session_factory, run.id)).status == MissionRunStatus.PENDING


async def test_cancel_running_workflow_not_found_digests_then_finalises(
    db_session_factory, gateway, owner
) -> None:
    # 88.4.5: a run whose workflow is gone gets a deterministic digest and is
    # finalised CANCELLED with the stored cancel reason.
    gateway.cancel.return_value = WorkflowState.NOT_FOUND
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)

    async with db_session_factory() as session:
        cancelled = await _svc(session).cancel_run(
            mission.id, run.id, user.id, MissionRunStatusReason.CANCELLED_BY_USER
        )

    assert cancelled.status == MissionRunStatus.CANCELLED
    assert cancelled.status_reason == MissionRunStatusReason.CANCELLED_BY_USER
    assert cancelled.status_detail == "workflow not found at cancel"
    async with db_session_factory() as session:
        digest = await RunMemoryService(session).get_digest(mission.id, run.id)
    assert digest is not None
    assert digest.generator == DigestGenerator.DETERMINISTIC


# ── supervisor approval (88.1.8) ──────────────────────────────────────────


async def test_approve_proposed_only_when_autonomous(db_session_factory, gateway, owner) -> None:
    user, mission, plan = await owner()
    manual = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, manual.id)
    held = await _task(db_session_factory, plan, TaskStatus.PROPOSED, manual.id)

    async with db_session_factory() as session:
        assert await _svc(session).approve_proposed(manual.id) == 0
    (left,) = await _tasks(db_session_factory, held)
    assert left.status == TaskStatus.PROPOSED

    await _end(db_session_factory, manual.id)
    await _set_gate_mode(db_session_factory, plan, "AUTONOMOUS")
    autonomous = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, autonomous.id)
    proposed = await _task(db_session_factory, plan, TaskStatus.PROPOSED, autonomous.id)

    async with db_session_factory() as session:
        assert await _svc(session).approve_proposed(autonomous.id) == 1
    (approved,) = await _tasks(db_session_factory, proposed)
    assert approved.status == TaskStatus.APPROVED
    assert approved.approved_by_user_id == mission.owner_id


# ── finalise ──────────────────────────────────────────────────────────────


async def test_finalise_fails_inflight_tasks_and_sets_counts(
    db_session_factory, gateway, owner
) -> None:
    user, mission, plan = await owner()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    running = await _task(db_session_factory, plan, TaskStatus.RUNNING, run.id)
    queued = await _task(db_session_factory, plan, TaskStatus.QUEUED, run.id)
    await _task(db_session_factory, plan, TaskStatus.COMPLETED, run.id)
    proposed = await _task(db_session_factory, plan, TaskStatus.PROPOSED, run.id)

    async with db_session_factory() as session:
        await _svc(session).finalise(
            run.id, MissionRunStatus.FAILED, MissionRunStatusReason.TASK_FAILURES, "two failed"
        )

    a, b, released = await _tasks(db_session_factory, running, queued, proposed)
    assert (a.status, b.status) == (TaskStatus.FAILED, TaskStatus.FAILED)
    assert a.failure_reason == MissionRunStatusReason.TASK_FAILURES.value
    assert released.mission_run_id is None
    stored = await _run(db_session_factory, run.id)
    assert stored.status == MissionRunStatus.FAILED
    assert (stored.task_count, stored.completed_task_count, stored.failed_task_count) == (3, 1, 2)
    assert stored.context_version_end == 0
    async with db_session_factory() as session:
        record = await session.scalar(
            select(ExecutionRecord).where(ExecutionRecord.mission_run_id == run.id)
        )
    assert record.status == ExecutionRecordStatus.FAILED
    assert record.completed_at is not None


async def test_finalise_writes_ledger_cost(db_session_factory, gateway, owner) -> None:
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    begun = await _begin(db_session_factory, run.id)
    async with db_session_factory() as session:
        for cost, run_id in ((0.25, run.id), (0.50, run.id), (1.00, None)):
            session.add(
                LlmCall(
                    agent_name="test.agent",
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

    async with db_session_factory() as session:
        result = await _svc(session).finalise(
            run.id, MissionRunStatus.SUCCEEDED, MissionRunStatusReason.NO_FURTHER_WORK, None
        )

    assert result.cost_usd == pytest.approx(0.75)
    assert result.notification.kind == RUN_SUCCEEDED
    assert result.notification.subject_id == run.id
    assert (await _run(db_session_factory, run.id)).cost_usd == pytest.approx(0.75)
    async with db_session_factory() as session:
        record = await session.get(ExecutionRecord, begun.execution_record_id)
    assert record.total_cost_usd == pytest.approx(0.75)


async def test_finalise_keeps_digest_context_version_end(
    db_session_factory, gateway, owner
) -> None:
    # The digest owns context_version_end (88.3.7); finalise fills it only when NULL.
    user, mission, _ = await owner()

    async def _write_mcd(path: str) -> None:
        async with db_session_factory() as session:
            await MissionContextManager(session).apply_updates(
                mission.id,
                [{"op": "add", "path": path, "value": "x"}],
                agent_id=None,
                task_id=None,
                mission_run_id=None,
                reason="watermark test",
            )
            await session.commit()

    async with db_session_factory() as session:
        await MissionContextManager(session).create_context(mission.id, mission.name, "end")
        await session.commit()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    await _write_mcd("architecture.data_flow")
    async with db_session_factory() as session:
        await RunMemoryService(session).write_digest(
            run.id,
            status=MissionRunStatus.SUCCEEDED,
            reason=MissionRunStatusReason.NO_FURTHER_WORK,
            narrator=None,
        )
    await _write_mcd("architecture.components.api")

    async with db_session_factory() as session:
        await _svc(session).finalise(
            run.id, MissionRunStatus.SUCCEEDED, MissionRunStatusReason.NO_FURTHER_WORK, None
        )

    assert (await _run(db_session_factory, run.id)).context_version_end == 2


async def test_finalise_payload_states_generator(db_session_factory, gateway, owner) -> None:
    # Contract 3.1.7: the run-finished notification states the digest generator (88.3.8).
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    async with db_session_factory() as session:
        digest = await RunMemoryService(session).write_digest(
            run.id,
            status=MissionRunStatus.SUCCEEDED,
            reason=MissionRunStatusReason.NO_FURTHER_WORK,
            narrator=None,
        )
        summary = digest.summary

    async with db_session_factory() as session:
        result = await _svc(session).finalise(
            run.id, MissionRunStatus.SUCCEEDED, MissionRunStatusReason.NO_FURTHER_WORK, None
        )

    assert result.notification.kind == RUN_SUCCEEDED
    assert result.notification.payload["digest_generator"] == DigestGenerator.DETERMINISTIC.value
    assert result.notification.payload["digest_summary"] == summary


async def test_cancel_digest_and_run_row_agree_on_cancel_reason(
    db_session_factory, gateway, owner
) -> None:
    # The workflow ends a user-cancelled run with reason None; the digest and
    # finalise must both resolve it from run.cancel_reason (88.3.8 review).
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    async with db_session_factory() as session:
        await _svc(session).cancel_run(
            mission.id, run.id, user.id, MissionRunStatusReason.CANCELLED_BY_USER
        )
    gateway.cancel.assert_awaited_once()

    async with db_session_factory() as session:
        digest = await RunMemoryService(session).write_digest(
            run.id, status=MissionRunStatus.CANCELLED, reason=None, narrator=None
        )
        summary = digest.summary
    async with db_session_factory() as session:
        await _svc(session).finalise(run.id, MissionRunStatus.CANCELLED, None, None)

    ended = await _run(db_session_factory, run.id)
    assert ended.status_reason == MissionRunStatusReason.CANCELLED_BY_USER
    assert "ended cancelled (cancelled_by_user)" in summary


async def test_finalise_payload_without_digest_states_none(
    db_session_factory, gateway, owner
) -> None:
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)

    async with db_session_factory() as session:
        result = await _svc(session).finalise(
            run.id, MissionRunStatus.FAILED, MissionRunStatusReason.PLANNING_FAILED, "boom"
        )

    assert result.notification.kind == RUN_FAILED
    assert result.notification.payload["digest_generator"] is None
    assert result.notification.payload["digest_summary"] is None


async def test_finalise_records_director_objective_met_with_the_run_end(
    db_session_factory, gateway, owner
) -> None:
    # The Director's declaration is recorded only as the run ends on it, in
    # the same commit (review of 4d5d315b): a rejected declaration leaves no row.
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    begun = await _begin(db_session_factory, run.id)

    async with db_session_factory() as session:
        await _svc(session).finalise(
            run.id,
            MissionRunStatus.SUCCEEDED,
            MissionRunStatusReason.OBJECTIVE_MET,
            "Director declared the objective met: poem completed",
            director_objective_met="poem completed",
        )

    assert (await _run(db_session_factory, run.id)).status == MissionRunStatus.SUCCEEDED
    async with db_session_factory() as session:
        [decision] = (
            await session.scalars(
                select(ExecutionDecision).where(
                    ExecutionDecision.execution_record_id == begun.execution_record_id
                )
            )
        ).all()
    assert decision.decision_type == DecisionType.OBJECTIVE_MET
    human, meta = decode_decision_reasoning(decision.reasoning)
    assert human == "poem completed"
    assert meta["reviewer"] == "mission.director.agent"
    assert meta["action"] == "objective_met"
    assert meta["mission_run_id"] == run.id


async def test_finalise_refuses_director_objective_met_on_another_outcome(
    db_session_factory, gateway, owner
) -> None:
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    begun = await _begin(db_session_factory, run.id)

    async with db_session_factory() as session:
        with pytest.raises(ValidationError):
            await _svc(session).finalise(
                run.id,
                MissionRunStatus.FAILED,
                MissionRunStatusReason.SUPERVISOR_ESCALATED,
                "refine contradiction",
                director_objective_met="poem completed",
            )

    assert (await _run(db_session_factory, run.id)).status != MissionRunStatus.FAILED
    async with db_session_factory() as session:
        rows = await session.scalars(
            select(ExecutionDecision).where(
                ExecutionDecision.execution_record_id == begun.execution_record_id
            )
        )
        assert rows.all() == []


async def test_finalise_sums_rows_tagged_through_record_call(
    db_session_factory, gateway, owner
) -> None:
    """A ledger write tagged through record_call is counted in the run's cost."""
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    async with db_session_factory() as session:
        for cost, run_id in ((0.40, run.id), (2.00, None)):
            await TokenEconomicsService(session).record_call(
                session_id=None,
                mission_id=mission.id,
                agent_name="test.agent",
                agent_role="worker",
                model="test-model",
                provider="test",
                input_tokens=1,
                output_tokens=1,
                cache_read_tokens=0,
                cache_write_5m_tokens=0,
                cache_write_1h_tokens=0,
                thinking_tokens=0,
                cost_usd=cost,
                mission_run_id=run_id,
            )
        await session.commit()

    async with db_session_factory() as session:
        result = await _svc(session).finalise(
            run.id, MissionRunStatus.SUCCEEDED, MissionRunStatusReason.NO_FURTHER_WORK, None
        )

    assert result.cost_usd == pytest.approx(0.40)
    assert (await _run(db_session_factory, run.id)).cost_usd == pytest.approx(0.40)


async def test_approval_racing_finalise_starts_next_run(db_session_factory, gateway, owner) -> None:
    user, mission, plan = await owner()
    await _set_gate_mode(db_session_factory, plan, "AUTONOMOUS")
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    raced = await _task(db_session_factory, plan, TaskStatus.APPROVED, run.id)

    async with db_session_factory() as session:
        await _svc(session).finalise(
            run.id, MissionRunStatus.SUCCEEDED, MissionRunStatusReason.NO_FURTHER_WORK, None
        )

    (task,) = await _tasks(db_session_factory, raced)
    assert task.mission_run_id is None
    assert gateway.start_mission_run.await_count == 2
    (inp,) = gateway.start_mission_run.await_args.args
    following = await _run(db_session_factory, inp.mission_run_id)
    assert following.sequence == run.sequence + 1
    assert following.status == MissionRunStatus.PENDING
    assert following.objective is None


async def _ledger_row(factory: Factory, mission: Mission, cost: float, run_id: str | None) -> None:
    async with factory() as session:
        session.add(
            LlmCall(
                agent_name="test.agent",
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


async def test_finalise_budget_stopped_emits_breach_and_starts_no_run(
    db_session_factory, gateway, owner
) -> None:
    """88.4.6: the run-cap figures come from the run; raced approvals start nothing."""
    user, mission, plan = await owner()
    await _set_gate_mode(db_session_factory, plan, "AUTONOMOUS")
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    await _task(db_session_factory, plan, TaskStatus.APPROVED, run.id)
    await _ledger_row(db_session_factory, mission, 5.5, run.id)
    bus = RecordingBus()

    async with db_session_factory() as session:
        result = await MissionRunService(session, bus).finalise(
            run.id, MissionRunStatus.BUDGET_STOPPED, MissionRunStatusReason.BUDGET_RUN_CAP, None
        )

    (event,) = [e for e in bus.events if isinstance(e, MissionRunBudgetBreachedEvent)]
    assert (event.cap, event.spent_usd, event.cap_usd) == ("budget_run_cap", 5.5, 5.0)
    assert event.mission_run_id == run.id
    assert result.notification.kind == "budget_paused"
    assert gateway.start_mission_run.await_count == 1  # only the run itself


async def test_finalise_budget_stopped_monthly_reports_month_spend(
    db_session_factory, gateway, owner
) -> None:
    user, mission, _ = await owner()
    run = await _start(db_session_factory, mission, user)
    await _begin(db_session_factory, run.id)
    await _ledger_row(db_session_factory, mission, 99.0, None)
    await _ledger_row(db_session_factory, mission, 1.5, run.id)
    bus = RecordingBus()

    async with db_session_factory() as session:
        await MissionRunService(session, bus).finalise(
            run.id,
            MissionRunStatus.BUDGET_STOPPED,
            MissionRunStatusReason.BUDGET_MONTHLY_CAP,
            None,
        )

    (event,) = [e for e in bus.events if isinstance(e, MissionRunBudgetBreachedEvent)]
    assert event.cap == "budget_monthly_cap"
    assert event.spent_usd == pytest.approx(100.5)
    assert event.cap_usd == 100.0


# ── on_tasks_approved (88.1.9) ────────────────────────────────────────────


async def _runs(factory: Factory, mission: Mission) -> list[MissionRun]:
    async with factory() as session:
        result = await session.scalars(
            select(MissionRun).where(MissionRun.mission_id == mission.id)
        )
        return list(result)


async def test_on_tasks_approved_signals_active_run(db_session_factory, gateway, owner) -> None:
    user, mission, plan = await owner()
    run = await _start(db_session_factory, mission, user)
    task_id = await _task(db_session_factory, plan, TaskStatus.APPROVED)
    gateway.signal.return_value = WorkflowState.RUNNING

    async with db_session_factory() as session:
        await _svc(session).on_tasks_approved(mission.id, [task_id], user.id)

    gateway.signal.assert_awaited_once_with(
        run.temporal_workflow_id, "tasks_approved", TasksApprovedSignal(task_ids=[task_id])
    )
    gateway.start_mission_run.assert_awaited_once()


async def test_on_tasks_approved_starts_run_when_autonomous_and_idle(
    db_session_factory, gateway, owner
) -> None:
    user, mission, plan = await owner()
    await _set_gate_mode(db_session_factory, plan, "AUTONOMOUS")
    task_id = await _task(db_session_factory, plan, TaskStatus.APPROVED)

    async with db_session_factory() as session:
        await _svc(session).on_tasks_approved(mission.id, [task_id], user.id)

    gateway.signal.assert_not_awaited()
    gateway.start_mission_run.assert_awaited_once()
    (inp,) = gateway.start_mission_run.await_args.args
    started = await _run(db_session_factory, inp.mission_run_id)
    assert started.mission_id == mission.id
    assert started.trigger == MissionRunTrigger.MANUAL
    assert started.triggered_by_user_id == user.id
    assert started.objective is None


async def test_on_tasks_approved_noop_when_manual_and_idle(
    db_session_factory, gateway, owner
) -> None:
    user, mission, plan = await owner()
    task_id = await _task(db_session_factory, plan, TaskStatus.APPROVED)

    async with db_session_factory() as session:
        await _svc(session).on_tasks_approved(mission.id, [task_id], user.id)

    gateway.signal.assert_not_awaited()
    gateway.start_mission_run.assert_not_awaited()
    assert await _runs(db_session_factory, mission) == []


async def test_on_tasks_approved_signal_not_found_logs_and_returns(
    db_session_factory, gateway, owner
) -> None:
    user, mission, plan = await owner()
    await _set_gate_mode(db_session_factory, plan, "AUTONOMOUS")
    run = await _start(db_session_factory, mission, user)
    task_id = await _task(db_session_factory, plan, TaskStatus.APPROVED)
    gateway.signal.return_value = WorkflowState.NOT_FOUND

    async with db_session_factory() as session:
        svc = _svc(session)
        svc._logger = MagicMock()
        await svc.on_tasks_approved(mission.id, [task_id], user.id)

    svc._logger.warning.assert_called_once()
    assert svc._logger.warning.call_args.kwargs["extra"]["run_id"] == run.id
    gateway.start_mission_run.assert_awaited_once()
    assert [r.id for r in await _runs(db_session_factory, mission)] == [run.id]
