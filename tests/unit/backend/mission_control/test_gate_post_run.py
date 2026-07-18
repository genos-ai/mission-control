"""Tests for AutonomousPostRunReviewer — Plan 51 Phase C decision matrix.

Tests all 4 circuit breakers, 4 decision rules, budget headroom logic,
idempotency caching, and the normalize_task_content utility.

Uses real db_session (SQLite) per project testing principles. Rule-logic
tests omit execution_record_id from context so no FK chain is needed.
The cached-decision test (A.2.11) inserts real DB rows.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.agents.mission_control.gate_models import GateAction, GateContext
from modules.backend.agents.mission_control.gate_post_run import (
    AutonomousPostRunReviewer,
    normalize_task_content,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context(
    *,
    budget_usd: float = 10.0,
    total_cost_usd: float = 0.0,
    supervisor_iteration_count: int = 0,
    recent_run_outcomes: list[dict] | None = None,
    approved: int = 0,
    proposed: int = 0,
    total_completed: int = 0,
    max_supervisor_iterations: int = 20,
    execution_record_id: str | None = None,
    mission_brief: str | None = None,
) -> GateContext:
    """Build a GateContext for post_run tests."""
    summary: dict = {
        "approved": approved,
        "proposed": proposed,
        "total_completed": total_completed,
        "max_supervisor_iterations": max_supervisor_iterations,
    }
    if execution_record_id:
        summary["execution_record_id"] = execution_record_id
    return GateContext(
        gate_type="post_run",
        mission_id="test-mission",
        total_cost_usd=total_cost_usd,
        budget_usd=budget_usd,
        supervisor_iteration_count=supervisor_iteration_count,
        recent_run_outcomes=recent_run_outcomes or [],
        plan_task_summary=summary,
        mission_brief=mission_brief,
    )


def _parse_rule(decision) -> str | int:
    """Extract rule from decision reason's __META__ JSON tail."""
    reason = decision.reason or ""
    if "__META__" in reason:
        _, raw = reason.split("__META__", 1)
        return json.loads(raw).get("rule")
    return "unknown"


# ---------------------------------------------------------------------------
# A.2.1 — Circuit breaker #1: Budget exhausted
# ---------------------------------------------------------------------------


