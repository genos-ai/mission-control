"""Per-task execution unit for the in-process loop and the Temporal activity (Plan 88, 88.2.3).

``run_single_task`` routes one task to its executor: the convergence loop,
the research loop, a ``workflow:`` sub-run or a standard roster agent. It
resolves upstream inputs, injects mission context and returns the task's
``TaskResult``. It never writes MCD updates; the caller applies them.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from modules.backend.agents.mission_control.dispatch.dag import resolve_upstream_inputs
from modules.backend.agents.mission_control.dispatch.result_builders import failed_result
from modules.backend.agents.mission_control.dispatch.step_executor import execute_with_step_events
from modules.backend.agents.mission_control.gate import GateReviewer, NoOpGate
from modules.backend.agents.mission_control.helpers import _emit
from modules.backend.agents.mission_control.models import (
    ContextAssemblerProtocol,
    EventBusProtocol,
    ExecuteAgentFn,
)
from modules.backend.agents.mission_control.outcome import TaskResult, TaskStatus, TaskTokenUsage
from modules.backend.agents.mission_control.roster import Roster
from modules.backend.core.logging import get_logger
from modules.backend.events.types import MissionNarrativeEvent, SystemEvent
from modules.backend.schemas.task_plan import TaskDefinition

if TYPE_CHECKING:
    from modules.backend.agents.mission_control.runtime import DispatchRuntime

logger = get_logger(__name__)

ROSTER_MISS_REASON = "Agent not found in roster"


async def emit_task_failure(
    bus: EventBusProtocol,
    session_id: str,
    mission_id: str | None,
    task_id: str,
    agent_name: str,
    reason: str,
) -> None:
    """Emit a narrative error event when a task fails during dispatch."""
    if not mission_id:
        return
    await _emit(
        bus,
        MissionNarrativeEvent,
        session_id=session_id,
        source=f"dispatch:{mission_id}",
        mission_id=mission_id,
        agent_id=agent_name,
        narrative=f"**{agent_name or 'dispatch'}** task `{task_id}` failed — {reason[:200]}",
        phase="error",
        level="warning",
    )


def _task_route(task: TaskDefinition) -> str:
    """Which executor runs the task: convergence_loop, research_loop, workflow or agent."""
    task_type = task.inputs.static.get("type")
    if task_type in ("convergence_loop", "research_loop"):
        return task_type
    if task.agent.startswith("workflow:"):
        return "workflow"
    return "agent"


def precheck_task(
    task: TaskDefinition, roster: Roster, upstream_outputs: dict[str, dict]
) -> str | None:
    """The reason the task cannot start, or None when it can.

    A standard agent task fails when its agent is not in the roster; every
    task except a ``workflow:`` one fails when a from_upstream reference is
    missing. The loop runs this before it waits for approval, so a task that
    cannot start fails at once instead of waiting.
    """
    route = _task_route(task)
    if route == "workflow":
        return None
    if route == "agent" and roster.get_agent_by_name(task.agent) is None:
        return ROSTER_MISS_REASON
    try:
        resolve_upstream_inputs(task, upstream_outputs)
    except KeyError as e:
        return str(e)
    return None


async def run_single_task(
    *,
    task: TaskDefinition,
    runtime: DispatchRuntime,
    upstream_outputs: dict[str, dict],
    mission_id: str,
    budget_usd: float,
    event_bus: EventBusProtocol,
    session_id: str,
    gate: GateReviewer | None,
    project_context: dict | None,
) -> TaskResult:
    """Run one task and return its TaskResult.

    ``gate=None`` means ``NoOpGate()``. ``budget_usd`` feeds only the gate
    context. ``project_context`` is the mission PCD used when the context
    assembler is absent or fails. A roster miss or a missing upstream output
    returns a failed result; an executor exception propagates to the caller.
    """
    _gate = gate or NoOpGate()

    reason = precheck_task(task, runtime.roster, upstream_outputs)
    if reason is not None:
        await emit_task_failure(event_bus, session_id, mission_id, task.task_id, task.agent, reason)
        return failed_result(task, reason)

    route = _task_route(task)
    logger.info(
        "TRACE     run_single_task routing",
        extra={
            "task_id": task.task_id,
            "agent": task.agent,
            "route": route,
            "static_keys": list(task.inputs.static.keys()),
        },
    )

    # ── Workflow task (Plan 53 Phase B): delegate to WorkflowRunService ──
    if route == "workflow":
        return await _dispatch_workflow_task(
            task=task,
            workflow_name=task.agent.split(":", 1)[1],
            mission_id=mission_id,
            event_bus=event_bus,
            session_id=session_id,
            gate=_gate,
        )

    resolved_inputs = dict(resolve_upstream_inputs(task, upstream_outputs))

    # ── Convergence loop (Plan 51 Phase B): the scaffold resolves its own
    # eval/remediation agents, so the roster check does not apply.
    if route == "convergence_loop":
        return await _dispatch_convergence_loop(
            task_id=task.task_id,
            resolved_inputs=resolved_inputs,
            execute_agent_fn=runtime.execute_agent_fn,
            mission_id=mission_id,
            gate=_gate,
            event_bus=event_bus,
            session_id=session_id,
        )

    # ── Research loop (Plan 40): same pattern as the convergence loop ──
    if route == "research_loop":
        return await _dispatch_research_loop(
            task_id=task.task_id,
            resolved_inputs=resolved_inputs,
            execute_agent_fn=runtime.execute_agent_fn,
            mission_id=mission_id,
            gate=_gate,
            event_bus=event_bus,
            session_id=session_id,
        )

    # ── Standard agent task ──
    await _inject_context(
        resolved_inputs=resolved_inputs,
        task=task,
        mission_id=mission_id,
        context_assembler=runtime.context_assembler,
        project_context=project_context,
    )
    return await execute_with_step_events(
        task=task,
        roster_entry=runtime.roster.get_agent_by_name(task.agent),
        resolved_inputs=resolved_inputs,
        execute_agent_fn=runtime.execute_agent_fn,
        execution_id=str(uuid.uuid4()),
        gate=_gate,
        mission_id=mission_id,
        budget_usd=budget_usd,
        event_bus=event_bus,
        session_id=session_id,
    )


async def _dispatch_convergence_loop(
    *,
    task_id: str,
    resolved_inputs: dict[str, Any],
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None,
    gate: GateReviewer,
    event_bus: EventBusProtocol,
    session_id: str,
) -> TaskResult:
    """Dispatch a convergence_loop task via the convergence scaffold.

    Plan 51 Phase B: parses ``ConvergenceConfig`` from the task's
    ``loop_config`` input, delegates to ``execute_convergence_loop()``,
    and returns the resulting ``TaskResult`` in the same shape the
    standard path returns — so the dispatch loop aggregates it
    transparently alongside regular single-agent task results.

    If ``loop_config`` is missing or malformed, returns a failed
    ``TaskResult`` immediately rather than raising — matching the
    error-result convention used by the rest of ``_execute_layer``.
    """
    from modules.backend.agents.mission_control.dispatch.convergence import (
        ConvergenceConfig,
        execute_convergence_loop,
    )

    loop_config_raw = resolved_inputs.get("loop_config")
    if not isinstance(loop_config_raw, dict):
        logger.warning(
            "convergence_loop task missing loop_config in inputs",
            extra={"task_id": task_id, "mission_id": mission_id},
        )
        return TaskResult(
            task_id=task_id,
            agent_name="convergence",
            status=TaskStatus.FAILED,
            output_reference={
                "error": "convergence_loop task requires a 'loop_config' dict "
                "in inputs.static, but none was found."
            },
            cost_usd=0.0,
            token_usage=TaskTokenUsage(),
        )

    try:
        config = ConvergenceConfig.from_dict(loop_config_raw)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "convergence_loop task has invalid loop_config",
            extra={"task_id": task_id, "error": str(exc), "mission_id": mission_id},
        )
        await _emit(
            event_bus,
            SystemEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            level="error",
            message=f"Task '{task_id}' has invalid convergence loop_config: {exc}"[:500],
            mission_id=mission_id,
        )
        return TaskResult(
            task_id=task_id,
            agent_name="convergence",
            status=TaskStatus.FAILED,
            output_reference={"error": f"Invalid loop_config: {exc}"},
            cost_usd=0.0,
            token_usage=TaskTokenUsage(),
        )

    return await execute_convergence_loop(
        task_id=task_id,
        config=config,
        execute_agent_fn=execute_agent_fn,
        mission_id=mission_id,
        gate=gate,
        event_bus=event_bus,
        session_id=session_id,
    )


async def _dispatch_research_loop(
    *,
    task_id: str,
    resolved_inputs: dict[str, Any],
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None,
    gate: GateReviewer,
    event_bus: EventBusProtocol,
    session_id: str,
) -> TaskResult:
    """Dispatch a research_loop task via the research loop executor.

    Plan 40: parses ``ResearchConfig`` from the task's ``loop_config``
    input, delegates to ``execute_research_loop()``, and returns the
    resulting ``TaskResult``. Mirrors ``_dispatch_convergence_loop``.
    """
    from modules.backend.agents.mission_control.dispatch.research_loop import (
        ResearchConfig,
        execute_research_loop,
    )

    loop_config_raw = resolved_inputs.get("loop_config")
    if not isinstance(loop_config_raw, dict):
        logger.warning(
            "research_loop task missing loop_config in inputs",
            extra={"task_id": task_id, "mission_id": mission_id},
        )
        return TaskResult(
            task_id=task_id,
            agent_name="research",
            status=TaskStatus.FAILED,
            output_reference={
                "error": "research_loop task requires a 'loop_config' dict "
                "in inputs.static, but none was found."
            },
            cost_usd=0.0,
            token_usage=TaskTokenUsage(),
        )

    try:
        config = ResearchConfig.from_dict(loop_config_raw)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "research_loop task has invalid loop_config",
            extra={"task_id": task_id, "error": str(exc), "mission_id": mission_id},
        )
        await _emit(
            event_bus,
            SystemEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            level="error",
            message=f"Task '{task_id}' has invalid research loop_config: {exc}"[:500],
            mission_id=mission_id,
        )
        return TaskResult(
            task_id=task_id,
            agent_name="research",
            status=TaskStatus.FAILED,
            output_reference={"error": f"Invalid loop_config: {exc}"},
            cost_usd=0.0,
            token_usage=TaskTokenUsage(),
        )

    query = resolved_inputs.get("query", "")
    return await execute_research_loop(
        task_id=task_id,
        query=query,
        config=config,
        execute_agent_fn=execute_agent_fn,
        mission_id=mission_id,
        gate=gate,
        event_bus=event_bus,
        session_id=session_id,
    )


async def _dispatch_workflow_task(
    *,
    task: TaskDefinition,
    workflow_name: str,
    mission_id: str | None,
    event_bus: EventBusProtocol,
    session_id: str,
    gate: GateReviewer,
) -> TaskResult:
    """Execute a workflow as a plan task (Plan 53 Phase B).

    Delegates to WorkflowRunService.run_workflow() which resolves the
    workflow name against mission-scoped definitions then system templates.
    Returns a TaskResult in the same shape as standard agent tasks.

    Cross-session note: the workflow runs in its own DB session (via
    factory()) — same model as WorkflowRunService._execute_wave() which
    opens per-step sessions. The ExecutionRecord created here commits
    independently. If the outer dispatch session rolls back (e.g. budget
    exceeded after this task), the ExecutionRecord persists as an orphan
    but plan_task_states won't link to it (the link was never committed).
    This is acceptable: orphan records are benign audit data, and the
    alternative (sharing the outer session) would conflict with the
    workflow's internal parallel step sessions.
    """
    from modules.backend.events.types import PlanStepCompletedEvent, PlanStepStartedEvent
    from modules.backend.services.workflow_run import WorkflowRunService

    await _emit(
        event_bus,
        PlanStepStartedEvent,
        session_id=session_id,
        source=f"dispatch:{mission_id}",
        plan_id=mission_id or "",
        step_id=task.task_id,
        step_name=task.description or task.task_id,
        assigned_agent=f"workflow:{workflow_name}",
    )

    status = TaskStatus.FAILED
    try:
        async with WorkflowRunService.factory(event_bus=event_bus) as svc:
            run = await svc.run_workflow(
                workflow_name=workflow_name,
                triggered_by="plan_dispatch",
                mission_id=mission_id,
                gate=gate,
            )

        run_status = run.status if isinstance(run.status, str) else run.status.value
        status = TaskStatus.SUCCESS if run_status == "completed" else TaskStatus.FAILED

        duration = 0.0
        if run.completed_at and run.started_at:
            duration = (run.completed_at - run.started_at).total_seconds()

        result = TaskResult(
            task_id=task.task_id,
            agent_name=f"workflow:{workflow_name}",
            status=status,
            output_reference={
                "workflow_run_id": str(run.id),
                "execution_record_id": run.execution_record_id,
                "status": run_status,
                "result": run.result_summary or f"Workflow {run_status}",
            },
            cost_usd=run.total_cost_usd or 0.0,
            duration_seconds=duration,
            token_usage=TaskTokenUsage(),
        )
    except Exception as e:
        # Catch-all justified: this is a task-dispatch boundary wrapping
        # a sub-workflow run (run_workflow) whose exception surface is
        # unbounded — any failure must convert to a failed TaskResult so
        # the dispatch loop can continue to the next task instead of
        # crashing the whole mission.
        # best-effort — the finally block below unconditionally emits
        # PlanStepCompletedEvent with status="failed" for this case.
        logger.error(
            "Workflow task dispatch failed",
            extra={
                "task_id": task.task_id,
                "workflow": workflow_name,
                "error": str(e),
                "mission_id": mission_id,
            },
            exc_info=True,
        )
        result = TaskResult(
            task_id=task.task_id,
            agent_name=f"workflow:{workflow_name}",
            status=TaskStatus.FAILED,
            output_reference={"error": str(e)},
            cost_usd=0.0,
            token_usage=TaskTokenUsage(),
        )
    finally:
        status_str = "success" if status == TaskStatus.SUCCESS else "failed"
        await _emit(
            event_bus,
            PlanStepCompletedEvent,
            session_id=session_id,
            source=f"dispatch:{mission_id}",
            plan_id=mission_id or "",
            step_id=task.task_id,
            result_summary=f"workflow:{workflow_name} — {status_str}",
            status=status_str,
        )

    return result


async def _inject_context(
    resolved_inputs: dict[str, Any],
    task: TaskDefinition,
    mission_id: str | None,
    context_assembler: ContextAssemblerProtocol | None,
    project_context: dict | None,
) -> None:
    """Inject context (assembled packet or raw PCD) into resolved inputs."""
    if context_assembler and mission_id:
        try:
            assembled = await context_assembler.build(
                mission_id=mission_id,
                task_definition=task.model_dump(),
                resolved_inputs=dict(resolved_inputs),
                domain_tags=task.domain_tags or None,
            )
            resolved_inputs["project_context"] = assembled.get("project_context", {})
            code_map_content = assembled.get("code_map")
            if code_map_content:
                resolved_inputs["code_map"] = code_map_content
            history_content = assembled.get("history")
            if history_content:
                resolved_inputs["project_history"] = history_content
        except (OSError, ValueError, RuntimeError):
            logger.warning(
                "Context assembly failed, falling back to PCD",
                extra={"task_id": task.task_id, "mission_id": mission_id},
                exc_info=True,
            )
            if project_context:
                resolved_inputs["project_context"] = project_context
    elif project_context:
        resolved_inputs["project_context"] = project_context
