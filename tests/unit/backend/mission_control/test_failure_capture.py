"""Every failed task result carries a classified TaskFailure (Plan 88, 88.2.3b).

Covers the single failed-result builder, every failing dispatch fork, the
retry handler's one retry rule, workflow step errors and the AST guard on
``failed_result`` call sites; and the Planning Agent's view of task states and
failures during refinement (88.2.4a, contracts 3.8.6).
"""

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from modules.backend.agents.mission_control.dispatch import retry_handler
from modules.backend.agents.mission_control.dispatch.convergence import (
    ConvergenceConfig,
    execute_convergence_loop,
)
from modules.backend.agents.mission_control.dispatch.research_loop import (
    ResearchConfig,
    execute_research_loop,
)
from modules.backend.agents.mission_control.dispatch.result_builders import failed_result
from modules.backend.agents.mission_control.dispatch.task_runner import run_single_task
from modules.backend.agents.mission_control.outcome import TaskResult, TaskStatus
from modules.backend.agents.mission_control.roster import (
    Roster,
    RosterAgentEntry,
    RosterConstraintsSchema,
    RosterInterfaceSchema,
    RosterModelSchema,
)
from modules.backend.agents.mission_control.runtime import DispatchRuntime
from modules.backend.core.config import find_project_root
from modules.backend.core.exceptions import (
    BudgetExceededError,
    ContractViolationError,
    ExecutionEnvironmentError,
    ExternalServiceError,
    QuotaExhaustedError,
    RateLimitedError,
    TransientProviderError,
)
from modules.backend.core.failure_classification import (
    WorkflowStepFailedError,
    get_failure_classifier,
)
from modules.backend.core.protocols import NoOpEventBus
from modules.backend.schemas.task_failure import FailureClass, FailureOrigin
from modules.backend.schemas.task_plan import TaskDefinition
from modules.backend.schemas.workflow import WorkflowStepSchema
from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin
from modules.backend.tools.halt_workflow import WorkflowHaltedError

_WAVES = "modules.backend.services.workflow_run_waves"


def _entry(name: str = "agent_a", *, retry_budget: int = 0) -> RosterAgentEntry:
    return RosterAgentEntry(
        agent_name=name,
        agent_version="1.0.0",
        description=f"Agent {name}",
        model=RosterModelSchema(name="anthropic:claude-sonnet-5"),
        interface=RosterInterfaceSchema(
            input={"query": "string"}, output={"result": "string", "confidence": "float"}
        ),
        constraints=RosterConstraintsSchema(
            timeout_seconds=10, cost_ceiling_usd=1.0, retry_budget=retry_budget
        ),
    )


def _task(agent: str = "agent_a", static: dict | None = None) -> TaskDefinition:
    return TaskDefinition.model_validate(
        {
            "task_id": "t1",
            "agent": agent,
            "agent_version": "1.0.0",
            "description": "Test",
            "instructions": "Do it",
            "inputs": {"static": static or {}, "from_upstream": {}},
            "dependencies": [],
            "verification": {
                "tier_1": {"schema_validation": True, "required_output_fields": ["result"]},
                "tier_2": {"deterministic_checks": []},
                "tier_3": {"requires_ai_evaluation": False},
            },
        }
    )


async def _run(task: TaskDefinition, execute_agent_fn=None) -> TaskResult:
    async def _default(agent_name, instructions, inputs, usage_limits):
        return {"result": "done", "confidence": 0.9, "_meta": {}}

    runtime = DispatchRuntime(
        roster=Roster(agents=[_entry()]),
        execute_agent_fn=execute_agent_fn or _default,
        context_curator=None,
        context_assembler=None,
        environment_handle=None,
    )
    return await run_single_task(
        task=task,
        runtime=runtime,
        upstream_outputs={},
        mission_id="mission-1",
        budget_usd=10.0,
        event_bus=NoOpEventBus(),
        session_id=str(uuid.uuid4()),
        gate=None,
        project_context=None,
    )


def _assert_failed(result: TaskResult) -> None:
    assert result.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT)
    assert result.failure is not None
    assert len(result.failure.fingerprint) == 64