class TestBreakerBudgetExhausted:
    @pytest.mark.asyncio
    async def test_budget_exhausted(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(budget_usd=5.0, total_cost_usd=5.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == 1

    @pytest.mark.asyncio
    async def test_budget_exceeded(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(budget_usd=5.0, total_cost_usd=6.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == 1

    @pytest.mark.asyncio
    async def test_no_budget_ceiling_skips_breaker(self, db_session: AsyncSession):
        """budget_usd=0 means unlimited — breaker #1 should not fire."""
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(budget_usd=0, total_cost_usd=100.0, proposed=2)

        decision = await reviewer.review(ctx)

        # Should reach rule #5 (auto-advance), not breaker #1
        assert decision.action != GateAction.ESCALATE or _parse_rule(decision) != 1


# ---------------------------------------------------------------------------
# A.2.2 — Circuit breaker #2: Max supervisor iterations
# ---------------------------------------------------------------------------


class TestBreakerMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(supervisor_iteration_count=20, max_supervisor_iterations=20)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == 2

    @pytest.mark.asyncio
    async def test_below_max_iterations(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(
            supervisor_iteration_count=5,
            max_supervisor_iterations=20,
            proposed=1,
        )

        decision = await reviewer.review(ctx)

        assert _parse_rule(decision) != 2


# ---------------------------------------------------------------------------
# A.2.3 — Circuit breaker #3: Stall detection
# ---------------------------------------------------------------------------


class TestBreakerStall:
    @pytest.mark.asyncio
    async def test_stall_detected(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, stall_threshold=3)
        ctx = _context(
            recent_run_outcomes=[
                {"completed_task_count": 0},
                {"completed_task_count": 0},
                {"completed_task_count": 0},
            ]
        )

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == 3

    @pytest.mark.asyncio
    async def test_no_stall_when_some_completions(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, stall_threshold=3)
        ctx = _context(
            recent_run_outcomes=[
                {"completed_task_count": 0},
                {"completed_task_count": 1},  # breaks the stall
                {"completed_task_count": 0},
            ],
            proposed=1,
        )

        decision = await reviewer.review(ctx)

        assert _parse_rule(decision) != 3

    @pytest.mark.asyncio
    async def test_not_enough_outcomes_for_stall(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, stall_threshold=3)
        ctx = _context(
            recent_run_outcomes=[
                {"completed_task_count": 0},
                {"completed_task_count": 0},
            ],
            proposed=1,
        )

        decision = await reviewer.review(ctx)

        assert _parse_rule(decision) != 3


# ---------------------------------------------------------------------------
# A.2.4 — Circuit breaker #4: Budget headroom
# ---------------------------------------------------------------------------


class TestBreakerBudgetHeadroom:
    @pytest.mark.asyncio
    async def test_headroom_insufficient(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session,
            budget_safety_factor=1.5,
        )
        # Budget=10, spent=9, remaining=1.
        # 5 completed tasks at $9 total → avg $1.80/task.
        # 3 proposed × $1.80 × 1.5 safety = $8.10 estimated > $1 remaining.
        ctx = _context(
            budget_usd=10.0,
            total_cost_usd=9.0,
            proposed=3,
            total_completed=5,
        )

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == "4-headroom"

    @pytest.mark.asyncio
    async def test_headroom_sufficient(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(
            budget_usd=100.0,
            total_cost_usd=1.0,
            proposed=2,
            total_completed=10,
        )

        decision = await reviewer.review(ctx)

        # Plenty of headroom → should advance (rule 5)
        assert decision.action == GateAction.ADVANCE_APPROVED
        assert _parse_rule(decision) == 5


# ---------------------------------------------------------------------------
# A.2.5 — Rule #4: Approved tasks remaining
# ---------------------------------------------------------------------------


class TestRuleApprovedTasks:
    @pytest.mark.asyncio
    async def test_approved_tasks_wait(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(approved=3)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.WAIT
        assert _parse_rule(decision) == 4


# ---------------------------------------------------------------------------
# A.2.6–A.2.8 — Rules #5–7: Proposed tasks by gate_mode
# ---------------------------------------------------------------------------


class TestRuleProposedTasks:
    @pytest.mark.asyncio
    async def test_autonomous_mode_auto_advances(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode="autonomous")
        ctx = _context(proposed=2, total_completed=5, total_cost_usd=1.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ADVANCE_APPROVED
        assert _parse_rule(decision) == 5

    @pytest.mark.asyncio
    async def test_ai_assisted_mode_advances(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode="ai_assisted")
        ctx = _context(proposed=2, total_completed=5, total_cost_usd=1.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ADVANCE_APPROVED
        assert _parse_rule(decision) == 6

    @pytest.mark.asyncio
    async def test_interactive_mode_escalates(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode="interactive")
        ctx = _context(proposed=2, total_completed=5, total_cost_usd=1.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == 7


# ---------------------------------------------------------------------------
# A.2.9 — Rule #8: Plan exhausted → Haiku fallback
# ---------------------------------------------------------------------------


class TestRulePlanExhausted:
    @pytest.mark.asyncio
    async def test_haiku_failure_falls_through_to_escalate(
        self,
        db_session: AsyncSession,
    ):
        """When Haiku classification fails, reviewer falls through to ESCALATE."""
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(
            approved=0,
            proposed=0,
            recent_run_outcomes=[{"completed_task_count": 2}],
        )

        # Mock _classify_with_haiku to return None (simulates failure)
        # so the reviewer falls through to ESCALATE.
        with patch.object(
            reviewer, "_classify_with_haiku", new_callable=AsyncMock, return_value=None
        ):
            decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == "fallthrough"

    @pytest.mark.asyncio
    async def test_no_outcomes_falls_through(self, db_session: AsyncSession):
        """No approved, no proposed, no outcomes → fallthrough."""
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(approved=0, proposed=0, recent_run_outcomes=[])

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert _parse_rule(decision) == "fallthrough"


# ---------------------------------------------------------------------------
# A.2.10 — _check_budget_headroom pure logic
# ---------------------------------------------------------------------------


class TestCheckBudgetHeadroom:
    def test_no_ceiling_returns_true(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(budget_usd=0, total_cost_usd=100.0)
        assert reviewer._check_budget_headroom(ctx, proposed_count=10) is True

    def test_remaining_exceeds_estimate(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session,
            budget_safety_factor=1.5,
        )
        # Budget=100, spent=10, remaining=90.
        # 10 completed at $10 total → avg $1/task. 2 proposed × $1 × 1.5 = $3.
        ctx = _context(
            budget_usd=100.0,
            total_cost_usd=10.0,
            total_completed=10,
        )
        assert reviewer._check_budget_headroom(ctx, proposed_count=2) is True

    def test_remaining_less_than_estimate(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session,
            budget_safety_factor=1.5,
        )
        ctx = _context(
            budget_usd=10.0,
            total_cost_usd=9.5,
            total_completed=5,
        )
        # remaining=0.50, avg=1.90, 1 × 1.90 × 1.5 = 2.85 > 0.50
        assert reviewer._check_budget_headroom(ctx, proposed_count=1) is False

    def test_zero_completed_uses_cost_floor(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session,
            cost_floor_usd=0.50,
        )
        ctx = _context(
            budget_usd=10.0,
            total_cost_usd=0.0,
            total_completed=0,
        )
        # 3 × $0.50 = $1.50, remaining=$10 → headroom OK
        assert reviewer._check_budget_headroom(ctx, proposed_count=3) is True

    def test_already_over_ceiling(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        ctx = _context(budget_usd=5.0, total_cost_usd=6.0)
        assert reviewer._check_budget_headroom(ctx, proposed_count=1) is False


# ---------------------------------------------------------------------------
# A.2.11 — Cached decision (idempotency)
# ---------------------------------------------------------------------------


class TestCachedDecision:
    @pytest.mark.asyncio
    async def test_no_cached_row_returns_none(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session)
        result = await reviewer._get_cached_decision("00000000-0000-0000-0000-000000000000")
        assert result is None

    @pytest.mark.asyncio
    async def test_cached_row_returns_reconstructed_decision(
        self,
        db_session: AsyncSession,
    ):
        from modules.backend.core.utils import utc_now
        from modules.backend.models.execution_record import (
            DecisionType,
            ExecutionDecision,
            ExecutionRecord,
            ExecutionRecordStatus,
        )
        from modules.backend.models.session import Session, SessionStatus

        # Create a real session (FK target for execution_records)
        session = Session(
            status=SessionStatus.ACTIVE.value,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            last_activity_at=utc_now(),
            session_metadata={},
        )
        db_session.add(session)
        await db_session.flush()

        # Insert parent ExecutionRecord (required by FK)
        record_id = str(uuid.uuid4())
        record = ExecutionRecord(
            id=record_id,
            session_id=session.id,
            status=ExecutionRecordStatus.COMPLETED.value,
        )
        db_session.add(record)
        await db_session.flush()

        # Insert the cached decision row
        meta = json.dumps(
            {
                "action": "advance_approved",
                "reviewer": "config:rule_engine",
                "rule": 5,
                "model_metadata": None,
            }
        )
        row = ExecutionDecision(
            execution_record_id=record_id,
            decision_type=DecisionType.POST_RUN_SUPERVISOR.value,
            task_id=None,
            reasoning=f"Auto-advancing 2 proposed tasks\n__META__{meta}",
        )
        db_session.add(row)
        await db_session.flush()

        reviewer = AutonomousPostRunReviewer(db_session)
        cached = await reviewer._get_cached_decision(record_id)

        assert cached is not None
        assert cached.action == GateAction.ADVANCE_APPROVED
        assert cached.reviewer == "config:rule_engine"

    @pytest.mark.asyncio
    async def test_malformed_meta_falls_back_to_escalate(
        self,
        db_session: AsyncSession,
    ):
        from modules.backend.core.utils import utc_now
        from modules.backend.models.execution_record import (
            DecisionType,
            ExecutionDecision,
            ExecutionRecord,
            ExecutionRecordStatus,
        )
        from modules.backend.models.session import Session, SessionStatus

        # Create a real session (FK target for execution_records)
        malformed_session = Session(
            status=SessionStatus.ACTIVE.value,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            last_activity_at=utc_now(),
            session_metadata={},
        )
        db_session.add(malformed_session)
        await db_session.flush()

        record_id = str(uuid.uuid4())
        record = ExecutionRecord(
            id=record_id,
            session_id=malformed_session.id,
            status=ExecutionRecordStatus.COMPLETED.value,
        )
        db_session.add(record)
        await db_session.flush()

        row = ExecutionDecision(
            execution_record_id=record_id,
            decision_type=DecisionType.POST_RUN_SUPERVISOR.value,
            task_id=None,
            reasoning="Some reason\n__META__{invalid json!!!}",
        )
        db_session.add(row)
        await db_session.flush()

        reviewer = AutonomousPostRunReviewer(db_session)
        cached = await reviewer._get_cached_decision(record_id)

        assert cached is not None
        assert cached.action == GateAction.ESCALATE


# ---------------------------------------------------------------------------
# A.2.12 — normalize_task_content
# ---------------------------------------------------------------------------


class TestNormalizeTaskContent:
    def test_same_text_same_hash(self):
        h1 = normalize_task_content("Fix the bug", "Check the logs")
        h2 = normalize_task_content("Fix the bug", "Check the logs")
        assert h1 == h2

    def test_different_whitespace_same_hash(self):
        h1 = normalize_task_content("Fix  the   bug", "Check\n\tthe  logs")
        h2 = normalize_task_content("Fix the bug", "Check the logs")
        assert h1 == h2

    def test_different_case_same_hash(self):
        h1 = normalize_task_content("FIX THE BUG", "CHECK THE LOGS")
        h2 = normalize_task_content("fix the bug", "check the logs")
        assert h1 == h2

    def test_different_text_different_hash(self):
        h1 = normalize_task_content("Fix the bug", "Check the logs")
        h2 = normalize_task_content("Add a feature", "Write the code")
        assert h1 != h2
