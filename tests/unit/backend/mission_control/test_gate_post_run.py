"""Tests for AutonomousPostRunReviewer — Plan 51 Phase C decision matrix.

Tests all 4 circuit breakers, 4 decision rules, budget headroom logic,
idempotency caching, and the normalize_task_content utility.

Uses real db_session (SQLite) per project testing principles. Rule-logic
tests omit execution_record_id from context so no FK chain is needed.
The cached-decision test (A.2.11) inserts real DB rows.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.agents.mission_control.gate_models import GateAction, GateContext
from modules.backend.agents.mission_control.gate_post_run import (
    AutonomousPostRunReviewer,
    normalize_task_content,
)
from modules.backend.models.mission_plan import GateMode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ledger(monkeypatch) -> AsyncMock:
    """The Haiku classifier writes an llm_calls row (88.4.6); capture it instead."""
    record = AsyncMock()
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.gate_post_run.record_llm_call", record
    )
    return record


def _context(
    *,
    budget_usd: float = 10.0,
    total_cost_usd: float = 0.0,
    supervisor_iteration_count: int = 0,
    recent_run_outcomes: list[dict] | None = None,
    approved: int = 0,
    proposed: int = 0,
    total_completed: int = 0,
    zero_completion_waves: int = 0,
    execution_record_id: str | None = None,
    mission_brief: str | None = None,
) -> GateContext:
    """Build a GateContext for post_run tests."""
    summary: dict = {
        "approved": approved,
        "proposed": proposed,
        "total_completed": total_completed,
        "zero_completion_waves": zero_completion_waves,
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


# ---------------------------------------------------------------------------
# A.2.2 — No supervisor iteration breaker (Plan 88 step 88.2.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_iteration_breaker(db_session: AsyncSession):
    reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
    ctx = _context(supervisor_iteration_count=500, proposed=1)

    decision = await reviewer.review(ctx)

    assert decision.action == GateAction.ADVANCE_APPROVED
    assert decision.rule != 2


# ---------------------------------------------------------------------------
# A.2.3 — Circuit breaker #3: Stall detection
# ---------------------------------------------------------------------------


class TestBreakerStall:
    @pytest.mark.asyncio
    async def test_stall_detected(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session, gate_mode=GateMode.AUTONOMOUS, stall_threshold=3
        )
        ctx = _context(
            recent_run_outcomes=[
                {"completed_task_count": 0},
                {"completed_task_count": 0},
                {"completed_task_count": 0},
            ]
        )

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert decision.rule == 3

    @pytest.mark.asyncio
    async def test_stall_within_run_after_early_success(self, db_session: AsyncSession):
        """The run's record shows a completion, yet three waves in a row completed nothing."""
        reviewer = AutonomousPostRunReviewer(
            db_session, gate_mode=GateMode.AUTONOMOUS, stall_threshold=3
        )
        ctx = _context(
            recent_run_outcomes=[{"completed_task_count": 1}],
            zero_completion_waves=3,
            proposed=1,
        )

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert decision.rule == 3

    @pytest.mark.asyncio
    async def test_no_stall_below_wave_threshold(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session, gate_mode=GateMode.AUTONOMOUS, stall_threshold=3
        )
        ctx = _context(
            recent_run_outcomes=[{"completed_task_count": 1}],
            zero_completion_waves=2,
            proposed=1,
        )

        decision = await reviewer.review(ctx)

        assert decision.rule != 3

    @pytest.mark.asyncio
    async def test_no_stall_when_some_completions(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session, gate_mode=GateMode.AUTONOMOUS, stall_threshold=3
        )
        ctx = _context(
            recent_run_outcomes=[
                {"completed_task_count": 0},
                {"completed_task_count": 1},  # breaks the stall
                {"completed_task_count": 0},
            ],
            proposed=1,
        )

        decision = await reviewer.review(ctx)

        assert decision.rule != 3

    @pytest.mark.asyncio
    async def test_not_enough_outcomes_for_stall(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session, gate_mode=GateMode.AUTONOMOUS, stall_threshold=3
        )
        ctx = _context(
            recent_run_outcomes=[
                {"completed_task_count": 0},
                {"completed_task_count": 0},
            ],
            proposed=1,
        )

        decision = await reviewer.review(ctx)

        assert decision.rule != 3