# =============================================================================
# Construction
# =============================================================================


def test_failed_result_requires_failure():
    with pytest.raises(PydanticValidationError, match="requires a failure"):
        TaskResult(task_id="t1", agent_name="a", status=TaskStatus.FAILED)
    with pytest.raises(PydanticValidationError, match="requires a failure"):
        TaskResult(task_id="t1", agent_name="a", status=TaskStatus.TIMEOUT)
    failure = get_failure_classifier().roster_miss("a")
    with pytest.raises(PydanticValidationError, match="must not carry a failure"):
        TaskResult(task_id="t1", agent_name="a", status=TaskStatus.SUCCESS, failure=failure)
    with pytest.raises(TypeError):
        failed_result(_task())  # type: ignore[call-arg]

    result = failed_result(_task(), failure, cost_usd=0.25, duration_seconds=1.5)
    assert result.failure == failure
    assert (result.cost_usd, result.duration_seconds) == (0.25, 1.5)


async def _raise_runtime(**_kwargs):
    raise RuntimeError("agent run broke")


class _WorkflowFactory:
    def __init__(self, run=None, error: Exception | None = None):
        self._svc = MagicMock()
        self._svc.run_workflow = AsyncMock(return_value=run, side_effect=error)

    async def __aenter__(self):
        return self._svc

    async def __aexit__(self, *exc):
        return False


def _workflow_run(error_data: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        id="run-1",
        status="failed",
        completed_at=None,
        started_at=None,
        execution_record_id=None,
        result_summary="Workflow failed",
        total_cost_usd=0.0,
        error_data=error_data,
    )


async def test_every_failed_fork_carries_failure():
    classifier = get_failure_classifier()

    # Standard agent fork, through the retry handler.
    standard = await _run(_task(), AsyncMock(side_effect=_raise_runtime))
    _assert_failed(standard)

    # Roster miss.
    _assert_failed(await _run(_task(agent="ghost.agent")))

    # Convergence and research forks with no loop_config.
    for loop_type in ("convergence_loop", "research_loop"):
        result = await _run(_task(static={"type": loop_type}))
        _assert_failed(result)
        assert result.failure.failure_class is FailureClass.AGENT_CONTRACT

    # Convergence loop that never converges.
    executor = AsyncMock(
        side_effect=[
            {"output": {"findings_count": 3}, "success": True, "cost_usd": 0.0},
            {"output": {}, "success": True, "cost_usd": 0.0},
        ]
    )
    unconverged = await execute_convergence_loop(
        task_id="t1",
        config=ConvergenceConfig(max_iterations=1),
        execute_agent_fn=executor,
        event_bus=NoOpEventBus(),
    )
    _assert_failed(unconverged)
    assert unconverged.failure.failure_class is FailureClass.AGENT_REPORTED_FAILURE

    # Research loop whose agent call raises.
    research = await execute_research_loop(
        task=_task(agent="research"),
        query="q",
        config=ResearchConfig(max_iterations=1),
        execute_agent_fn=_raise_runtime,
        event_bus=NoOpEventBus(),
    )
    _assert_failed(research)

    # workflow: fork — a stored step failure, no stored failure, and an exception.
    stored = classifier.agent_outcome("workflow:scan", "workflow halted: nothing to report")
    target = "modules.backend.services.workflow_run.WorkflowRunService.factory"
    cases = [
        (_WorkflowFactory(_workflow_run({"failure": stored.model_dump(mode="json")})), stored),
        (_WorkflowFactory(_workflow_run({"message": "Step 'scan' failed"})), None),
        (_WorkflowFactory(error=RuntimeError("definition not found")), None),
    ]
    for factory, expected in cases:
        with patch(target, return_value=factory):
            result = await _run(_task(agent="workflow:flow"))
        _assert_failed(result)
        if expected is not None:
            assert result.failure == expected
    with patch(target, return_value=cases[1][0]):
        aborted = await _run(_task(agent="workflow:flow"))
    assert aborted.failure.failure_class is FailureClass.RUN_ABORTED
    assert aborted.failure.summary == "Step 'scan' failed"


