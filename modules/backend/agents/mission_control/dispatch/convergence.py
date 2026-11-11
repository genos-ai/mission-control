"""Convergence loop executor.

Implements the iterative QA/fix cycle pattern: an evaluation agent
identifies issues, a remediation agent fixes them, and the cycle
repeats until quality gates are met or max_iterations is reached.

This is a new dispatch pattern — NOT an extension of retry_handler.
The retry handler handles single-task retry with verification feedback.
The convergence loop coordinates TWO different agents across multiple cycles.

Integration: called from dispatch/loop.py when a task has
type=convergence_loop in its input_data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from modules.backend.agents.mission_control.gate import (
    GateAction,
    GateContext,
    GateReviewer,
    NoOpGate,
)
from modules.backend.agents.mission_control.helpers import _emit
from modules.backend.agents.mission_control.models import (
    EventBusProtocol,
    ExecuteAgentFn,
)
from modules.backend.agents.mission_control.outcome import (
    TaskResult,
    TaskStatus,
    TaskTokenUsage,
)
from modules.backend.core.failure_classification import get_failure_classifier
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ConvergenceConfig:
    """Configuration for a convergence loop."""

    max_iterations: int = 5
    convergence_condition: str = "zero_critical_findings"
    convergence_threshold: float | None = None
    commit_per_cycle: bool = True
    final_verification: bool = False
    evaluation_agent: str = "software.quality.agent"
    remediation_agent: str = "software.coder.agent"
    evaluation_config: dict[str, Any] = field(default_factory=dict)
    remediation_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConvergenceConfig:
        """Create from task input_data['loop_config']."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CycleResult:
    """Result of a single evaluation/remediation cycle."""

    cycle_number: int
    findings_count: int = 0
    fixes_applied: int = 0
    convergence_metric: float | None = None
    converged: bool = False
    evaluation_result: TaskResult | None = None
    remediation_result: TaskResult | None = None