# ---------------------------------------------------------------------------
# A.2.4 — Circuit breaker #4: Budget headroom
# ---------------------------------------------------------------------------


class TestBreakerBudgetHeadroom:
    @pytest.mark.asyncio
    async def test_headroom_insufficient(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session,
            gate_mode=GateMode.AUTONOMOUS,
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
        assert decision.rule == "4-headroom"

    @pytest.mark.asyncio
    async def test_exhausted_caps_with_no_run_spend_escalates(self, db_session: AsyncSession):
        # Monthly or lifetime cap used up by earlier runs: this run spent 0
        # and has 0 headroom, so budget_usd = 0 + 0 (supervisor_activities).
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        ctx = _context(budget_usd=0.0, total_cost_usd=0.0, proposed=2)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert decision.rule == "4-headroom"

    @pytest.mark.asyncio
    async def test_headroom_sufficient(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        ctx = _context(
            budget_usd=100.0,
            total_cost_usd=1.0,
            proposed=2,
            total_completed=10,
        )

        decision = await reviewer.review(ctx)

        # Plenty of headroom → should advance (rule 5)
        assert decision.action == GateAction.ADVANCE_APPROVED
        assert decision.rule == 5


# ---------------------------------------------------------------------------
# A.2.5 — Rule #4: Approved tasks remaining
# ---------------------------------------------------------------------------


class TestRuleApprovedTasks:
    @pytest.mark.asyncio
    async def test_approved_tasks_wait(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        ctx = _context(approved=3)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.WAIT
        assert decision.rule == 4


# ---------------------------------------------------------------------------
# A.2.6–A.2.8 — Rules #5–7: Proposed tasks by gate_mode
# ---------------------------------------------------------------------------


class TestRuleProposedTasks:
    @pytest.mark.asyncio
    async def test_autonomous_mode_auto_advances(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        ctx = _context(proposed=2, total_completed=5, total_cost_usd=1.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ADVANCE_APPROVED
        assert decision.rule == 5

    @pytest.mark.asyncio
    async def test_ai_assisted_mode_advances(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AI_ASSISTED)
        ctx = _context(proposed=2, total_completed=5, total_cost_usd=1.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ADVANCE_APPROVED
        assert decision.rule == 6

    @pytest.mark.asyncio
    async def test_interactive_mode_escalates(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.INTERACTIVE)
        ctx = _context(proposed=2, total_completed=5, total_cost_usd=1.0)

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert decision.rule == 7


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
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
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
        assert decision.rule == "fallthrough"

    @pytest.mark.asyncio
    async def test_no_outcomes_falls_through(self, db_session: AsyncSession):
        """No approved, no proposed, no outcomes → fallthrough."""
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        ctx = _context(approved=0, proposed=0, recent_run_outcomes=[])

        decision = await reviewer.review(ctx)

        assert decision.action == GateAction.ESCALATE
        assert decision.rule == "fallthrough"


# ---------------------------------------------------------------------------
# A.2.10 — _check_budget_headroom pure logic
# ---------------------------------------------------------------------------


class TestCheckBudgetHeadroom:
    def test_zero_budget_is_exhausted_not_unlimited(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        ctx = _context(budget_usd=0, total_cost_usd=0.0)
        assert reviewer._check_budget_headroom(ctx, proposed_count=1) is False

    def test_remaining_exceeds_estimate(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(
            db_session,
            gate_mode=GateMode.AUTONOMOUS,
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
            gate_mode=GateMode.AUTONOMOUS,
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
            gate_mode=GateMode.AUTONOMOUS,
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
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        ctx = _context(budget_usd=5.0, total_cost_usd=6.0)
        assert reviewer._check_budget_headroom(ctx, proposed_count=1) is False


# ---------------------------------------------------------------------------
# A.2.11 — Cached decision (idempotency)
# ---------------------------------------------------------------------------


class TestCachedDecision:
    @pytest.mark.asyncio
    async def test_no_cached_row_returns_none(self, db_session: AsyncSession):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        result = await reviewer._get_cached_decision("00000000-0000-0000-0000-000000000000", 0)
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
                "iteration": 0,
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

        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        cached = await reviewer._get_cached_decision(record_id, 0)

        assert cached is not None
        assert cached.action == GateAction.ADVANCE_APPROVED
        assert cached.reviewer == "config:rule_engine"
        # The stored tail is decoded into fields, never left in the reason.
        assert cached.reason == "Auto-advancing 2 proposed tasks"
        assert cached.rule == 5

    @pytest.mark.asyncio
    async def test_unknown_action_falls_back_to_escalate(
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
            reasoning='Some reason\n__META__{"action": "not-an-action", "iteration": 0}',
        )
        db_session.add(row)
        await db_session.flush()

        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        cached = await reviewer._get_cached_decision(record_id, 0)

        assert cached is not None
        assert cached.action == GateAction.ESCALATE
        assert cached.reason == "Some reason"

    @pytest.mark.asyncio
    async def test_cache_scoped_to_iteration(self, db_session: AsyncSession):
        """One ExecutionRecord spans a run: iteration 1's decision is not replayed for 2."""
        from modules.backend.core.utils import utc_now
        from modules.backend.models.execution_record import (
            ExecutionRecord,
            ExecutionRecordStatus,
        )
        from modules.backend.models.session import Session, SessionStatus

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
        record_id = str(uuid.uuid4())
        db_session.add(
            ExecutionRecord(
                id=record_id,
                session_id=session.id,
                status=ExecutionRecordStatus.RUNNING.value,
            )
        )
        await db_session.flush()

        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        first = await reviewer.review(
            _context(proposed=2, supervisor_iteration_count=1, execution_record_id=record_id)
        )
        await db_session.flush()
        assert first.action == GateAction.ADVANCE_APPROVED

        assert await reviewer._get_cached_decision(record_id, 1) is not None
        assert await reviewer._get_cached_decision(record_id, 2) is None

        second = await reviewer.review(
            _context(
                zero_completion_waves=3,
                supervisor_iteration_count=2,
                execution_record_id=record_id,
            )
        )
        assert (second.action, second.rule) == (GateAction.ESCALATE, 3)


# ---------------------------------------------------------------------------
# The reason is human text: it is sent to events, notifications and prompts
# ---------------------------------------------------------------------------


class TestReasonIsHumanText:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("kwargs", "rule"),
        [
            ({"zero_completion_waves": 3}, 3),
            ({"approved": 0, "proposed": 0, "recent_run_outcomes": []}, "fallthrough"),
        ],
    )
    async def test_reason_carries_no_metadata(
        self,
        db_session: AsyncSession,
        kwargs: dict,
        rule: str | int,
    ):
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)

        decision = await reviewer.review(_context(**kwargs))

        assert decision.rule == rule
        assert decision.reason
        assert "__META__" not in decision.reason
        assert "{" not in decision.reason


class TestDecisionIsPersistedAndReadBack:
    @pytest.mark.asyncio
    async def test_stored_row_cached_read_and_api_agree_on_the_human_reason(
        self,
        db_session: AsyncSession,
    ):
        from modules.backend.core.decision_reasoning import decode_decision_reasoning
        from modules.backend.core.utils import utc_now
        from modules.backend.models.execution_record import (
            ExecutionRecord,
            ExecutionRecordStatus,
        )
        from modules.backend.models.session import Session, SessionStatus
        from modules.backend.schemas.execution_record import ExecutionDecisionResponse
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

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
        record_id = str(uuid.uuid4())
        db_session.add(
            ExecutionRecord(
                id=record_id,
                session_id=session.id,
                status=ExecutionRecordStatus.COMPLETED.value,
            )
        )
        await db_session.flush()

        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.AUTONOMOUS)
        decision = await reviewer.review(
            _context(zero_completion_waves=3, execution_record_id=record_id)
        )
        await db_session.flush()

        rows = await ExecutionPersistenceService(db_session).get_decisions(record_id)
        assert len(rows) == 1
        stored = decode_decision_reasoning(rows[0].reasoning)
        assert stored.human == decision.reason
        assert stored.meta["rule"] == decision.rule == 3
        assert stored.meta["action"] == decision.action.value

        cached = await reviewer.review(
            _context(zero_completion_waves=3, execution_record_id=record_id)
        )
        assert (cached.action, cached.reason, cached.rule) == (
            decision.action,
            decision.reason,
            decision.rule,
        )

        assert ExecutionDecisionResponse.model_validate(rows[0]).reasoning == decision.reason


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


# ---------------------------------------------------------------------------
# The classifier model comes from gate.yaml, not from the code
# ---------------------------------------------------------------------------


class TestClassifierModelComesFromConfig:
    @pytest.mark.asyncio
    async def test_the_configured_reviewer_model_is_used_and_recorded(
        self, db_session: AsyncSession, monkeypatch
    ):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from modules.backend.core.config import get_app_config

        monkeypatch.setattr(get_app_config().gate.ai, "model", "fixture:reviewer")
        fake_result = SimpleNamespace(
            output=SimpleNamespace(decision="ESCALATE", confidence=0.9, reason="needs a human"),
            usage=lambda: SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        fake_agent = MagicMock()
        fake_agent.run = AsyncMock(return_value=fake_result)
        create_agent = MagicMock(return_value=fake_agent)

        with patch(
            "modules.backend.agents.mission.supervisor.agent.create_event_agent", create_agent
        ):
            decision = await AutonomousPostRunReviewer(
                db_session, gate_mode=GateMode.AUTONOMOUS
            )._classify_with_haiku(_context())

        create_agent.assert_called_once_with("fixture:reviewer")
        assert decision.reviewer == "ai:fixture:reviewer"


class TestClassifierPromptSeparatesCurrentRun:
    @pytest.mark.asyncio
    async def test_current_run_record_is_labelled_not_listed_as_a_previous_run(
        self, db_session: AsyncSession
    ):
        """The run under review is still RUNNING at gate time; it must not read as a prior run."""
        fake_result = SimpleNamespace(
            output=SimpleNamespace(decision="PROPOSE_COMPLETE", confidence=0.9, reason="done"),
            usage=lambda: SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        fake_agent = MagicMock()
        fake_agent.run = AsyncMock(return_value=fake_result)
        outcomes = [
            {"execution_record_id": "rec-current", "status": "running", "completed_task_count": 1},
            {"execution_record_id": "rec-prev", "status": "completed", "completed_task_count": 1},
        ]

        with patch(
            "modules.backend.agents.mission.supervisor.agent.create_event_agent",
            MagicMock(return_value=fake_agent),
        ):
            await AutonomousPostRunReviewer(
                db_session, gate_mode=GateMode.AUTONOMOUS
            )._classify_with_haiku(
                _context(recent_run_outcomes=outcomes, execution_record_id="rec-current")
            )

        prompt = fake_agent.run.await_args.args[0]
        current_section, rest = prompt.split("Previous runs' outcomes")
        previous_section = rest.split("Plan task summary")[0]
        assert "This run's execution record" in current_section
        assert "rec-current" in current_section
        assert "rec-prev" not in current_section
        assert "rec-prev" in previous_section
        assert "rec-current" not in previous_section


# ---------------------------------------------------------------------------
# GateMode.MANUAL defers to the manual reviewer
# ---------------------------------------------------------------------------


class TestFailClosedGateMode:
    @pytest.mark.asyncio
    async def test_manual_gate_mode_uses_manual_reviewer(self, db_session: AsyncSession):
        from modules.backend.agents.mission_control.gate_manual import ManualGateReviewer
        from modules.backend.agents.mission_control.gate_models import GateDecision

        manual_decision = GateDecision(action=GateAction.ESCALATE, reviewer="manual")
        reviewer = AutonomousPostRunReviewer(db_session, gate_mode=GateMode.MANUAL)
        with patch.object(
            ManualGateReviewer, "review", new_callable=AsyncMock, return_value=manual_decision
        ) as review:
            decision = await reviewer.review(_context(proposed=2))

        review.assert_awaited_once()
        assert decision is manual_decision