# =============================================================================
# Retry handler
# =============================================================================


async def _execute(exc: BaseException, *, retry_budget: int = 1):
    async def _raise(**_kwargs):
        raise exc

    mock_execute = AsyncMock(side_effect=_raise)
    with patch.object(retry_handler, "execute_task", mock_execute):
        result = await retry_handler.execute_with_retry(
            task=_task(),
            roster_entry=_entry(retry_budget=retry_budget),
            resolved_inputs={},
            execute_agent_fn=AsyncMock(),
        )
    return result, mock_execute.await_count


@pytest.mark.parametrize(
    ("exc", "expected_class", "attempts"),
    [
        (QuotaExhaustedError("quota"), FailureClass.QUOTA_EXHAUSTED, 1),
        (RateLimitedError("slow"), FailureClass.TRANSIENT_PROVIDER, 2),
        (TransientProviderError("blip"), FailureClass.TRANSIENT_PROVIDER, 2),
        (ContractViolationError("shape"), FailureClass.AGENT_CONTRACT, 1),
        (ExecutionEnvironmentError("no workspace"), FailureClass.ENV_UNAVAILABLE, 1),
        (TimeoutError(), FailureClass.TIMEOUT, 2),
        (ExternalServiceError("503"), FailureClass.PLATFORM_TRANSIENT, 2),
        (BudgetExceededError(), FailureClass.BUDGET_EXCEEDED, 1),
        (RuntimeError("odd"), FailureClass.UNKNOWN, 2),
    ],
)
async def test_retry_decision_follows_failure_retryable(exc, expected_class, attempts):
    result, await_count = await _execute(exc)
    assert result.failure.failure_class is expected_class
    assert await_count == attempts
    assert (await_count == 2) is result.failure.retryable


async def test_timeout_class_sets_timeout_status():
    result, _ = await _execute(TimeoutError(), retry_budget=0)
    assert result.status == TaskStatus.TIMEOUT
    result, _ = await _execute(RuntimeError("odd"), retry_budget=0)
    assert result.status == TaskStatus.FAILED


async def test_final_attempt_in_retry_history():
    result, await_count = await _execute(RuntimeError("still broken"), retry_budget=2)
    assert await_count == 3
    assert [e.attempt for e in result.retry_history] == [1, 2, 3]
    assert all(e.failure_class is FailureClass.UNKNOWN for e in result.retry_history)
    assert result.retry_history[0].feedback_provided.startswith(
        "Previous attempt failed (unknown): "
    )
    assert result.retry_history[-1].feedback_provided == ""


async def test_platform_defect_not_retried():
    # Raised by the mock, so the innermost non-skipped frame is the platform's
    # retry handler: the frame-path rule makes it a platform defect.
    mock_execute = AsyncMock(side_effect=KeyError("missing"))
    with patch.object(retry_handler, "execute_task", mock_execute):
        result = await retry_handler.execute_with_retry(
            task=_task(),
            roster_entry=_entry(retry_budget=2),
            resolved_inputs={},
            execute_agent_fn=AsyncMock(),
        )
    assert result.failure.origin is FailureOrigin.PLATFORM
    assert result.failure.failure_class is FailureClass.PLATFORM_DEFECT
    assert mock_execute.await_count == 1


async def test_budget_exceeded_not_retried():
    result, await_count = await _execute(BudgetExceededError(), retry_budget=3)
    assert await_count == 1
    assert result.failure.summary == "budget_exceeded"


# =============================================================================
# Workflow step errors
# =============================================================================


def _waves_service() -> WorkflowRunWavesMixin:
    svc = WorkflowRunWavesMixin()
    svc._workflow_service = MagicMock()
    svc._workflow_service.resolve_upstream_context.return_value = {}
    svc._event_bus = AsyncMock()
    return svc


def _step_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.persistence.count_active = AsyncMock(return_value=0)
    ctx.persistence.save_execution = AsyncMock(return_value=MagicMock(id="rec-1"))
    ctx.persistence.complete_execution = AsyncMock()
    return ctx


