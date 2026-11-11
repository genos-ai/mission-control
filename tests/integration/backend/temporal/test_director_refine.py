"""A run's advance_refine waits for the Director's refinement (Plan 88 Phase 2 failure drill B).

Drill B (mission p88-faildrill-b2) ended its run "refine produced no tasks":
the Director's refine_plan started a PlanRefineWorkflow and returned, the turn
ended, ChatTurnWorkflow signalled refinement_complete, and the run read its
task graph before the refine had committed. The task arrived 5 seconds later,
APPROVED on a run that had already ended.

These tests run the real MissionRunWorkflow, ChatTurnWorkflow and
PlanRefineWorkflow in a time-skipping Temporal environment, with the real
refine_plan tool inside the Director turn. Every activity is a stub: the run's
come from mission_run_stubs; the Director turn calls refine_plan as run_tool
would; the refine activity takes longer than the rest of the turn, then
"commits" its task by changing the run's scripted task graph.
"""

import asyncio
import dataclasses
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from modules.backend.agents.deps.base import RunRefineTurn
from modules.backend.agents.mission.director.tools.declare_objective_met import (
    declare_objective_met,
)
from modules.backend.agents.mission.director.tools.refine_plan import refine_plan
from modules.backend.core.config import get_app_config
from modules.backend.models.execution_record import ExecutionDecision
from modules.backend.models.mission_run import MissionRunTrigger
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_run import MissionRunService
from modules.backend.temporal.chat_models import ChatTurnInput, ChatTurnResult
from modules.backend.temporal.chat_workflow import ChatTurnWorkflow
from modules.backend.temporal.config_snapshots import (
    build_run_config_snapshot,
    build_workflow_timeouts_snapshot,
)
from modules.backend.temporal.mission_run_models import (
    DirectorTurnInput,
    MissionRunWorkflowInput,
    RunTaskGraph,
)
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
from modules.backend.temporal.plan_refine_models import PlanRefineInput, PlanRefineResult
from modules.backend.temporal.plan_refine_workflow import PlanRefineWorkflow
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway
from tests.integration.backend.services.test_mission_schedule_service import RecordingBus
from tests.integration.backend.temporal import mission_run_stubs as stubs
from tests.integration.backend.temporal.mission_run_stubs import failed, graph

Factory = async_sessionmaker[AsyncSession]
EMPTY = RunTaskGraph(layers=[], proposed=0, approved=0, running=0)
REFINE_SECONDS = 1.0  # longer than the rest of the Director turn, as in the drill


@dataclasses.dataclass
class Harness:
    client: Client | None = None
    refine: Callable[[PlanRefineInput], PlanRefineResult] | None = None
    turn_error: Exception | None = None
    # Replaces the refine_plan Director: answers the turn as execute_chat_turn would.
    director: Callable[[ChatTurnInput], Awaitable[ChatTurnResult]] | None = None


HARNESS = Harness()


@activity.defn(name="start_director_turn")
async def director_turn_stub(inp: DirectorTurnInput) -> str:
    """As start_director_turn: start a ChatTurnWorkflow for the Director, signalling the run."""
    stubs.CALLS.append(("start_director_turn", inp))
    workflow_id = f"director-followup-{uuid.uuid4().hex[:8]}"
    await HARNESS.client.start_workflow(
        ChatTurnWorkflow.run,
        ChatTurnInput(
            session_id=inp.session_id,
            mission_id=inp.mission_id,
            message=inp.prompt,
            sender_id="mission.supervisor.agent",
            agent_id="mission.director.agent",
            channel="followup",
            parent_workflow_id=inp.signal_workflow_id,
            refine_mission_run_id=inp.mission_run_id if inp.signal_workflow_id else None,
            timeouts=build_workflow_timeouts_snapshot(),
        ),
        id=workflow_id,
        task_queue=get_app_config().temporal.task_queue,
    )
    return workflow_id


@activity.defn(name="persist_user_message")
async def persist_user_message_stub(inp: ChatTurnInput) -> str:
    return "message-id"


@activity.defn(name="execute_chat_turn")
async def execute_chat_turn_stub(inp: ChatTurnInput) -> ChatTurnResult:
    """The Director answers the refine prompt by calling refine_plan, as run_tool runs it."""
    if HARNESS.turn_error is not None:
        raise HARNESS.turn_error
    if HARNESS.director is not None:
        return await HARNESS.director(inp)
    db = SimpleNamespace(commit=AsyncMock())
    try:
        output = json.dumps(await refine_plan(db, inp.mission_id, "next wave", None))
    except Exception as exc:  # noqa: BLE001 — run_tool's contract: errors go back to the LLM
        output = json.dumps({"error": str(exc)})
    stubs.CALLS.append(("director_turn_done", output))
    return ChatTurnResult(session_id=inp.session_id, content=f"refine_plan said: {output}")