async def execute_convergence_loop(
    *,
    task_id: str,
    config: ConvergenceConfig,
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None = None,
    gate: GateReviewer | None = None,
    event_bus: EventBusProtocol,
    session_id: str | None = None,
) -> TaskResult:
    """Execute a bounded convergence loop.

    Alternates between evaluation and remediation agents until the
    convergence condition is met or max_iterations is reached.

    Args:
        task_id: ID of the convergence loop task in the plan
        config: Loop configuration (agents, conditions, limits)
        execute_agent_fn: Function to execute a single agent task
        mission_id: Mission context
        gate: Gate reviewer for inter-cycle decisions
        event_bus: Event bus for publishing convergence events. Required —
            pass a real SessionEventBus; NoOpEventBus is for tests only.
        session_id: Session for event publishing

    Returns:
        TaskResult summarizing the convergence loop outcome
    """
    _gate = gate or NoOpGate()
    _bus = event_bus
    _sid = session_id or ""

    cycles: list[CycleResult] = []
    total_cost = 0.0
    total_tokens = TaskTokenUsage()

    for cycle_num in range(1, config.max_iterations + 1):
        logger.info(
            "Convergence cycle starting",
            extra={
                "task_id": task_id,
                "cycle": cycle_num,
                "max_iterations": config.max_iterations,
            },
        )

        # --- Evaluation phase ---
        eval_result = await execute_agent_fn(
            agent_name=config.evaluation_agent,
            task_instructions=(
                f"Evaluate the codebase. Cycle {cycle_num}/{config.max_iterations}. "
                f"Convergence condition: {config.convergence_condition}. "
                f"Report all findings."
            ),
            resolved_inputs=config.evaluation_config,
        )

        findings_count = _extract_findings_count(eval_result)
        convergence_metric = _extract_metric(eval_result, config)
        converged = _check_convergence(
            config.convergence_condition,
            findings_count,
            convergence_metric,
            config.convergence_threshold,
        )

        cycle = CycleResult(
            cycle_number=cycle_num,
            findings_count=findings_count,
            convergence_metric=convergence_metric,
            converged=converged,
            evaluation_result=_to_task_result(
                f"{task_id}-eval-{cycle_num}",
                config.evaluation_agent,
                eval_result,
            ),
        )

        # Publish iteration event
        from modules.backend.events.types import ConvergenceIterationEvent

        await _emit(
            _bus,
            ConvergenceIterationEvent,
            session_id=_sid,
            source=f"convergence:{task_id}",
            loop_task_id=task_id,
            cycle_number=cycle_num,
            findings_count=findings_count,
            fixes_applied=0,
            convergence_metric=convergence_metric,
            converged=converged,
        )

        if converged:
            logger.info(
                "Convergence achieved",
                extra={"task_id": task_id, "cycle": cycle_num},
            )
            cycles.append(cycle)
            break

        # --- Gate check: should we continue? ---
        decision = await _gate.review(
            GateContext(
                gate_type="convergence_cycle",
                mission_id=mission_id,
                session_id=_sid,
                layer_index=cycle_num,
                total_layers=config.max_iterations,
                task_output=eval_result,
                pending_tasks=[
                    {
                        "task_id": f"{task_id}-fix-{cycle_num}",
                        "agent": config.remediation_agent,
                        "description": f"Fix {findings_count} findings (cycle {cycle_num})",
                    }
                ],
                total_cost_usd=total_cost,
                budget_usd=0,  # No per-loop budget — mission budget applies
            )
        )

        if decision.action == GateAction.ABORT:
            logger.info("Convergence loop aborted by gate", extra={"cycle": cycle_num})
            cycles.append(cycle)
            break

        # --- Remediation phase ---
        fix_instructions = (
            f"Fix the {findings_count} findings from the evaluation. "
            f"Cycle {cycle_num}/{config.max_iterations}."
        )
        if isinstance(eval_result, dict) and eval_result.get("output"):
            fix_instructions += f"\n\nFindings:\n{eval_result['output']}"

        fix_result = await execute_agent_fn(
            agent_name=config.remediation_agent,
            task_instructions=fix_instructions,
            resolved_inputs=config.remediation_config,
        )

        fixes_applied = _extract_fixes_count(fix_result)
        cycle.fixes_applied = fixes_applied
        cycle.remediation_result = _to_task_result(
            f"{task_id}-fix-{cycle_num}",
            config.remediation_agent,
            fix_result,
        )

        cycles.append(cycle)

        # Accumulate costs
        for r in (cycle.evaluation_result, cycle.remediation_result):
            if r and r.token_usage:
                total_tokens.input += r.token_usage.input
                total_tokens.output += r.token_usage.output
                total_tokens.thinking += r.token_usage.thinking
            if r:
                total_cost += r.cost_usd

    # --- Final clean verification (optional) ---
    final_converged = cycles[-1].converged if cycles else False
    verification_passed: bool | None = None

    if final_converged and config.final_verification:
        logger.info(
            "Running final clean verification",
            extra={"task_id": task_id},
        )
        verification_result = await _run_final_verification(
            task_id=task_id,
            config=config,
            execute_agent_fn=execute_agent_fn,
            event_bus=_bus,
            session_id=_sid,
        )
        verification_passed = verification_result.status == TaskStatus.SUCCESS
        total_cost += verification_result.cost_usd
        if verification_result.token_usage:
            total_tokens.input += verification_result.token_usage.input
            total_tokens.output += verification_result.token_usage.output
            total_tokens.thinking += verification_result.token_usage.thinking

        if not verification_passed:
            logger.warning(
                "Final verification failed — branch may not be deployable",
                extra={"task_id": task_id, "mission_id": mission_id},
            )

    # --- Build final result ---
    outcome = (
        "converged"
        if final_converged and verification_passed is not False
        else "verification_failed" if verification_passed is False else "max_iterations"
    )

    # Publish completion event
    from modules.backend.events.types import ConvergenceCompletedEvent

    await _emit(
        _bus,
        ConvergenceCompletedEvent,
        session_id=_sid,
        source=f"convergence:{task_id}",
        loop_task_id=task_id,
        total_cycles=len(cycles),
        final_metric=cycles[-1].convergence_metric if cycles else None,
        outcome=outcome,
    )

    agent_name = f"convergence({config.evaluation_agent},{config.remediation_agent})"
    converged_ok = outcome == "converged"
    return TaskResult(
        task_id=task_id,
        agent_name=agent_name,
        status=TaskStatus.SUCCESS if converged_ok else TaskStatus.FAILED,
        failure=(
            None
            if converged_ok
            else get_failure_classifier().agent_outcome(
                agent_name, f"convergence loop ended without converging: {outcome}"
            )
        ),
        output_reference={
            "outcome": outcome,
            "total_cycles": len(cycles),
            "final_verification_passed": verification_passed,
            "cycles": [
                {
                    "cycle": c.cycle_number,
                    "findings": c.findings_count,
                    "fixes": c.fixes_applied,
                    "metric": c.convergence_metric,
                    "converged": c.converged,
                }
                for c in cycles
            ],
        },
        cost_usd=total_cost,
        token_usage=total_tokens,
    )