def _wf_run() -> MagicMock:
    run = MagicMock()
    run.id = "run-1"
    run.mission_id = "mission-1"
    run.context = {}
    return run


async def test_workflow_step_env_error_is_env_unavailable():
    step = WorkflowStepSchema(id="scan", capability="security.webapp", environment="container")
    env_error = ExecutionEnvironmentError("execution mode 'container' requires repo_root")
    with (
        patch(f"{_WAVES}.resolve_dispatch_params", AsyncMock(side_effect=env_error)),
        patch("modules.backend.services.session.SessionService", MagicMock()),
        pytest.raises(WorkflowStepFailedError) as exc_info,
    ):
        await _waves_service()._execute_step(_wf_run(), step, str(uuid.uuid4()), {}, _step_ctx())

    failure = exc_info.value.failure
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.ENVIRONMENT,
        FailureClass.ENV_UNAVAILABLE,
    )
    assert exc_info.value.__cause__ is env_error
    assert failure.summary in str(exc_info.value)


async def test_workflow_halt_is_agent_reported_failure():
    step = WorkflowStepSchema(
        id="gate",
        node_type="tool_call",
        tool_call_config={"tool_name": "halt_workflow", "tool_args": {"reason": "no deliverable"}},
    )

    with pytest.raises(WorkflowStepFailedError) as exc_info:
        await _waves_service()._execute_step(_wf_run(), step, str(uuid.uuid4()), {}, _step_ctx())

    failure = exc_info.value.failure
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.AGENT,
        FailureClass.AGENT_REPORTED_FAILURE,
    )
    assert failure.summary == "workflow halted: no deliverable"
    assert isinstance(exc_info.value.__cause__, WorkflowHaltedError)
    assert failure == get_failure_classifier().agent_outcome(
        "workflow:gate", "workflow halted: no deliverable"
    )


# =============================================================================
# Spend
# =============================================================================


async def test_research_failure_keeps_spend():
    async def _bad_decomposition(*, agent_name, instructions, inputs, usage_limits):
        return {
            "output": {"not": "a decomposition"},
            "_meta": {"cost_usd": 0.42, "input_tokens": 7, "output_tokens": 3},
        }

    result = await execute_research_loop(
        task=_task(agent="research"),
        query="q",
        config=ResearchConfig(max_iterations=1),
        execute_agent_fn=_bad_decomposition,
        event_bus=NoOpEventBus(),
    )
    _assert_failed(result)
    assert result.failure.failure_class is FailureClass.AGENT_REPORTED_FAILURE
    assert result.cost_usd == pytest.approx(0.42)
    assert (result.token_usage.input, result.token_usage.output) == (7, 3)
    assert result.duration_seconds >= 0.0


# =============================================================================
# Call sites
# =============================================================================