@activity.defn(name="execute_plan_refine")
async def execute_plan_refine_stub(inp: PlanRefineInput) -> PlanRefineResult:
    await asyncio.sleep(REFINE_SECONDS)
    result = HARNESS.refine(inp)
    stubs.CALLS.append(("refine_committed", inp.plan_id))
    return result


def _commit_task_b(inp: PlanRefineInput) -> PlanRefineResult:
    # The refine's new task becomes visible to the run's next graph reads.
    stubs.SCRIPT.graphs = [graph(["b"]), graph(["b"]), EMPTY]
    return PlanRefineResult(plan_id=inp.plan_id, version=2, task_count=1, approved_count=1)


def _planner_fails(inp: PlanRefineInput) -> PlanRefineResult:
    raise ApplicationError(
        "Planning Agent failed after 3 attempts: no agent",
        type="ValidationError",
        non_retryable=True,
    )


@pytest.fixture
async def bare_env(monkeypatch) -> AsyncIterator[WorkflowEnvironment]:
    """The Temporal test environment and the harness, with no service patched."""
    stubs.reset()
    HARNESS.__init__()
    environment = await WorkflowEnvironment.start_time_skipping()
    HARNESS.client = environment.client
    monkeypatch.setattr(
        "modules.backend.temporal.client.get_temporal_client",
        AsyncMock(return_value=environment.client),
    )
    try:
        yield environment
    finally:
        await environment.shutdown()


@pytest.fixture
def env(bare_env: WorkflowEnvironment, monkeypatch) -> WorkflowEnvironment:
    """bare_env with the services refine_plan reads patched (no database)."""
    run_id = str(uuid.uuid4())
    monkeypatch.setattr(
        MissionService, "get_mission", AsyncMock(return_value=SimpleNamespace(owner_id="owner"))
    )
    monkeypatch.setattr(
        MissionPlanService,
        "get_or_create_plan",
        AsyncMock(return_value=SimpleNamespace(id=str(uuid.uuid4()))),
    )
    monkeypatch.setattr(MissionPlanService, "remaining_budget_usd", AsyncMock(return_value=5.0))
    monkeypatch.setattr(
        MissionRunService, "get_active_run", AsyncMock(return_value=SimpleNamespace(id=run_id))
    )
    return bare_env


