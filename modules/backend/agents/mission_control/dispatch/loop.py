"""Dispatch loop — layer-by-layer task orchestration.

Executes a validated TaskPlan by sorting tasks topologically, running
each layer in parallel, resolving upstream inputs, injecting context,
and aggregating results into an ExecutionOutcome.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from modules.backend.agents.mission_control.dispatch.dag import (
    resolve_upstream_inputs,
    topological_sort,
)
from modules.backend.agents.mission_control.dispatch.result_builders import (
    aborted_outcome,
    failed_result,
    skipped_result,
)
from modules.backend.agents.mission_control.dispatch.step_executor import (
    execute_with_step_events,
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
    NoOpEventBus,
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
from modules.backend.core.logging import get_logger
from modules.backend.events.types import PlanCreatedEvent
from modules.backend.schemas.task_plan import TaskPlan

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
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
    execution_mode: str = "local",
) -> ExecutionOutcome:
    """Execute the dispatch loop for a validated TaskPlan.

    1. Topological sort into execution layers
    2. Execute each layer (parallel within layer, sequential across layers)
    3. Resolve from_upstream at dispatch time
    4. 3-tier verification after each task
    5. Retry with feedback on verification failure
    6. Aggregate results into ExecutionOutcome

    When gate is provided, pauses at key decision points for review.
    """
    start_time = time.monotonic()
    _gate = gate or NoOpGate()
    _bus = event_bus or NoOpEventBus()
    _sid = session_id or plan.mission_id
    layers = topological_sort(plan)

    if execution_mode != "local":
        logger.info(
            "Dispatch using non-local execution mode",
            extra={"execution_mode": execution_mode, "mission_id": plan.mission_id},
        )

    gate_decisions: list[GateDecisionRecord] = []

    decision = await _gate.review(GateContext(
        gate_type="pre_dispatch",
        mission_id=plan.mission_id,
        layer_index=0,
        total_layers=len(layers),
        pending_tasks=[
            {"task_id": t.task_id, "agent": t.agent, "description": t.description}
            for t in plan.tasks
        ],
        total_cost_usd=0.0,
        budget_usd=mission_budget_usd,
    ))
    gate_decisions.append(GateDecisionRecord(
        gate_type="pre_dispatch", layer_index=0,
        action=decision.action.value, reason=decision.reason,
        reviewer=decision.reviewer,
    ))
    if decision.action == GateAction.ABORT:
        logger.info("Mission aborted at pre_dispatch gate", extra={"reason": decision.reason})
        outcome = aborted_outcome(plan, decision.reason, start_time)
        outcome.gate_decisions = gate_decisions
        return outcome

    await _emit(_bus, PlanCreatedEvent,
        session_id=_sid,
        source=f"dispatch:{plan.mission_id}",
        plan_id=plan.mission_id,
        goal=plan.summary,
        step_count=len(plan.tasks),
        metadata={"task_plan_json": plan.model_dump_json()},
    )

    project_context = await _load_project_context(mission_id, context_curator)

    completed_outputs: dict[str, dict] = {}
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
            roster=roster,
            execute_agent_fn=execute_agent_fn,
            completed_outputs=completed_outputs,
            task_results=task_results,
            total_cost=total_cost,
            mission_budget_usd=mission_budget_usd,
            gate=_gate,
            gate_decisions=gate_decisions,
            mission_id=mission_id,
            context_curator=context_curator,
            context_assembler=context_assembler,
            project_context=project_context,
            event_bus=_bus,
            session_id=_sid,
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
    roster: Roster,
    execute_agent_fn: ExecuteAgentFn,
    completed_outputs: dict[str, dict],
    task_results: list[TaskResult],
    total_cost: float,
    mission_budget_usd: float,
    gate: GateReviewer,
    gate_decisions: list[GateDecisionRecord],
    mission_id: str | None,
    context_curator: ContextCuratorProtocol | None,
    context_assembler: ContextAssemblerProtocol | None,
    project_context: dict | None,
    event_bus: EventBusProtocol,
    session_id: str,
) -> dict | None:
    """Execute a single layer of tasks. Returns accumulated metrics or abort signal."""
    from modules.backend.schemas.task_plan import TaskDefinition

    coros = []
    layer_tasks: list[TaskDefinition] = []
    resolved_inputs_map: dict[str, dict] = {}

    for task_id in layer:
        task = plan.get_task(task_id)
        if task is None:
            continue

        # ── Convergence loop fork (Plan 51 Phase B) ──────────────────
        # If the task's static inputs declare type=convergence_loop,
        # route to execute_convergence_loop() instead of the standard
        # single-agent path. The convergence scaffold resolves its own
        # eval/remediation agents internally, so we skip the roster
        # check — it's not applicable here.
        if task.inputs.static.get("type") == "convergence_loop":
            try:
                resolved_inputs = resolve_upstream_inputs(task, completed_outputs)
            except KeyError as e:
                task_results.append(failed_result(task, str(e)))
                continue
            resolved_inputs = dict(resolved_inputs)
            layer_tasks.append(task)
            resolved_inputs_map[task.task_id] = resolved_inputs
            coros.append(
                _dispatch_convergence_loop(
                    task_id=task.task_id,
                    resolved_inputs=resolved_inputs,
                    execute_agent_fn=execute_agent_fn,
                    mission_id=plan.mission_id,
                    gate=gate,
                    event_bus=event_bus,
                    session_id=session_id,
                )
            )
            continue

        # ── Workflow task fork (Plan 53 Phase B) ──────────────────────
        # If the task's agent field starts with "workflow:", delegate to
        # WorkflowRunService instead of the standard single-agent path.
        if task.agent.startswith("workflow:"):
            workflow_name = task.agent.split(":", 1)[1]
            layer_tasks.append(task)
            coros.append(
                _dispatch_workflow_task(
                    task=task,
                    workflow_name=workflow_name,
                    mission_id=plan.mission_id,
                    event_bus=event_bus,
                    session_id=session_id,
                    gate=gate,
                )
            )
            continue

        # ── Standard agent task ──────────────────────────────────────
        roster_entry = roster.get_agent_by_name(task.agent)
        if roster_entry is None:
            task_results.append(failed_result(task, "Agent not found in roster"))
            continue

        try:
            resolved_inputs = resolve_upstream_inputs(task, completed_outputs)
        except KeyError as e:
            task_results.append(failed_result(task, str(e)))
            continue

        resolved_inputs = dict(resolved_inputs)

        await _inject_context(
            resolved_inputs=resolved_inputs,
            task=task,
            mission_id=mission_id,
            context_assembler=context_assembler,
            project_context=project_context,
        )

        layer_tasks.append(task)
        resolved_inputs_map[task.task_id] = resolved_inputs
        coros.append(
            execute_with_step_events(
                task=task,
                roster_entry=roster_entry,
                resolved_inputs=resolved_inputs,
                execute_agent_fn=execute_agent_fn,
                execution_id=str(uuid.uuid4()),
                gate=gate,
                mission_id=plan.mission_id,
                budget_usd=mission_budget_usd,
                event_bus=event_bus,
                session_id=session_id,
            )
        )

    if not coros:
        return None

    decision = await gate.review(GateContext(
        gate_type="pre_layer",
        mission_id=plan.mission_id,
        layer_index=layer_idx,
        total_layers=len(layers),
        pending_tasks=[
            {
                "task_id": t.task_id,
                "agent": t.agent,
                "description": t.description,
                "instructions": (t.instructions or "")[:500],
                "input_keys": list(resolved_inputs_map.get(t.task_id, {}).keys()),
            }
            for t in layer_tasks
        ],
        completed_tasks=[r.model_dump() for r in task_results],
        total_cost_usd=total_cost,
        budget_usd=mission_budget_usd,
    ))
    gate_decisions.append(GateDecisionRecord(
        gate_type="pre_layer", layer_index=layer_idx,
        action=decision.action.value, reason=decision.reason,
        reviewer=decision.reviewer,
    ))
    if decision.action == GateAction.ABORT:
        logger.info("Mission aborted at pre_layer gate", extra={"layer": layer_idx})
        for c in coros:
            c.close()
        return {"aborted": True, "abort_reason": decision.reason}
    if decision.action == GateAction.SKIP:
        for c in coros:
            c.close()
        for t in layer_tasks:
            task_results.append(skipped_result(t, decision.reason))
        return None

    results = await asyncio.gather(*coros, return_exceptions=True)

    total_input_tokens = 0
    total_output_tokens = 0
    total_thinking_tokens = 0

    for task, result in zip(layer_tasks, results):
        if isinstance(result, Exception):
            task_results.append(failed_result(task, str(result)))
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
                        mission_id_ref=mission_id,
                        task_id=task_result.task_id,
                    )
                except (OSError, ValueError, RuntimeError):
                    logger.warning(
                        "Context update failed (non-fatal)",
                        extra={"task_id": task_result.task_id},
                        exc_info=True,
                    )

        total_cost += task_result.cost_usd
        total_input_tokens += task_result.token_usage.input
        total_output_tokens += task_result.token_usage.output
        total_thinking_tokens += task_result.token_usage.thinking

    decision = await gate.review(GateContext(
        gate_type="post_layer",
        mission_id=plan.mission_id,
        layer_index=layer_idx,
        total_layers=len(layers),
        completed_tasks=[r.model_dump() for r in task_results],
        total_cost_usd=total_cost,
        budget_usd=mission_budget_usd,
    ))
    gate_decisions.append(GateDecisionRecord(
        gate_type="post_layer", layer_index=layer_idx,
        action=decision.action.value, reason=decision.reason,
        reviewer=decision.reviewer,
    ))
    if decision.action == GateAction.ABORT:
        logger.info("Mission aborted at post_layer gate", extra={"layer": layer_idx})
        return {"aborted": True, "abort_reason": decision.reason}

    return {
        "total_cost": total_cost,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_thinking_tokens": total_thinking_tokens,
    }


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
            extra={"task_id": task_id},
        )
        return TaskResult(
            task_id=task_id,
            agent_name="convergence",
            status=TaskStatus.FAILED,
            output_reference={
                "error": "convergence_loop task requires a 'loop_config' dict "
                "in inputs.static, but none was found.",
            },
            cost_usd=0.0,
            token_usage=TaskTokenUsage(),
        )

    try:
        config = ConvergenceConfig.from_dict(loop_config_raw)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "convergence_loop task has invalid loop_config",
            extra={"task_id": task_id, "error": str(exc)},
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


async def _dispatch_workflow_task(
    *,
    task: Any,  # TaskDefinition — imported locally in _execute_layer
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

    await _emit(event_bus, PlanStepStartedEvent,
        session_id=session_id,
        source=f"dispatch:{mission_id}",
        plan_id=mission_id or "",
        step_id=task.task_id,
        step_name=task.description or task.task_id,
        assigned_agent=f"workflow:{workflow_name}",
    )

    status = TaskStatus.FAILED
    try:
        async with WorkflowRunService.factory() as svc:
            run = await svc.run_workflow(
                workflow_name=workflow_name,
                triggered_by="plan_dispatch",
                mission_id=mission_id or "",
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
        logger.error(
            "Workflow task dispatch failed",
            extra={"task_id": task.task_id, "workflow": workflow_name, "error": str(e), "mission_id": mission_id},
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
        await _emit(event_bus, PlanStepCompletedEvent,
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
    task: Any,
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
            resolved_inputs["project_context"] = assembled.get(
                "project_context", {}
            )
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
    successful_tasks = sum(
        1 for r in task_results if r.status == TaskStatus.SUCCESS
    )
    success_ratio = successful_tasks / total_tasks if total_tasks > 0 else 0.0

    critical_path_ids = set(plan.execution_hints.critical_path)
    critical_path_success = all(
        any(
            r.task_id == cp_id and r.status == TaskStatus.SUCCESS
            for r in task_results
        )
        for cp_id in critical_path_ids
    ) if critical_path_ids else True

    if aborted:
        status = ExecutionStatus.FAILED
    elif budget_exceeded:
        status = ExecutionStatus.FAILED
    elif successful_tasks == total_tasks:
        status = ExecutionStatus.SUCCESS
    elif (
        success_ratio >= plan.execution_hints.min_success_threshold
        and critical_path_success
    ):
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
