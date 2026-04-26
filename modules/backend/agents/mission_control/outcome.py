"""DEPRECATED: Import from modules.backend.schemas.execution_outcome instead.

Re-exports all types for backward compatibility. The build_verification_outcome
function stays here because it imports from the verification module (agent layer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.backend.schemas.execution_outcome import (  # noqa: F401
    ExecutionOutcome,
    ExecutionStatus,
    FailedCheck,
    GateDecisionRecord,
    RetryHistoryEntry,
    TaskResult,
    TaskStatus,
    TaskTokenUsage,
    Tier1Outcome,
    Tier2Outcome,
    Tier3Outcome,
    VerificationOutcome,
)

if TYPE_CHECKING:
    from modules.backend.agents.mission_control.verification import VerificationResult

__all__ = [
    "ExecutionOutcome",
    "ExecutionStatus",
    "FailedCheck",
    "GateDecisionRecord",
    "RetryHistoryEntry",
    "TaskResult",
    "TaskStatus",
    "TaskTokenUsage",
    "Tier1Outcome",
    "Tier2Outcome",
    "Tier3Outcome",
    "VerificationOutcome",
    "build_verification_outcome",
]


def build_verification_outcome(
    result: VerificationResult,
) -> VerificationOutcome:
    """Convert internal VerificationResult to serializable VerificationOutcome."""
    from modules.backend.agents.mission_control.verification import (
        Tier3Result,
        TierStatus,
    )

    # Tier 1
    tier_1 = Tier1Outcome(
        status=result.tier_1.status.value if result.tier_1 else "skipped",
        details=result.tier_1.details if result.tier_1 else "",
    )

    # Tier 2
    if result.tier_2 and result.tier_2.status != TierStatus.SKIPPED:
        checks_run = len(result.tier_2.check_results)
        failed = [
            FailedCheck(check=cr["check"], reason=cr["details"])
            for cr in result.tier_2.check_results
            if not cr.get("passed")
        ]
        tier_2 = Tier2Outcome(
            status=result.tier_2.status.value,
            checks_run=checks_run,
            checks_passed=checks_run - len(failed),
            failed_checks=failed,
        )
    else:
        tier_2 = Tier2Outcome(
            status=result.tier_2.status.value if result.tier_2 else "skipped",
        )

    # Tier 3
    if result.tier_3 and isinstance(result.tier_3, Tier3Result):
        tier_3 = Tier3Outcome(
            status=result.tier_3.status.value,
            overall_score=result.tier_3.overall_score,
            criteria_results_reference=result.tier_3.criteria_results_reference,
            evaluator_thinking_trace_reference=result.tier_3.evaluator_thinking_trace_reference,
            cost_usd=result.tier_3.cost_usd,
        )
    else:
        tier_3 = Tier3Outcome(
            status=result.tier_3.status.value if result.tier_3 else "skipped",
        )

    return VerificationOutcome(tier_1=tier_1, tier_2=tier_2, tier_3=tier_3)