@asynccontextmanager
async def _run(
    env: WorkflowEnvironment, *, run_id: str | None = None, mission_id: str | None = None
) -> AsyncIterator[WorkflowHandle]:
    task_queue = get_app_config().temporal.task_queue
    snapshot = dataclasses.replace(build_run_config_snapshot(), task_queue=task_queue)
    inp = MissionRunWorkflowInput(
        mission_run_id=run_id or str(uuid.uuid4()),
        mission_id=mission_id or str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        config=snapshot,
    )
    run_activities = [a for a in stubs.ACTIVITIES if a is not stubs.director_stub]
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[MissionRunWorkflow, ChatTurnWorkflow, PlanRefineWorkflow],
        activities=[
            *run_activities,
            director_turn_stub,
            persist_user_message_stub,
            execute_chat_turn_stub,
            execute_plan_refine_stub,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        # Real time: refine_wait_seconds must not be skipped past while the
        # Director turn and the refine are in flight.
        with env.auto_time_skipping_disabled():
            yield await env.client.start_workflow(
                MissionRunWorkflow.run,
                inp,
                id=f"mission-run-{inp.mission_run_id}",
                task_queue=task_queue,
            )


def _executed() -> list[str]:
    return [inp.task_id for inp in stubs.calls("execute_plan_task")]


def _order() -> list[str]:
    return [name for name, _ in stubs.CALLS]


async def test_run_executes_task_from_refine_slower_than_turn(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"]), EMPTY]
    stubs.SCRIPT.actions = ["advance_refine", "propose_complete"]
    stubs.SCRIPT.task_results = {"a": [failed("a")]}
    HARNESS.refine = _commit_task_b

    async with _run(env) as handle:
        assert await asyncio.wait_for(handle.result(), timeout=30) == "succeeded"

    assert _executed() == ["a", "b"]
    order = _order()
    # The run read its graph only after the refine committed and the turn ended.
    assert order.index("refine_committed") < order.index("director_turn_done")
    post_refine_fetch = order.index("fetch_run_task_graph", order.index("start_director_turn"))
    assert order.index("director_turn_done") < post_refine_fetch
    [(status, reason)] = [(f.status, f.reason) for f in stubs.calls("finalise_mission_run")]
    assert (status, reason) == ("succeeded", "objective_met")


async def test_refine_failure_fails_run_with_its_cause(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"]), EMPTY]
    stubs.SCRIPT.actions = ["advance_refine"]
    stubs.SCRIPT.task_results = {"a": [failed("a")]}
    HARNESS.refine = _planner_fails

    async with _run(env) as handle:
        assert await asyncio.wait_for(handle.result(), timeout=30) == "failed"

    assert _executed() == ["a"]
    [end] = stubs.calls("finalise_mission_run")
    assert (end.status, end.reason) == ("failed", "supervisor_escalated")
    assert end.detail.startswith("refine produced no tasks: ")
    assert "Plan refinement failed: " in end.detail
    assert "Planning Agent failed after 3 attempts: no agent" in end.detail


async def test_director_turn_failure_fails_run_without_waiting(env: WorkflowEnvironment):
    stubs.SCRIPT.graphs = [graph(["a"]), EMPTY]
    stubs.SCRIPT.actions = ["advance_refine"]
    stubs.SCRIPT.task_results = {"a": [failed("a")]}
    HARNESS.turn_error = ApplicationError("model provider down", non_retryable=True)

    async with _run(env) as handle:
        # refine_wait_seconds is 600; the failed turn's signal ends the run first.
        assert await asyncio.wait_for(handle.result(), timeout=30) == "failed"

    [end] = stubs.calls("finalise_mission_run")
    assert (end.status, end.reason) == ("failed", "supervisor_escalated")
    assert end.detail.startswith("refine produced no tasks: Director turn failed: ")
    assert "model provider down" in end.detail


# ── declare_objective_met (owner decision 2026-11-11, drill p88-faildrill-b3) ──
#
# Drill b3: the wave-2 task completed, the reviewer still chose advance_refine,
# the Director replied "objective met" in text and the run failed "refine
# produced no tasks". These tests run the real declare_objective_met and
# refine_plan tools against the real database inside the Director turn; the
# run, mission and ExecutionRecord rows are real, the workflow's activities are
# stubs. The tool writes nothing: finalise records the decision as the run ends
# on it (test_mission_run_service covers that write against the database).

REASON = "The brief asks for one completed poem task; wave 2 completed it."
BLOCKED = RunTaskGraph(layers=[], proposed=0, approved=1, running=0)


@dataclasses.dataclass
class DbRun:
    mission_id: str
    run_id: str
    execution_record_id: str


@pytest.fixture
async def db_run(db_session_factory: Factory, committed_owner, monkeypatch) -> DbRun:
    """A begun mission run: the mission's active run, with its ExecutionRecord."""
    monkeypatch.setattr(TemporalWorkflowGateway, "connect", AsyncMock(return_value=AsyncMock()))
    user, mission, _plan = await committed_owner()
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
    return DbRun(mission.id, run.id, begun.execution_record_id)


def _director(
    factory: Factory, *, reply: str, declare: str | None, then_refine: bool = False
) -> Callable[[ChatTurnInput], Awaitable[ChatTurnResult]]:
    """A Director turn as execute_chat_turn runs it: RunRefineTurn in, its fields out."""

    async def answer(inp: ChatTurnInput) -> ChatTurnResult:
        run_refine = (
            RunRefineTurn(mission_run_id=inp.refine_mission_run_id)
            if inp.refine_mission_run_id
            else None
        )
        outputs: list[str] = []
        async with factory() as session:
            calls: list[Callable[[], Awaitable[dict]]] = []
            if declare is not None:
                calls.append(
                    lambda: declare_objective_met(
                        session, inp.mission_id, run_refine, declare, RecordingBus()
                    )
                )
            if then_refine:
                calls.append(
                    lambda: refine_plan(session, inp.mission_id, "one more", None, run_refine)
                )
            for call in calls:
                try:
                    outputs.append(json.dumps(await call()))
                except Exception as exc:  # noqa: BLE001 — run_tool's contract: errors go to the LLM
                    outputs.append(json.dumps({"error": str(exc)}))
        stubs.CALLS.append(("director_turn_done", outputs))
        return ChatTurnResult(
            session_id=inp.session_id,
            content=reply,
            objective_met_reason=run_refine.objective_met_reason if run_refine else None,
            refined=run_refine.refined if run_refine else False,
        )

    return answer


async def _decisions(factory: Factory, execution_record_id: str) -> list[ExecutionDecision]:
    async with factory() as session:
        result = await session.execute(
            select(ExecutionDecision).where(
                ExecutionDecision.execution_record_id == execution_record_id
            )
        )
        return list(result.scalars().all())


def _turn_outputs() -> list[dict]:
    [outputs] = [arg for name, arg in stubs.CALLS if name == "director_turn_done"]
    return [json.loads(o) for o in outputs]


async def test_director_declares_objective_met_run_succeeds(
    bare_env: WorkflowEnvironment, db_session_factory: Factory, db_run: DbRun
):
    stubs.SCRIPT.graphs = [graph(["a"]), EMPTY]
    stubs.SCRIPT.actions = ["advance_refine"]
    HARNESS.director = _director(db_session_factory, reply="Objective met.", declare=REASON)

    async with _run(bare_env, run_id=db_run.run_id, mission_id=db_run.mission_id) as handle:
        assert await asyncio.wait_for(handle.result(), timeout=30) == "succeeded"

    [refine_turn] = stubs.calls("start_director_turn")
    assert "declare_objective_met" in refine_turn.prompt
    [end] = stubs.calls("finalise_mission_run")
    assert (end.status, end.reason) == ("succeeded", "objective_met")
    assert end.detail == f"Director declared the objective met: {REASON}"
    assert end.director_objective_met == REASON
    # Nothing is written before the run decides; finalise (a stub here) records it.
    assert await _decisions(db_session_factory, db_run.execution_record_id) == []


async def test_declaration_with_blocked_task_left_from_failed_wave_succeeds(
    bare_env: WorkflowEnvironment, db_session_factory: Factory, db_run: DbRun
):
    # Wave 1 fails task a; its dependent stays APPROVED and blocked, so the
    # graph has an approved task the Director's turn did not add.
    stubs.SCRIPT.graphs = [graph(["a"]), BLOCKED]
    stubs.SCRIPT.actions = ["advance_refine"]
    stubs.SCRIPT.task_results = {"a": [failed("a")]}
    HARNESS.director = _director(db_session_factory, reply="Objective met.", declare=REASON)

    async with _run(bare_env, run_id=db_run.run_id, mission_id=db_run.mission_id) as handle:
        assert await asyncio.wait_for(handle.result(), timeout=30) == "succeeded"

    [end] = stubs.calls("finalise_mission_run")
    assert (end.status, end.reason) == ("succeeded", "objective_met")
    assert end.director_objective_met == REASON
    assert stubs.calls("approve_run_proposed_tasks") == []


async def test_refine_plan_after_declaration_is_refused_and_run_succeeds(
    bare_env: WorkflowEnvironment, db_session_factory: Factory, db_run: DbRun
):
    stubs.SCRIPT.graphs = [graph(["a"]), EMPTY]
    stubs.SCRIPT.actions = ["advance_refine", "propose_complete"]
    HARNESS.director = _director(
        db_session_factory, reply="Done, and one more task.", declare=REASON, then_refine=True
    )

    async with _run(bare_env, run_id=db_run.run_id, mission_id=db_run.mission_id) as handle:
        assert await asyncio.wait_for(handle.result(), timeout=30) == "succeeded"

    declared, refused = _turn_outputs()
    assert declared["status"] == "declared"
    assert "already declared met" in refused["error"]
    assert _executed() == ["a"]
    [end] = stubs.calls("finalise_mission_run")
    assert end.director_objective_met == REASON


async def test_objective_met_in_text_only_still_fails_loudly(
    bare_env: WorkflowEnvironment, db_session_factory: Factory, db_run: DbRun
):
    # Drill b3 exactly: the Director said so in text and called no tool.
    stubs.SCRIPT.graphs = [graph(["a"]), EMPTY]
    stubs.SCRIPT.actions = ["advance_refine"]
    HARNESS.director = _director(db_session_factory, reply="The objective is met.", declare=None)

    async with _run(bare_env, run_id=db_run.run_id, mission_id=db_run.mission_id) as handle:
        assert await asyncio.wait_for(handle.result(), timeout=30) == "failed"

    [end] = stubs.calls("finalise_mission_run")
    assert (end.status, end.reason) == ("failed", "supervisor_escalated")
    assert end.detail == (
        "refine produced no tasks: Director turn ended without new tasks; "
        "Director replied: The objective is met."
    )
    assert end.director_objective_met is None


async def test_declaration_for_a_run_that_is_not_active_is_refused(
    bare_env: WorkflowEnvironment, db_session_factory: Factory, db_run: DbRun
):
    # The turn is bound to a run that is not the mission's active run: the tool
    # refuses, the turn is undeclared, and the run fails loudly as before.
    stubs.SCRIPT.graphs = [graph(["a"]), EMPTY]
    stubs.SCRIPT.actions = ["advance_refine"]
    HARNESS.director = _director(db_session_factory, reply="Objective met.", declare=REASON)

    async with _run(bare_env, mission_id=db_run.mission_id) as handle:
        assert await asyncio.wait_for(handle.result(), timeout=30) == "failed"

    [output] = _turn_outputs()
    assert "is not the active run of mission" in output["error"]
    [end] = stubs.calls("finalise_mission_run")
    assert end.detail.startswith("refine produced no tasks: ")
    assert end.director_objective_met is None
