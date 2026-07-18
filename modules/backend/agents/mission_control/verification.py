"""3-tier verification pipeline for Mission Control.

Called by the dispatch loop's verify_task() hook after each agent returns
output. Each tier is cheaper and faster than the next. Execution stops
at the first tier failure.

Tier 1: Structural (code, zero tokens, milliseconds)
Tier 2: Deterministic functional (code, zero tokens)
Tier 3: AI evaluation (Verification Agent, Opus 4.6)

Models: verification_models.py
Tier implementations: verification_tiers.py
"""

from __future__ import annotations

from typing import Any

from modules.backend.agents.mission_control.models import ExecuteAgentFn

# Re-export models so callers can import from here
from modules.backend.agents.mission_control.verification_models import (  # noqa: F401
    Tier3Result,
    TierResult,
    TierStatus,
    VerificationResult,
)
from modules.backend.agents.mission_control.verification_tiers import (
    _elapsed_ms,
    _run_tier_1,
    _run_tier_2,
    _run_tier_3,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def run_verification_pipeline(
    output: dict[str, Any],
    task: dict[str, Any],
    agent_interface: dict[str, Any] | None,
    roster: dict[str, Any] | None = None,
    execute_agent_fn: ExecuteAgentFn | None = None,
    session_id: str | None = None,
) -> VerificationResult:
    """Execute the 3-tier verification pipeline.

    Args:
        output: Agent's actual output dict.
        task: TaskPlan task dict containing verification config.
        agent_interface: AgentInterfaceSchema dict for the agent.
        roster: Agent roster dict (used to validate evaluator_agent exists).
        execute_agent_fn: Async callable to dispatch the Verification Agent for Tier 3.
        session_id: Session ID for tracing.

    Returns:
        VerificationResult with per-tier results and overall pass/fail.
    """
    import time

    pipeline_start = time.perf_counter()
    result = VerificationResult(passed=True)
    verification_config = task.get("verification", {})

    tier_1_result = await _run_tier_1(output, verification_config, agent_interface)
    result.tier_1 = tier_1_result

    if tier_1_result.status == TierStatus.FAIL:
        result.passed = False
        result.failed_tier = 1
        result.total_execution_time_ms = _elapsed_ms(pipeline_start)
        logger.warning(
            "Verification failed at Tier 1",
            extra={"task_id": task.get("task_id"), "details": tier_1_result.details},
        )
        return result

    tier_2_result = await _run_tier_2(output, verification_config)
    result.tier_2 = tier_2_result

    if tier_2_result.status == TierStatus.FAIL:
        result.passed = False
        result.failed_tier = 2
        result.total_execution_time_ms = _elapsed_ms(pipeline_start)
        logger.warning(
            "Verification failed at Tier 2",
            extra={"task_id": task.get("task_id"), "details": tier_2_result.details},
        )
        return result

    tier_3_result = await _run_tier_3(
        output,
        task,
        verification_config,
        execute_agent_fn=execute_agent_fn,
        session_id=session_id,
    )
    result.tier_3 = tier_3_result

    if tier_3_result.status == TierStatus.FAIL:
        result.passed = False
        result.failed_tier = 3
        result.total_execution_time_ms = _elapsed_ms(pipeline_start)
        logger.warning(
            "Verification failed at Tier 3",
            extra={"task_id": task.get("task_id"), "details": tier_3_result.details},
        )
        return result

    result.total_execution_time_ms = _elapsed_ms(pipeline_start)
    logger.info(
        "Verification pipeline passed",
        extra={
            "task_id": task.get("task_id"),
            "tier_1_ms": tier_1_result.execution_time_ms,
            "tier_2_ms": tier_2_result.execution_time_ms,
            "tier_3_ms": tier_3_result.execution_time_ms,
        },
    )
    return result


def build_retry_feedback(
    verification_result: VerificationResult,
    attempt: int,
) -> dict[str, Any]:
    """Build feedback dict for retry-with-feedback (Reflection pattern).

    Returns:
        Dict with keys: attempt, failure_tier, failure_reason, feedback_provided.
    """
    if verification_result.passed:
        return {}

    failed_tier = verification_result.failed_tier
    feedback_parts = []

    if failed_tier == 1 and verification_result.tier_1:
        feedback_parts.append(f"Structural validation failed: {verification_result.tier_1.details}")

    elif failed_tier == 2 and verification_result.tier_2:
        feedback_parts.append(f"Deterministic checks failed: {verification_result.tier_2.details}")
        for check_result in verification_result.tier_2.check_results:
            if not check_result.get("passed"):
                feedback_parts.append(f"  - {check_result['check']}: {check_result['details']}")

    elif failed_tier == 3 and verification_result.tier_3:
        feedback_parts.append(f"Quality evaluation failed: {verification_result.tier_3.details}")
        if isinstance(verification_result.tier_3, Tier3Result):
            feedback_parts.append(f"  Score: {verification_result.tier_3.overall_score:.2f}")

    failure_reason = ""
    if failed_tier == 1 and verification_result.tier_1:
        failure_reason = verification_result.tier_1.details
    elif failed_tier == 2 and verification_result.tier_2:
        failure_reason = verification_result.tier_2.details
    elif failed_tier == 3 and verification_result.tier_3:
        failure_reason = verification_result.tier_3.details

    return {
        "attempt": attempt,
        "failure_tier": failed_tier,
        "failure_reason": failure_reason or "Unknown failure",
        "feedback_provided": "\n".join(feedback_parts),
    }
