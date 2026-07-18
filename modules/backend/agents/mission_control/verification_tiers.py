"""Verification tier implementations — Tier 1, 2, and 3 checks."""

from __future__ import annotations

import time
from typing import Any

from modules.backend.agents.mission_control.models import ExecuteAgentFn
from modules.backend.agents.mission_control.verification_models import (
    Tier3Result,
    TierResult,
    TierStatus,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _elapsed_ms(start: float) -> float:
    """Calculate elapsed time in milliseconds since start."""
    return round((time.perf_counter() - start) * 1000, 3)


async def _run_tier_1(
    output: dict[str, Any],
    verification_config: dict[str, Any],
    agent_interface: dict[str, Any] | None,
) -> TierResult:
    """Tier 1: Structural validation against agent interface contract."""
    start = time.perf_counter()

    tier_1_config = verification_config.get("tier_1", {})
    schema_validation = tier_1_config.get("schema_validation", True)

    if not schema_validation:
        return TierResult(
            tier=1,
            status=TierStatus.SKIPPED,
            details="Schema validation disabled for this task",
            execution_time_ms=_elapsed_ms(start),
        )

    if not isinstance(output, dict):
        return TierResult(
            tier=1,
            status=TierStatus.FAIL,
            details=f"Output is not a dict: got {type(output).__name__}",
            execution_time_ms=_elapsed_ms(start),
        )

    if not output:
        return TierResult(
            tier=1,
            status=TierStatus.FAIL,
            details="Output is an empty dict",
            execution_time_ms=_elapsed_ms(start),
        )

    errors = []

    if agent_interface:
        expected_output_fields = agent_interface.get("output", {})
        for field_name in expected_output_fields:
            if field_name not in output:
                errors.append(f"Missing interface field: '{field_name}'")

    required_fields = tier_1_config.get("required_output_fields", [])
    for field_name in required_fields:
        if field_name not in output:
            errors.append(f"Missing required field: '{field_name}'")

    if errors:
        return TierResult(
            tier=1,
            status=TierStatus.FAIL,
            details=f"{len(errors)} structural error(s): {'; '.join(errors)}",
            execution_time_ms=_elapsed_ms(start),
        )

    return TierResult(
        tier=1,
        status=TierStatus.PASS,
        details="Structural validation passed",
        execution_time_ms=_elapsed_ms(start),
    )


async def _run_tier_2(
    output: dict[str, Any],
    verification_config: dict[str, Any],
) -> TierResult:
    """Tier 2: Deterministic functional checks from the check registry.

    Runs ALL specified checks (even if one fails) to collect complete
    diagnostic information.
    """
    start = time.perf_counter()

    tier_2_config = verification_config.get("tier_2", {})
    checks = tier_2_config.get("deterministic_checks", [])

    if not checks:
        return TierResult(
            tier=2,
            status=TierStatus.SKIPPED,
            details="No deterministic checks specified",
            execution_time_ms=_elapsed_ms(start),
        )

    from modules.backend.agents.mission_control.check_registry import get_check

    check_results = []
    failed_checks = []

    for check_spec in checks:
        check_name = check_spec.get("check", "")
        check_params = check_spec.get("params", {})

        check_fn = get_check(check_name)
        if check_fn is None:
            check_results.append(
                {
                    "check": check_name,
                    "passed": False,
                    "details": f"Check '{check_name}' not found in registry",
                    "execution_time_ms": 0.0,
                }
            )
            failed_checks.append(check_name)
            continue

        try:
            cr = await check_fn(output, check_params)
            check_results.append(
                {
                    "check": check_name,
                    "passed": cr.passed,
                    "details": cr.details,
                    "execution_time_ms": cr.execution_time_ms,
                }
            )
            if not cr.passed:
                failed_checks.append(check_name)
        except Exception as exc:
            check_results.append(
                {
                    "check": check_name,
                    "passed": False,
                    "details": f"Check raised exception: {exc}",
                    "execution_time_ms": _elapsed_ms(start),
                }
            )
            failed_checks.append(check_name)
            logger.error(
                "Tier 2 check raised exception",
                extra={"check": check_name, "error": str(exc)},
                exc_info=True,
            )

    checks_run = len(check_results)

    if failed_checks:
        return TierResult(
            tier=2,
            status=TierStatus.FAIL,
            details=(
                f"{len(failed_checks)}/{checks_run} checks failed: " f"{', '.join(failed_checks)}"
            ),
            execution_time_ms=_elapsed_ms(start),
            check_results=check_results,
        )

    return TierResult(
        tier=2,
        status=TierStatus.PASS,
        details=f"All {checks_run} checks passed",
        execution_time_ms=_elapsed_ms(start),
        check_results=check_results,
    )


async def _run_tier_3(
    output: dict[str, Any],
    task: dict[str, Any],
    verification_config: dict[str, Any],
    execute_agent_fn: ExecuteAgentFn | None = None,
    session_id: str | None = None,
) -> TierResult | Tier3Result:
    """Tier 3: AI-based quality evaluation via Verification Agent."""
    start = time.perf_counter()

    tier_3_config = verification_config.get("tier_3", {})
    requires_evaluation = tier_3_config.get("requires_ai_evaluation", False)

    if not requires_evaluation:
        return TierResult(
            tier=3,
            status=TierStatus.SKIPPED,
            details="AI evaluation not required for this task",
            execution_time_ms=_elapsed_ms(start),
        )

    evaluation_criteria = tier_3_config.get("evaluation_criteria", [])
    evaluator_agent = tier_3_config.get("evaluator_agent", "verification_agent")
    min_score = tier_3_config.get("min_evaluation_score", 0.8)

    # Pre-flight validation (P2: deterministic over non-deterministic)
    if not evaluation_criteria:
        logger.warning(
            "Tier 3 skipped: no evaluation_criteria provided",
            extra={"task_id": task.get("task_id")},
        )
        return TierResult(
            tier=3,
            status=TierStatus.SKIPPED,
            details="No evaluation_criteria provided — nothing to evaluate against",
            execution_time_ms=_elapsed_ms(start),
        )

    task_instructions = task.get("instructions", "")
    task_description = task.get("description", "")

    if not task_instructions and not task_description:
        logger.warning(
            "Tier 3 skipped: no task instructions or description",
            extra={"task_id": task.get("task_id")},
        )
        return TierResult(
            tier=3,
            status=TierStatus.SKIPPED,
            details="No task instructions or description — evaluator lacks context",
            execution_time_ms=_elapsed_ms(start),
        )

    agent_output = {k: v for k, v in output.items() if k != "_meta"}
    if not agent_output:
        logger.warning(
            "Tier 3 skipped: agent output is empty (ignoring _meta)",
            extra={"task_id": task.get("task_id")},
        )
        return TierResult(
            tier=3,
            status=TierStatus.SKIPPED,
            details="Agent output is empty — nothing to evaluate",
            execution_time_ms=_elapsed_ms(start),
        )

    if execute_agent_fn is None:
        return TierResult(
            tier=3,
            status=TierStatus.FAIL,
            details="Tier 3 required but no execute_agent_fn provided",
            execution_time_ms=_elapsed_ms(start),
        )

    # Self-evaluation prevention (P13)
    task_agent = task.get("agent", "")
    if evaluator_agent == task_agent:
        return TierResult(
            tier=3,
            status=TierStatus.FAIL,
            details=(
                f"Self-evaluation prevented: task agent '{task_agent}' "
                f"cannot be its own evaluator (P13)"
            ),
            execution_time_ms=_elapsed_ms(start),
        )

    evaluation_context = {
        "task_instructions": task_instructions,
        "task_description": task_description,
        "evaluation_criteria": evaluation_criteria,
        "agent_output": agent_output,
        "upstream_context": task.get("inputs", {}).get("static", {}),
    }

    try:
        from pydantic_ai import UsageLimits

        evaluation = await execute_agent_fn(
            agent_name=evaluator_agent,
            instructions="Evaluate the agent output against the provided criteria.",
            inputs=evaluation_context,
            usage_limits=UsageLimits(request_limit=10),
        )

        overall_score = evaluation.get("overall_score", 0.0)
        blocking_issues = evaluation.get("blocking_issues", [])
        cost_usd = evaluation.get("_cost_usd", 0.0)

        passed = overall_score >= min_score and len(blocking_issues) == 0

        status = TierStatus.PASS if passed else TierStatus.FAIL
        details = (
            f"Score: {overall_score:.2f} (threshold: {min_score:.2f}), "
            f"blocking issues: {len(blocking_issues)}"
        )

        if not passed:
            if blocking_issues:
                details += f" — issues: {'; '.join(blocking_issues[:5])}"
            if overall_score < min_score:
                details += " — score below threshold"

        criteria_reference = f"verification:{task.get('task_id', 'unknown')}:criteria"
        trace_reference = f"verification:{task.get('task_id', 'unknown')}:thinking"

        return Tier3Result(
            tier=3,
            status=status,
            details=details,
            execution_time_ms=_elapsed_ms(start),
            overall_score=overall_score,
            criteria_results_reference=criteria_reference,
            evaluator_thinking_trace_reference=trace_reference,
            cost_usd=cost_usd,
        )

    except Exception as exc:
        logger.error(
            "Tier 3 evaluation failed",
            extra={"evaluator": evaluator_agent, "error": str(exc)},
            exc_info=True,
        )
        return TierResult(
            tier=3,
            status=TierStatus.FAIL,
            details=f"Verification Agent raised exception: {exc}",
            execution_time_ms=_elapsed_ms(start),
        )
