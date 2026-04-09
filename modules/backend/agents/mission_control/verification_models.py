"""Verification result models — TierStatus, TierResult, Tier3Result, VerificationResult."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TierStatus(str, Enum):
    """Verification tier outcome status."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TierResult:
    """Result from a single verification tier."""

    tier: int
    status: TierStatus
    details: str
    execution_time_ms: float
    check_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Tier3Result(TierResult):
    """Extended result for Tier 3 with AI evaluation details."""

    overall_score: float = 0.0
    criteria_results_reference: str = ""
    evaluator_thinking_trace_reference: str = ""
    cost_usd: float = 0.0


@dataclass
class VerificationResult:
    """Combined result of the full verification pipeline."""

    passed: bool
    tier_1: TierResult | None = None
    tier_2: TierResult | None = None
    tier_3: TierResult | Tier3Result | None = None
    failed_tier: int | None = None
    total_execution_time_ms: float = 0.0