async def _run_final_verification(
    *,
    task_id: str,
    config: ConvergenceConfig,
    execute_agent_fn: ExecuteAgentFn,
    event_bus: EventBusProtocol,
    session_id: str,
) -> TaskResult:
    """Run a clean-slate verification after convergence.

    Spins up the evaluation agent one final time in a fresh context
    to prove the codebase is clean. In container mode, this would
    use a fresh ephemeral container (bootstrap from zero, install,
    migrate, run full suite). In local mode, it re-runs the evaluator.

    The result determines whether a PR should be opened or the branch
    should be flagged for human review.
    """
    logger.info("Final verification: re-running evaluation from clean state")

    eval_result = await execute_agent_fn(
        agent_name=config.evaluation_agent,
        task_instructions=(
            "FINAL VERIFICATION — clean-slate check. "
            "Run the full evaluation suite. This is the last check "
            "before the branch is submitted for review. "
            "Report ALL findings, no matter how minor."
        ),
        resolved_inputs=config.evaluation_config,
    )

    findings = _extract_findings_count(eval_result)
    passed = findings == 0

    # Publish verification event
    from modules.backend.events.types import FinalVerificationEvent

    await _emit(
        event_bus,
        FinalVerificationEvent,
        session_id=session_id,
        source=f"convergence:{task_id}",
        loop_task_id=task_id,
        passed=passed,
        test_summary=f"{findings} findings" if not passed else "0 findings — clean",
        environment_mode="local",  # TODO: use actual environment mode
    )

    return _to_task_result(
        f"{task_id}-final-verify",
        config.evaluation_agent,
        eval_result,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_findings_count(result: Any) -> int:
    """Extract findings count from an agent result."""
    if isinstance(result, dict):
        output = result.get("output", {})
        if isinstance(output, dict):
            # Try common field names
            for key in ("findings_count", "violation_count", "issue_count", "findings"):
                val = output.get(key)
                if isinstance(val, int):
                    return val
                if isinstance(val, list):
                    return len(val)
    return 0


def _extract_fixes_count(result: Any) -> int:
    """Extract fixes count from an agent result."""
    if isinstance(result, dict):
        output = result.get("output", {})
        if isinstance(output, dict):
            for key in ("fixes_applied", "fix_count", "changes_made"):
                val = output.get(key)
                if isinstance(val, int):
                    return val
    return 0


def _extract_metric(result: Any, config: ConvergenceConfig) -> float | None:
    """Extract convergence metric from evaluation result."""
    if config.convergence_condition == "quality_threshold":
        if isinstance(result, dict):
            output = result.get("output", {})
            if isinstance(output, dict):
                return output.get("composite_score") or output.get("pqi_score")
    return None


def _check_convergence(
    condition: str,
    findings_count: int,
    metric: float | None,
    threshold: float | None,
) -> bool:
    """Check if the convergence condition is met."""
    if condition == "all_tests_pass":
        return findings_count == 0
    if condition == "zero_critical_findings":
        return findings_count == 0
    if condition == "zero_findings":
        return findings_count == 0
    if condition == "quality_threshold" and metric is not None and threshold is not None:
        return metric >= threshold
    return findings_count == 0  # default


def _to_task_result(
    task_id: str,
    agent_name: str,
    raw_result: Any,
) -> TaskResult:
    """Convert a raw agent execution result to a TaskResult."""
    if isinstance(raw_result, dict):
        success = bool(raw_result.get("success", True))
        return TaskResult(
            task_id=task_id,
            agent_name=agent_name,
            status=TaskStatus.SUCCESS if success else TaskStatus.FAILED,
            output_reference=raw_result.get("output", {}),
            cost_usd=raw_result.get("cost_usd", 0.0),
            token_usage=TaskTokenUsage(
                input=raw_result.get("input_tokens", 0),
                output=raw_result.get("output_tokens", 0),
            ),
            failure=(
                None
                if success
                else get_failure_classifier().agent_outcome(
                    agent_name, "agent reported success: False"
                )
            ),
        )
    return TaskResult(
        task_id=task_id,
        agent_name=agent_name,
        status=TaskStatus.FAILED,
        failure=get_failure_classifier().agent_outcome(
            agent_name, f"agent returned a non-dict result ({type(raw_result).__name__})"
        ),
    )
