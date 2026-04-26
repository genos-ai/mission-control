"""
Workflow Run Waves Mixin — extracted from workflow_run.py.

Contains the wave-execution engine: topological sorting of steps into
parallel waves, concurrent step dispatch within a wave, single-step
execution, and objective building. Separated because wave orchestration
is a distinct concern from run lifecycle management, definition
resolution, and notification.

Mixed into WorkflowRunService — do not instantiate directly.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger

if TYPE_CHECKING:
    from modules.backend.models.execution import WorkflowRun
    from modules.backend.schemas.workflow import WorkflowSchema, WorkflowStepSchema
    from modules.backend.services.execution import ExecutionService

logger = get_logger(__name__)


@dataclass
class VirtualExecution:
    """Lightweight stand-in for condition/notification nodes that don't create DB Execution records."""

    id: str
    status: str = "COMPLETED"
    total_cost_usd: float = 0.0
    error_data: dict = field(default_factory=dict)


class WorkflowRunWavesMixin:
    """Wave-execution methods for WorkflowRunService.

    Mixed into WorkflowRunService — do not instantiate directly.
    All methods reference self._execution_service_factory and
    self._workflow_service which are set by
    WorkflowRunService.__init__().
    """

    async def _execute_steps(
        self,
        run: WorkflowRun,
        workflow: WorkflowSchema,
        session_id: str,
        on_progress: Any | None = None,
        gate: object | None = None,
        edges: list[dict] | None = None,
    ) -> None:
        """Execute steps in topological wave order.

        Steps within a wave have no mutual dependencies and run in
        parallel via asyncio.gather. Each step gets its own DB session
        (via execution_service_factory) to avoid SQLAlchemy flush conflicts.
        Falls back to sequential execution when no factory is provided.
        """
        waves = self._compute_waves(workflow.steps)
        completed_outcomes: dict[str, dict] = {}
        step_map = {step.id: step for step in workflow.steps}
        total_steps = len(workflow.steps)

        # Build edge map: (source, target) → label (for condition routing)
        edges_map: dict[tuple[str, str], str | None] = {}
        for e in (edges or []):
            edges_map[(e.get("source", ""), e.get("target", ""))] = e.get("label")

        def _emit(event: dict) -> None:
            if on_progress:
                on_progress(event)

        _emit({"type": "workflow_start", "workflow": workflow.workflow_name, "total_steps": total_steps})

        for wave_num, wave_step_ids in enumerate(waves):
            logger.info(
                "Executing wave",
                extra={
                    "run_id": run.id,
                    "wave": wave_num + 1,
                    "steps": wave_step_ids,
                },
            )

            # Check budget before each wave
            if run.budget_usd and run.total_cost_usd >= run.budget_usd:
                raise RuntimeError(
                    f"Budget exceeded: ${run.total_cost_usd:.4f} >= "
                    f"${run.budget_usd:.2f}"
                )

            # Partition wave into skipped and executable steps
            executable_ids: list[str] = []
            for step_id in wave_step_ids:
                if self._should_skip(step_id, step_map, completed_outcomes, edges_map):
                    completed_outcomes[step_id] = {"_skipped": True}
                    _emit({
                        "type": "step_skipped",
                        "step_id": step_id,
                        "reason": "condition branch not taken",
                    })
                    logger.info("Skipping step (condition branch)", extra={"step_id": step_id, "run_id": run.id})
                else:
                    executable_ids.append(step_id)

            # Emit step_start for executable steps
            for step_id in executable_ids:
                step = step_map[step_id]
                _emit({
                    "type": "step_start",
                    "step_id": step_id,
                    "capability": step.capability,
                    "description": step.description or step_id,
                })

            # Execute all steps in this wave concurrently
            wave_steps = [step_map[sid] for sid in executable_ids]
            if not wave_steps:
                continue
            results = await self._execute_wave(
                run, wave_steps, session_id, completed_outcomes, gate=gate,
            )

            # Collect results sequentially (cost, outcomes, events)
            for step, (execution, extracted_outputs) in zip(wave_steps, results):
                completed_outcomes[step.id] = extracted_outputs
                run.total_cost_usd += execution.total_cost_usd
                status_str = execution.status if isinstance(execution.status, str) else execution.status.value
                _emit({
                    "type": "step_done",
                    "step_id": step.id,
                    "status": status_str,
                    "cost_usd": execution.total_cost_usd,
                    "completed_steps": len(completed_outcomes),
                    "total_steps": total_steps,
                })

    async def _execute_wave(
        self,
        run: WorkflowRun,
        steps: list[WorkflowStepSchema],
        session_id: str,
        completed_outcomes: dict[str, dict],
        gate: object | None = None,
    ) -> list[tuple[Any, dict]]:
        """Execute all steps in a wave concurrently.

        Each step gets its own DB session via the factory to avoid
        SQLAlchemy async flush conflicts.
        """
        if self._execution_service_factory is None:
            raise RuntimeError(
                "execution_service_factory is required to execute workflows"
            )

        async def _run_step(step: WorkflowStepSchema) -> tuple[Any, dict]:
            async with self._execution_service_factory() as execution_service:
                return await self._execute_step(
                    run, step, session_id, completed_outcomes,
                    execution_service, gate=gate,
                )

        results = await asyncio.gather(
            *[_run_step(step) for step in steps],
        )
        return list(results)

    async def _execute_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        session_id: str,
        completed_outcomes: dict[str, dict],
        execution_service: ExecutionService,
        gate: object | None = None,
    ) -> tuple[Any, dict]:
        """Execute a single workflow step, dispatching by node_type."""
        node_type = getattr(step, "node_type", "agent_step")

        if node_type == "condition":
            return await self._execute_condition_step(run, step, completed_outcomes)
        if node_type == "notification":
            return await self._execute_notification_step(run, step, completed_outcomes)

        # Default: agent_step — existing logic
        # Resolve upstream context from dependencies
        upstream = self._workflow_service.resolve_upstream_context(
            step, completed_outcomes, run.context,
        )

        # Build the objective from step description + input context
        step_input = upstream.get("_step_input", step.input)
        objective = self._build_step_objective(step, step_input)

        app_config = get_app_config()
        cost_ceiling = (
            step.cost_ceiling_usd
            or app_config.workflows.default_budget_usd
        )

        execution = await execution_service.create_execution_from_step(
            workflow_run_id=run.id,
            step_id=step.id,
            objective=objective,
            roster_ref=step.roster,
            complexity_tier=step.complexity_tier,
            cost_ceiling_usd=cost_ceiling,
            upstream_context=upstream,
            session_id=session_id,
            mission_id=run.mission_id,
        )

        logger.info(
            "Step execution created",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "execution_id": execution.id,
                "agent": f"{step.capability}.agent",
            },
        )

        execution = await execution_service.run_execution(execution.id, gate=gate)

        output_mapping = (
            step.output_mapping.model_dump()
            if step.output_mapping
            else None
        )
        extracted = execution_service.extract_outputs(
            execution, output_mapping,
        )

        status_str = execution.status if isinstance(execution.status, str) else execution.status.value
        logger.info(
            "Step completed",
            extra={
                "run_id": run.id,
                "step_id": step.id,
                "execution_id": execution.id,
                "status": status_str,
                "cost": execution.total_cost_usd,
            },
        )

        if status_str == "failed":
            raise RuntimeError(
                f"Step '{step.id}' execution failed: "
                f"{execution.error_data}"
            )

        return execution, extracted

    async def _execute_condition_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Evaluate a condition expression and return branch result."""
        from modules.backend.services.condition_evaluator import (
            ConditionEvaluationError,
            evaluate_condition,
        )

        config = step.condition_config
        expression = config.expression if config else ""

        try:
            result = evaluate_condition(expression, completed_outcomes, run.context)
        except ConditionEvaluationError as e:
            logger.error("Condition evaluation failed", extra={"step_id": step.id, "error": str(e)})
            raise RuntimeError(f"Condition '{step.id}' failed: {e}") from e

        branch = (config.true_label if result else config.false_label) if config else ("Yes" if result else "No")

        logger.info(
            "Condition evaluated",
            extra={"step_id": step.id, "expression": expression, "result": result, "branch": branch},
        )

        outputs = {"result": result, "branch": branch, "_branch": branch}
        return VirtualExecution(id=step.id), outputs

    async def _execute_notification_step(
        self,
        run: WorkflowRun,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
    ) -> tuple[VirtualExecution, dict]:
        """Send a notification via the configured channel."""
        from modules.backend.services.condition_evaluator import resolve_template
        from modules.backend.services.run_notifier import _dispatch_to_channels

        config = step.notification_config
        channel = config.channel if config else "sse"
        template = config.message_template if config else ""

        message = resolve_template(template, completed_outcomes, run.context)
        title = f"Workflow notification: {step.id}"

        try:
            await _dispatch_to_channels(
                [channel], title, message, "info",
                {"mission_id": run.mission_id, "run_id": run.id},
            )
            success = True
        except Exception:
            logger.warning("Notification step failed", extra={"step_id": step.id}, exc_info=True)
            success = False

        logger.info("Notification sent", extra={"step_id": step.id, "channel": channel, "success": success})
        outputs = {"sent": success, "channel": channel}
        return VirtualExecution(id=step.id), outputs

    @staticmethod
    def _should_skip(
        step_id: str,
        step_map: dict[str, WorkflowStepSchema],
        completed_outcomes: dict[str, dict],
        edges_map: dict[tuple[str, str], str | None],
    ) -> bool:
        """Check if a step should be skipped because a condition dependency took a different branch.

        A step is skipped when ANY of its dependencies is a condition node
        whose branch result does not match the edge label connecting them.
        If no edge label exists, the step always runs (backward-compatible).
        """
        step = step_map[step_id]
        for dep_id in step.depends_on:
            dep = step_map.get(dep_id)
            if dep is None:
                continue
            dep_type = getattr(dep, "node_type", "agent_step")
            if dep_type != "condition":
                # Also propagate skips: if a dependency was skipped, skip this step too
                dep_outcome = completed_outcomes.get(dep_id, {})
                if dep_outcome.get("_skipped"):
                    return True
                continue

            # Dependency is a condition node — check the branch
            dep_outcome = completed_outcomes.get(dep_id, {})
            if dep_outcome.get("_skipped"):
                return True
            branch_taken = dep_outcome.get("_branch")
            if branch_taken is None:
                continue  # condition hasn't run yet — shouldn't happen in wave order

            edge_label = edges_map.get((dep_id, step_id))
            if edge_label is None:
                continue  # no label on edge — always run
            if edge_label != branch_taken:
                return True

        return False

    def _build_step_objective(
        self,
        step: WorkflowStepSchema,
        step_input: dict[str, Any],
    ) -> str:
        """Build an objective string from the step definition and resolved input."""
        parts = [step.description or f"Execute step: {step.id}"]

        if step_input:
            context_parts = []
            for key, value in step_input.items():
                if isinstance(value, str):
                    context_parts.append(f"{key}: {value}")
                elif isinstance(value, list):
                    context_parts.append(f"{key}: {', '.join(str(v) for v in value)}")
            if context_parts:
                parts.append("Context: " + "; ".join(context_parts))

        return ". ".join(parts)

    @staticmethod
    def _compute_waves(
        steps: list[WorkflowStepSchema],
    ) -> list[list[str]]:
        """Topologically sort steps into execution waves.

        Steps with no unmet dependencies run in the same wave (parallel).
        Returns a list of waves, each wave is a list of step IDs.
        """
        # Build dependency graph
        in_degree: dict[str, int] = {}
        dependents: dict[str, list[str]] = defaultdict(list)

        for step in steps:
            in_degree[step.id] = len(step.depends_on)
            for dep in step.depends_on:
                dependents[dep].append(step.id)

        waves: list[list[str]] = []
        remaining = set(in_degree.keys())

        while remaining:
            # Find all steps with no unmet dependencies
            wave = [
                sid for sid in remaining
                if in_degree[sid] == 0
            ]

            if not wave:
                raise RuntimeError("Dependency cycle detected in workflow steps")

            waves.append(sorted(wave))

            # Remove completed steps and update degrees
            for sid in wave:
                remaining.remove(sid)
                for dependent in dependents[sid]:
                    in_degree[dependent] -= 1

        return waves
