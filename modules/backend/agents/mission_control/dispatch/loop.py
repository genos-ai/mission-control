"""Dispatch loop — layer-by-layer task orchestration.

Executes a validated TaskPlan by sorting tasks topologically, running
each layer in parallel, resolving upstream inputs, injecting context,
and aggregating results into an ExecutionOutcome.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from modules.backend.agents.mission_control.dispatch.dag import topological_sort
from modules.backend.agents.mission_control.dispatch.result_builders import failed_result
from modules.backend.agents.mission_control.dispatch.task_runner import (
    emit_task_failure,
    precheck_task,
    run_single_task,
)
from modules.backend.agents.mission_control.gate import (
    GateAction,
    GateContext,
    GateReviewer,
    NoOpGate,
)
from modules.backend.agents.mission_control.helpers import _emit
from modules.backend.agents.mission_control.models import (
    ContextAssemblerProtocol,
    ContextCuratorProtocol,
    EventBusProtocol,
    ExecuteAgentFn,
)
from modules.backend.agents.mission_control.outcome import (
    ExecutionOutcome,
    ExecutionStatus,
    GateDecisionRecord,
    TaskResult,
    TaskStatus,
    TaskTokenUsage,
)
from modules.backend.agents.mission_control.roster import Roster
from modules.backend.agents.mission_control.runtime import DispatchRuntime
from modules.backend.core.config import get_app_config
from modules.backend.core.failure_classification import get_failure_classifier
from modules.backend.core.logging import get_logger
from modules.backend.events.types import PlanCreatedEvent
from modules.backend.schemas.task_plan import TaskDefinition, TaskPlan

logger = get_logger(__name__)


async def dispatch(
    plan: TaskPlan,
    roster: Roster,
    execute_agent_fn: ExecuteAgentFn,
    mission_budget_usd: float,
    *,
    gate: GateReviewer | None = None,
    mission_id: str | None = None,
    context_curator: ContextCuratorProtocol | None = None,
    context_assembler: ContextAssemblerProtocol | None = None,
    event_bus: EventBusProtocol,
    session_id: str | None = None,
    execution_mode: str = "local",
    prior_outputs: dict[str, dict] | None = None,
    session_factory: Any | None = None,
) -> ExecutionOutcome:
    """Execute the dispatch loop for a validated TaskPlan.

    1. Topological sort into execution layers
    2. Execute each layer (parallel within layer, sequential across layers)
    3. Resolve from_upstream at dispatch time
    4. 3-tier verification after each task
    5. Retry with feedback on verification failure
    6. Aggregate results into ExecutionOutcome

    When gate is provided, pauses at key decision points for review.
    event_bus is required — pass a real SessionEventBus; NoOpEventBus is
    for tests only.
    """
    start_time = time.monotonic()
    _gate = gate or NoOpGate()
    _bus = event_bus
    _sid = session_id or plan.mission_id
    layers = topological_sort(plan)

    if execution_mode != "local":
        logger.info(
            "Dispatch using non-local execution mode",
            extra={"execution_mode": execution_mode, "mission_id": plan.mission_id},
        )

    # Plan 80h: pre_dispatch / pre_layer gates removed. Pre-execution
    # approval is the task lifecycle (PROPOSED → APPROVED). Tasks that
    # need operator approval will park here when the wave engine waits
    # on their state. The user transitions them via `mc plan approve`.
    gate_decisions: list[GateDecisionRecord] = []

    await _emit(
        _bus,
        PlanCreatedEvent,
        session_id=_sid,
        source=f"dispatch:{plan.mission_id}",
        plan_id=plan.mission_id,
        goal=plan.summary,
        step_count=len(plan.tasks),
        metadata={"task_count": len(plan.tasks), "summary": plan.summary},
    )

    project_context = await _load_project_context(mission_id, context_curator)
    # Mission context is injected only when dispatch runs for a mission.
    runtime = DispatchRuntime(
        roster=roster,
        execute_agent_fn=execute_agent_fn,
        context_curator=context_curator if mission_id else None,
        context_assembler=context_assembler if mission_id else None,
        environment_handle=None,
    )

    # Seed with outputs from prior waves (completed in earlier dispatches).
    # Without this, from_upstream references to tasks that ran in a previous
    # dispatch_approved call would fail with KeyError.
    completed_outputs: dict[str, dict] = dict(prior_outputs) if prior_outputs else {}
    task_results: list[TaskResult] = []
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    total_thinking_tokens = 0

    aborted = False
    abort_reason: str | None = None
    for layer_idx, layer in enumerate(layers):
        layer_result = await _execute_layer(
            plan=plan,
            layer=layer,
            layer_idx=layer_idx,
            layers=layers,
            runtime=runtime,
            completed_outputs=completed_outputs,
            task_results=task_results,
            total_cost=total_cost,
            mission_budget_usd=mission_budget_usd,
            gate=_gate,
            gate_decisions=gate_decisions,
            mission_id=mission_id,
            context_curator=context_curator,
            project_context=project_context,
            event_bus=_bus,
            session_id=_sid,
            session_factory=session_factory,
        )

        if layer_result is None:
            continue

        if layer_result.get("aborted"):
            aborted = True
            abort_reason = layer_result.get("abort_reason")
            break

        total_cost = layer_result["total_cost"]
        total_input_tokens = layer_result["total_input_tokens"]
        total_output_tokens = layer_result["total_output_tokens"]
        total_thinking_tokens = layer_result["total_thinking_tokens"]

        if mission_budget_usd and total_cost > mission_budget_usd:
            logger.warning(
                "Mission budget exceeded, cancelling remaining tasks",
                extra={
                    "cumulative_cost": total_cost,
                    "budget": mission_budget_usd,
                    "mission_id": mission_id,
                },
            )
            break

    return _build_outcome(
        plan=plan,
        task_results=task_results,
        total_cost=total_cost,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_thinking_tokens=total_thinking_tokens,
        mission_budget_usd=mission_budget_usd,
        aborted=aborted,
        abort_reason=abort_reason,
        start_time=start_time,
        gate_decisions=gate_decisions,
    )


async def _load_project_context(
    mission_id: str | None,
    context_curator: ContextCuratorProtocol | None,
) -> dict | None:
    """Load the project context document for agent context injection."""
    if not (mission_id and context_curator):
        return None
    try:
        pcd = await context_curator.get_mission_context(mission_id)
        return pcd or None
    except (OSError, ValueError, RuntimeError):
        logger.warning(
            "Failed to load PCD for dispatch (non-fatal)",
            extra={"mission_id": mission_id},
            exc_info=True,
        )
        return None


async def _execute_layer(
    plan: TaskPlan,
    layer: list[str],
    layer_idx: int,
    layers: list[list[str]],
    runtime: DispatchRuntime,
    completed_outputs: dict[str, dict],
    task_results: list[TaskResult],
    total_cost: float,
    mission_budget_usd: float,
    gate: GateReviewer,
    gate_decisions: list[GateDecisionRecord],
    mission_id: str | None,
    context_curator: ContextCuratorProtocol | None,
    project_context: dict | None,
    event_bus: EventBusProtocol,
    session_id: str,
    session_factory: Any | None = None,
) -> dict | None:
    """Execute a single layer of tasks. Returns accumulated metrics or abort signal."""
    coros = []
    layer_tasks: list[TaskDefinition] = []

    for task_id in layer:
        task = plan.get_task(task_id)
        if task is None:
            continue

        # A task that cannot start fails now, without waiting for approval.
        failure = precheck_task(task, runtime.roster, completed_outputs)
        if failure is not None:
            task_results.append(failed_result(task, failure))
            await emit_task_failure(
                event_bus, session_id, mission_id, task.task_id, task.agent, failure.summary
            )
            continue

        layer_tasks.append(task)
        coros.append(
            run_single_task(
                task=task,
                runtime=runtime,
                upstream_outputs=completed_outputs,
                mission_id=plan.mission_id,
                budget_usd=mission_budget_usd,
                event_bus=event_bus,
                session_id=session_id,
                gate=gate,
                project_context=project_context,
            )
        )

    if not coros:
        return None

    # Plan 80h: pre_layer gate removed. Pre-execution approval is the
    # task lifecycle. Wait until every task in this layer is APPROVED
    # before dispatching. For autonomous mode the rule engine has
    # already transitioned them, so this is fast. For interactive modes
    # the operator approves each task via `mc plan approve <id>`.
    from modules.backend.agents.mission_control.task_approval import wait_until_approved

    if session_factory is None:
        from modules.backend.core.database import get_session_factory

        session_factory = get_session_factory()
    manual = get_app_config().gate.manual
    waiters = [
        wait_until_approved(
            task_id=t.task_id,
            session_factory=session_factory,
            timeout_seconds=manual.timeout_seconds,
            poll_interval_seconds=manual.poll_interval_seconds,
        )
        for t in layer_tasks
    ]
    if waiters:
        await asyncio.gather(*waiters)

    results = await asyncio.gather(*coros, return_exceptions=True)

    total_input_tokens = 0
    total_output_tokens = 0
    total_thinking_tokens = 0

    for task, result in zip(layer_tasks, results):
        if isinstance(result, Exception):
            failure = get_failure_classifier().from_exception(result)
            task_results.append(failed_result(task, failure))
            await emit_task_failure(
                event_bus, session_id, mission_id, task.task_id, task.agent, failure.summary
            )
            continue

        task_result: TaskResult = result
        task_results.append(task_result)

        if task_result.status == TaskStatus.SUCCESS:
            completed_outputs[task.task_id] = task_result.output_reference

            if context_curator and mission_id and task_result.context_updates:
                try:
                    await context_curator.apply_task_updates(
                        mission_id,
                        task_result.context_updates,
                        agent_id=task_result.agent_name,
                        task_id=task_result.task_id,
                        mission_run_id=None,
                    )
                except (OSError, ValueError, RuntimeError):
                    logger.warning(
                        "Context update failed (non-fatal)",
                        extra={"task_id": task_result.task_id, "mission_id": mission_id},
                        exc_info=True,
                    )

        total_cost += task_result.cost_usd
        total_input_tokens += task_result.token_usage.input
        total_output_tokens += task_result.token_usage.output
        total_thinking_tokens += task_result.token_usage.thinking

    decision = await gate.review(
        GateContext(
            gate_type="post_layer",
            mission_id=plan.mission_id,
            session_id=session_id,
            layer_index=layer_idx,
            total_layers=len(layers),
            completed_tasks=[r.model_dump() for r in task_results],
            total_cost_usd=total_cost,
            budget_usd=mission_budget_usd,
        )
    )
    gate_decisions.append(
        GateDecisionRecord(
            gate_type="post_layer",
            layer_index=layer_idx,
            action=decision.action.value,
            reason=decision.reason,
            reviewer=decision.reviewer,
        )
    )
    if decision.action == GateAction.ABORT:
        logger.info("Mission aborted at post_layer gate", extra={"layer": layer_idx})
        return {"aborted": True, "abort_reason": decision.reason}

    return {
        "total_cost": total_cost,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_thinking_tokens": total_thinking_tokens,
    }


def _build_outcome(
    plan: TaskPlan,
    task_results: list[TaskResult],
    total_cost: float,
    total_input_tokens: int,
    total_output_tokens: int,
    total_thinking_tokens: int,
    mission_budget_usd: float,
    aborted: bool,
    abort_reason: str | None,
    start_time: float,
    gate_decisions: list[GateDecisionRecord] | None = None,
) -> ExecutionOutcome:
    """Determine execution status and build the final ExecutionOutcome."""
    budget_exceeded = bool(mission_budget_usd and total_cost > mission_budget_usd)
    total_tasks = len(plan.tasks)
    successful_tasks = sum(1 for r in task_results if r.status == TaskStatus.SUCCESS)
    success_ratio = successful_tasks / total_tasks if total_tasks > 0 else 0.0

    critical_path_ids = set(plan.execution_hints.critical_path)
    critical_path_success = (
        all(
            any(r.task_id == cp_id and r.status == TaskStatus.SUCCESS for r in task_results)
            for cp_id in critical_path_ids
        )
        if critical_path_ids
        else True
    )

    if aborted:
        status = ExecutionStatus.FAILED
    elif budget_exceeded:
        status = ExecutionStatus.FAILED
    elif successful_tasks == total_tasks:
        status = ExecutionStatus.SUCCESS
    elif success_ratio >= plan.execution_hints.min_success_threshold and critical_path_success:
        status = ExecutionStatus.PARTIAL
    else:
        status = ExecutionStatus.FAILED

    total_duration = time.monotonic() - start_time

    return ExecutionOutcome(
        mission_id=plan.mission_id,
        status=status,
        task_results=task_results,
        total_cost_usd=round(total_cost, 6),
        total_duration_seconds=round(total_duration, 2),
        total_tokens=TaskTokenUsage(
            input=total_input_tokens,
            output=total_output_tokens,
            thinking=total_thinking_tokens,
        ),
        abort_reason=abort_reason,
        gate_decisions=gate_decisions or [],
    )
