"""Tests for execution record models."""

from modules.backend.models.execution_record import (
    DecisionType,
    FailureTier,
    ExecutionDecision,
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskAttempt,
    TaskAttemptStatus,
    TaskExecution,
    TaskExecutionStatus,
)


class TestExecutionRecordModel:
    def test_create_execution_record(self):
        record = ExecutionRecord(
            session_id="test-session",
            status=ExecutionRecordStatus.COMPLETED,
            roster_name="code_review",
            total_cost_usd=0.0123,
        )
        assert record.status == ExecutionRecordStatus.COMPLETED
        assert record.roster_name == "code_review"

    def test_execution_record_repr(self):
        record = ExecutionRecord(
            id="abc-123",
            session_id="test-session",
            status=ExecutionRecordStatus.FAILED,
            roster_name="research",
            total_cost_usd=1.50,
        )
        assert "research" in repr(record)
        assert "abc-123" in repr(record)

    def test_execution_record_with_objective(self):
        record = ExecutionRecord(
            session_id="test-session",
            status=ExecutionRecordStatus.COMPLETED,
            objective_statement="Improve code quality",
            objective_category="engineering",
            total_cost_usd=0.0,
        )
        assert record.objective_statement == "Improve code quality"
        assert record.objective_category == "engineering"


class TestTaskExecutionModel:
    def test_create_task_execution(self):
        execution = TaskExecution(
            execution_record_id="execution-123",
            task_id="analyze_code",
            agent_name="software.quality.agent",
            status=TaskExecutionStatus.COMPLETED,
            cost_usd=0.005,
        )
        assert execution.agent_name == "software.quality.agent"

    def test_task_execution_with_verification(self):
        execution = TaskExecution(
            execution_record_id="execution-123",
            task_id="summarize",
            agent_name="content.summarizer.agent",
            status=TaskExecutionStatus.COMPLETED,
            verification_outcome={
                "passed": True,
                "tier": "tier_1_structural",
                "details": "Output matches expected schema",
            },
        )
        assert execution.verification_outcome["passed"] is True


class TestTaskAttemptModel:
    def test_create_task_attempt(self):
        attempt = TaskAttempt(
            task_execution_id="exec-123",
            attempt_number=1,
            status=TaskAttemptStatus.FAILED,
            failure_tier=FailureTier.TIER_1_STRUCTURAL,
            failure_reason="Missing required field: summary",
            input_tokens=100,
            output_tokens=50,
        )
        assert attempt.attempt_number == 1
        assert attempt.failure_tier == FailureTier.TIER_1_STRUCTURAL


class TestExecutionDecisionModel:
    def test_create_decision(self):
        decision = ExecutionDecision(
            execution_record_id="execution-123",
            decision_type=DecisionType.RETRY,
            task_id="task_1",
            reasoning="Tier 1 validation failed, retrying with feedback",
        )
        assert decision.decision_type == DecisionType.RETRY
        assert decision.task_id == "task_1"


class TestEnums:
    def test_decision_types(self):
        assert DecisionType.RETRY.value == "retry"
        assert DecisionType.RE_PLAN.value == "re_plan"
        assert DecisionType.ESCALATE.value == "escalate"

    def test_failure_tiers(self):
        assert FailureTier.TIER_1_STRUCTURAL.value == "tier_1_structural"
        assert FailureTier.AGENT_ERROR.value == "agent_error"

    def test_execution_record_status(self):
        assert ExecutionRecordStatus.COMPLETED.value == "completed"
        assert ExecutionRecordStatus.TIMED_OUT.value == "timed_out"

    def test_task_execution_status(self):
        assert TaskExecutionStatus.COMPLETED.value == "completed"
        assert TaskExecutionStatus.SKIPPED.value == "skipped"

    def test_task_attempt_status(self):
        assert TaskAttemptStatus.PASSED.value == "passed"
        assert TaskAttemptStatus.FAILED.value == "failed"