def test_failed_result_callers_pass_task_failure():
    backend = find_project_root() / "modules" / "backend"
    offenders: list[str] = []
    private_builders: list[str] = []
    for path in sorted(backend.rglob("*.py")):
        tree = ast.parse(Path(path).read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name == "_failed_result":
                    private_builders.append(f"{path}:{node.lineno}")
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "failed_result":
                continue
            has_failure = len(node.args) >= 2 or any(k.arg == "failure" for k in node.keywords)
            if not has_failure:
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []
    assert private_builders == []


# =============================================================================
# Planning Agent sees task states and failures (88.2.4a)
# =============================================================================

_PLAN_AGENT = "agent_a"


def _task_row(status, *, mission_run_id: str | None = None):
    from modules.backend.models.task import Task

    return Task(
        id=str(uuid.uuid4()),
        agent=_PLAN_AGENT,
        description="A task",
        status=status,
        mission_run_id=mission_run_id,
    )


def test_materialize_task_states_carries_failure():
    from modules.backend.models.task import TaskStatus as RowStatus
    from modules.backend.repositories.task import TaskRepository
    from modules.backend.services import mission_plan_taskio

    run_id = str(uuid.uuid4())
    failed = _task_row(RowStatus.FAILED, mission_run_id=run_id)
    TaskRepository.set_failure(failed, get_failure_classifier().orphaned("workflow vanished"))
    completed = _task_row(RowStatus.COMPLETED)
    other_run = _task_row(RowStatus.FAILED, mission_run_id=str(uuid.uuid4()))
    plan = SimpleNamespace(tasks=[failed, completed, other_run])

    states = mission_plan_taskio.materialize_task_states(plan, mission_run_id=run_id)

    assert states == [
        {
            "task_id": failed.id,
            "status": "failed",
            "failure": {
                "origin": "platform",
                "failure_class": "orphaned",
                "summary": "workflow vanished",
            },
        },
        {"task_id": completed.id, "status": "completed", "failure": None},
    ]


class _RefiningPlanner:
    """Planning agent stand-in: keeps the seeded tasks and finalises the plan."""

    _function_toolset = SimpleNamespace(tools={})

    def __init__(self) -> None:
        self.prompt: str | None = None
        self.seeded: dict[str, dict] = {}
        self.finalise_result: dict | None = None

    async def run(self, prompt, *, deps, model_settings=None, usage_limits=None):
        from pydantic_ai.usage import RunUsage

        self.prompt = prompt
        self.seeded = {tid: dict(body) for tid, body in deps.build_session.tasks.items()}
        self.finalise_result = deps.build_session.finalise(
            summary="refined", estimated_cost_usd=0.5, estimated_duration_seconds=60
        )
        return SimpleNamespace(
            usage=lambda: RunUsage(input_tokens=10, output_tokens=5),
            all_messages=lambda: [],
        )


@pytest.mark.asyncio
async def test_refine_with_failed_task_finalises(db_session, test_user, monkeypatch):
    from pydantic_ai.models.test import TestModel

    from modules.backend.agents.mission_control.helpers import agent_executor
    from modules.backend.models.mission import Mission
    from modules.backend.models.mission_plan import GateMode, MissionPlan
    from modules.backend.models.task import TaskStatus as RowStatus
    from modules.backend.repositories.task import TaskRepository
    from modules.backend.schemas.task_plan import TaskPlan
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Refine with a failed task",
        owner_id=test_user.id,
        budget_ceiling_usd=10.0,
    )
    db_session.add(mission)
    await db_session.flush()
    plan = MissionPlan(
        mission_id=mission.id, gate_mode=GateMode.AUTONOMOUS, budget_usd_ceiling=10.0
    )
    db_session.add(plan)
    await db_session.flush()
    repo = TaskRepository(db_session)
    failed = await repo.create_task(
        plan_id=plan.id,
        mission_id=mission.id,
        agent=_PLAN_AGENT,
        description="Failing task",
        status=RowStatus.FAILED,
    )
    repo.set_failure(failed, get_failure_classifier().orphaned("workflow vanished"))
    await db_session.flush()

    start_version = plan.version
    planner = _RefiningPlanner()

    async def _noop(*args, **kwargs):
        return None

    async def _roster(mission_id, session):
        return Roster(agents=[_entry(_PLAN_AGENT)])

    monkeypatch.setattr(agent_executor, "record_llm_call", _noop)
    monkeypatch.setattr(agent_executor, "_build_model", lambda ref: TestModel())
    monkeypatch.setattr(
        "modules.backend.agents.mission.planning.agent.create_agent", lambda model: planner
    )
    monkeypatch.setattr("modules.backend.core.agent_trace.trace_and_emit", _noop)
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.roster.derive_roster_from_team", _roster
    )

    orchestrator = MissionPlanOrchestrator(db_session, event_bus=NoOpEventBus())
    refined = await orchestrator.refine(
        plan.id, "Retry the failing work", str(test_user.id), mission_run_id=None
    )

    assert planner.finalise_result is not None and planner.finalise_result["valid"]
    TaskPlan.model_validate(planner.finalise_result["plan"])
    # The failure reaches the prompt, never the seeded session tasks.
    assert "### Current Task States" in planner.prompt
    assert '"failure_class": "orphaned"' in planner.prompt
    assert '"summary": "workflow vanished"' in planner.prompt
    assert "status" not in planner.seeded[failed.id]
    assert "failure" not in planner.seeded[failed.id]
    assert refined.version == start_version + 1
