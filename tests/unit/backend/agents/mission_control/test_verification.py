"""Tests for the 3-tier verification pipeline.

Tests each tier independently and the full pipeline flow.
Tier 3 tests use a mock execute_agent_fn — the Verification Agent
itself is tested separately with TestModel.
"""

import pytest

from modules.backend.agents.mission_control.verification import (
    TierStatus,
    VerificationResult,
    build_retry_feedback,
    run_verification_pipeline,
)

# ---- Fixtures ----


@pytest.fixture
def basic_task():
    """A minimal task dict with verification config."""
    return {
        "task_id": "task_001",
        "agent": "software.quality.agent",
        "instructions": "Scan the codebase for violations",
        "description": "QA scan",
        "verification": {
            "tier_1": {
                "schema_validation": True,
                "required_output_fields": ["summary", "violations"],
            },
            "tier_2": {
                "deterministic_checks": [],
            },
            "tier_3": {
                "requires_ai_evaluation": False,
            },
        },
    }


@pytest.fixture
def task_with_tier2(basic_task):
    """Task with Tier 2 deterministic checks configured."""
    basic_task["verification"]["tier_2"]["deterministic_checks"] = [
        {
            "check": "validate_field_exists",
            "params": {"fields": ["summary", "violations"]},
        },
        {
            "check": "validate_field_type",
            "params": {"field_types": {"summary": "str", "violations": "list"}},
        },
    ]
    return basic_task


@pytest.fixture
def task_with_tier3(basic_task):
    """Task with Tier 3 AI evaluation configured."""
    basic_task["verification"]["tier_3"] = {
        "requires_ai_evaluation": True,
        "evaluation_criteria": [
            "Analysis covers all critical code paths",
            "No false positives reported",
        ],
        "evaluator_agent": "system.verification.agent",
        "min_evaluation_score": 0.8,
    }
    return basic_task


@pytest.fixture
def valid_output():
    """Agent output that passes all tiers."""
    return {
        "summary": "Found 3 violations in 2 files",
        "violations": [
            {"file": "auth.py", "line": 42, "rule": "no-eval"},
        ],
    }


@pytest.fixture
def mock_verification_agent():
    """Mock execute_agent_fn that returns a passing evaluation.

    Returns the real executor envelope — {"output": ..., "_meta": ...} — as
    produced by helpers/agent_executor.execute_agent. These fixtures previously
    returned the inner dict flat, which no production caller ever emits; that
    hid a bug where _run_tier_3 read overall_score off the envelope and scored
    every evaluation 0.00.
    """

    async def _execute(agent_name, instructions, inputs, **kwargs):
        return {
            "output": {
                "overall_score": 0.92,
                "passed": True,
                "criteria_results": [
                    {
                        "criterion": "Analysis covers all critical code paths",
                        "score": 0.95,
                        "passed": True,
                        "evidence": "All code paths analyzed",
                        "issues": [],
                    },
                ],
                "blocking_issues": [],
                "recommendations": [],
                "_thinking_trace": "I evaluated the output...",
            },
            "_meta": {"cost_usd": 0.05, "input_tokens": 900, "output_tokens": 120},
        }

    return _execute


@pytest.fixture
def mock_failing_verification_agent():
    """Mock execute_agent_fn that returns a failing evaluation (real envelope)."""

    async def _execute(agent_name, instructions, inputs, **kwargs):
        return {
            "output": {
                "overall_score": 0.45,
                "passed": False,
                "criteria_results": [],
                "blocking_issues": ["Critical code path missed"],
                "recommendations": ["Expand analysis scope"],
                "_thinking_trace": "The output is insufficient...",
            },
            "_meta": {"cost_usd": 0.05, "input_tokens": 900, "output_tokens": 120},
        }

    return _execute


# Ensure built-in checks are registered
@pytest.fixture(autouse=True)
def _register_checks():
    from modules.backend.agents.mission_control.checks import builtin  # noqa: F401


# ---- Tier 1 Tests ----


class TestTier1:
    """Tests for Tier 1 structural validation."""

    @pytest.mark.asyncio
    async def test_passes_with_valid_output(self, basic_task, valid_output):
        result = await run_verification_pipeline(
            output=valid_output,
            task=basic_task,
            agent_interface=None,
        )
        assert result.tier_1.status == TierStatus.PASS

    @pytest.mark.asyncio
    async def test_fails_on_non_dict_output(self, basic_task):
        result = await run_verification_pipeline(
            output="not a dict",
            task=basic_task,
            agent_interface=None,
        )
        assert result.passed is False
        assert result.failed_tier == 1
        assert result.tier_1.status == TierStatus.FAIL

    @pytest.mark.asyncio
    async def test_fails_on_missing_required_fields(self, basic_task):
        result = await run_verification_pipeline(
            output={"summary": "ok"},  # missing "violations"
            task=basic_task,
            agent_interface=None,
        )
        assert result.passed is False
        assert result.failed_tier == 1
        assert "violations" in result.tier_1.details

    @pytest.mark.asyncio
    async def test_fails_on_empty_dict(self, basic_task):
        result = await run_verification_pipeline(
            output={},
            task=basic_task,
            agent_interface=None,
        )
        assert result.passed is False
        assert result.failed_tier == 1

    @pytest.mark.asyncio
    async def test_validates_against_agent_interface(self):
        task = {
            "task_id": "t1",
            "verification": {"tier_1": {"schema_validation": True}},
        }
        interface = {"output": {"analysis": "str", "confidence": "float"}}
        result = await run_verification_pipeline(
            output={"analysis": "done"},  # missing "confidence"
            task=task,
            agent_interface=interface,
        )
        assert result.passed is False
        assert "confidence" in result.tier_1.details

    @pytest.mark.asyncio
    async def test_skipped_when_disabled(self):
        task = {
            "task_id": "t1",
            "verification": {"tier_1": {"schema_validation": False}},
        }
        result = await run_verification_pipeline(
            output={"anything": True},
            task=task,
            agent_interface=None,
        )
        assert result.tier_1.status == TierStatus.SKIPPED


# ---- Tier 2 Tests ----


class TestTier2:
    """Tests for Tier 2 deterministic functional checks."""

    @pytest.mark.asyncio
    async def test_passes_with_valid_output(self, task_with_tier2, valid_output):
        result = await run_verification_pipeline(
            output=valid_output,
            task=task_with_tier2,
            agent_interface=None,
        )
        assert result.tier_2.status == TierStatus.PASS
        assert len(result.tier_2.check_results) == 2

    @pytest.mark.asyncio
    async def test_fails_on_check_failure(self, task_with_tier2):
        result = await run_verification_pipeline(
            output={"summary": 123, "violations": "not a list"},  # wrong types
            task=task_with_tier2,
            agent_interface=None,
        )
        assert result.passed is False
        assert result.failed_tier == 2
        assert result.tier_2.status == TierStatus.FAIL

    @pytest.mark.asyncio
    async def test_runs_all_checks_even_on_failure(self, task_with_tier2):
        """All checks run to collect complete diagnostic info."""
        # Output passes Tier 1 (has required fields) but fails Tier 2 (wrong types)
        result = await run_verification_pipeline(
            output={"summary": 123, "violations": "not a list"},
            task=task_with_tier2,
            agent_interface=None,
        )
        assert result.failed_tier == 2
        assert len(result.tier_2.check_results) == 2

    @pytest.mark.asyncio
    async def test_skipped_when_no_checks(self, basic_task, valid_output):
        result = await run_verification_pipeline(
            output=valid_output,
            task=basic_task,
            agent_interface=None,
        )
        assert result.tier_2.status == TierStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_does_not_run_if_tier1_fails(self, task_with_tier2):
        result = await run_verification_pipeline(
            output="not a dict",  # Tier 1 failure
            task=task_with_tier2,
            agent_interface=None,
        )
        assert result.failed_tier == 1
        assert result.tier_2 is None


# ---- Tier 3 Tests ----


class TestTier3:
    """Tests for Tier 3 AI evaluation."""

    @pytest.mark.asyncio
    async def test_passes_with_high_score(
        self,
        task_with_tier3,
        valid_output,
        mock_verification_agent,
    ):
        result = await run_verification_pipeline(
            output=valid_output,
            task=task_with_tier3,
            agent_interface=None,
            execute_agent_fn=mock_verification_agent,
        )
        assert result.tier_3.status == TierStatus.PASS
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_with_low_score(
        self,
        task_with_tier3,
        valid_output,
        mock_failing_verification_agent,
    ):
        result = await run_verification_pipeline(
            output=valid_output,
            task=task_with_tier3,
            agent_interface=None,
            execute_agent_fn=mock_failing_verification_agent,
        )
        assert result.tier_3.status == TierStatus.FAIL
        assert result.passed is False
        assert result.failed_tier == 3

    @pytest.mark.asyncio
    async def test_unwraps_executor_envelope(
        self,
        task_with_tier3,
        valid_output,
        mock_verification_agent,
    ):
        """The score and cost come from inside the executor envelope.

        Regression: _run_tier_3 used to read overall_score straight off
        {"output": ..., "_meta": ...}, so it always resolved to 0.0 and every
        Tier 3 evaluation failed with "Score: 0.00" no matter what the evaluator
        returned. Asserting the actual values — not just PASS — is what catches
        a re-flattening of this contract.
        """
        result = await run_verification_pipeline(
            output=valid_output,
            task=task_with_tier3,
            agent_interface=None,
            execute_agent_fn=mock_verification_agent,
        )
        assert result.tier_3.overall_score == 0.92
        assert result.tier_3.cost_usd == 0.05  # from _meta, not a top-level _cost_usd
        assert result.tier_3.status == TierStatus.PASS

    @pytest.mark.asyncio
    async def test_fails_loudly_when_evaluator_returns_non_dict(
        self,
        task_with_tier3,
        valid_output,
    ):
        """A non-dict evaluation must FAIL with a clear reason, not score 0.0.

        Scoring an unparseable evaluation as 0.0 is the failure mode this whole
        regression came from — silence that looks like a verdict.
        """

        async def _execute(agent_name, instructions, inputs, **kwargs):
            return {"output": "I could not evaluate this.", "_meta": {"cost_usd": 0.01}}

        result = await run_verification_pipeline(
            output=valid_output,
            task=task_with_tier3,
            agent_interface=None,
            execute_agent_fn=_execute,
        )
        assert result.tier_3.status == TierStatus.FAIL
        assert "expected a dict" in result.tier_3.details

    @pytest.mark.asyncio
    async def test_skipped_when_not_required(self, basic_task, valid_output):
        result = await run_verification_pipeline(
            output=valid_output,
            task=basic_task,
            agent_interface=None,
        )
        assert result.tier_3.status == TierStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_self_evaluation_prevention(self, valid_output):
        """Agent cannot evaluate its own output (P13)."""
        task = {
            "task_id": "t1",
            "agent": "system.verification.agent",
            "description": "Test task for self-evaluation prevention",
            "instructions": "Evaluate the output",
            "verification": {
                "tier_1": {"schema_validation": True},
                "tier_3": {
                    "requires_ai_evaluation": True,
                    "evaluation_criteria": ["test"],
                    "evaluator_agent": "system.verification.agent",
                    "min_evaluation_score": 0.8,
                },
            },
        }

        async def _should_not_be_called(agent_name, instructions, inputs, **kwargs):
            raise AssertionError("Self-evaluation should be prevented")

        result = await run_verification_pipeline(
            output=valid_output,
            task=task,
            agent_interface=None,
            execute_agent_fn=_should_not_be_called,
        )
        assert result.passed is False
        assert result.failed_tier == 3
        assert "Self-evaluation prevented" in result.tier_3.details

    @pytest.mark.asyncio
    async def test_skipped_when_no_criteria(self, valid_output):
        """Tier 3 skips (not fails) when evaluation_criteria is empty (P2)."""
        task = {
            "task_id": "t1",
            "agent": "software.quality.agent",
            "instructions": "Scan the codebase",
            "description": "QA scan",
            "verification": {
                "tier_1": {"schema_validation": True},
                "tier_3": {
                    "requires_ai_evaluation": True,
                    "evaluation_criteria": [],
                    "evaluator_agent": "system.verification.agent",
                    "min_evaluation_score": 0.8,
                },
            },
        }
        result = await run_verification_pipeline(
            output=valid_output,
            task=task,
            agent_interface=None,
        )
        assert result.passed is True
        assert result.tier_3.status == TierStatus.SKIPPED
        assert "No evaluation_criteria" in result.tier_3.details

    @pytest.mark.asyncio
    async def test_skipped_when_no_instructions_or_description(self, valid_output):
        """Tier 3 skips when task has no instructions or description."""
        task = {
            "task_id": "t1",
            "agent": "software.quality.agent",
            "verification": {
                "tier_1": {"schema_validation": True},
                "tier_3": {
                    "requires_ai_evaluation": True,
                    "evaluation_criteria": ["check quality"],
                    "evaluator_agent": "system.verification.agent",
                    "min_evaluation_score": 0.8,
                },
            },
        }
        result = await run_verification_pipeline(
            output=valid_output,
            task=task,
            agent_interface=None,
        )
        assert result.passed is True
        assert result.tier_3.status == TierStatus.SKIPPED
        assert "instructions or description" in result.tier_3.details

    @pytest.mark.asyncio
    async def test_skipped_when_output_only_has_meta(self):
        """Tier 3 skips when agent output is empty (only _meta)."""
        task = {
            "task_id": "t1",
            "agent": "software.quality.agent",
            "instructions": "Scan the codebase",
            "description": "QA scan",
            "verification": {
                "tier_1": {"schema_validation": False},
                "tier_3": {
                    "requires_ai_evaluation": True,
                    "evaluation_criteria": ["check quality"],
                    "evaluator_agent": "system.verification.agent",
                    "min_evaluation_score": 0.8,
                },
            },
        }
        output = {"_meta": {"input_tokens": 100, "cost_usd": 0.01}}
        result = await run_verification_pipeline(
            output=output,
            task=task,
            agent_interface=None,
        )
        assert result.passed is True
        assert result.tier_3.status == TierStatus.SKIPPED
        assert "empty" in result.tier_3.details

    @pytest.mark.asyncio
    async def test_does_not_run_if_tier1_fails(self, task_with_tier3):
        result = await run_verification_pipeline(
            output="not a dict",
            task=task_with_tier3,
            agent_interface=None,
        )
        assert result.failed_tier == 1
        assert result.tier_3 is None

    @pytest.mark.asyncio
    async def test_fails_without_execute_fn(self, task_with_tier3, valid_output):
        result = await run_verification_pipeline(
            output=valid_output,
            task=task_with_tier3,
            agent_interface=None,
            execute_agent_fn=None,
        )
        assert result.passed is False
        assert result.failed_tier == 3
        assert "no execute_agent_fn" in result.tier_3.details


# ---- Full Pipeline Tests ----


class TestFullPipeline:
    """Tests for the complete 3-tier pipeline flow."""

    @pytest.mark.asyncio
    async def test_all_tiers_pass(
        self,
        task_with_tier3,
        valid_output,
        mock_verification_agent,
    ):
        task_with_tier3["verification"]["tier_2"] = {
            "deterministic_checks": [
                {"check": "validate_field_exists", "params": {"fields": ["summary"]}},
            ],
        }
        result = await run_verification_pipeline(
            output=valid_output,
            task=task_with_tier3,
            agent_interface=None,
            execute_agent_fn=mock_verification_agent,
        )
        assert result.passed is True
        assert result.tier_1.status == TierStatus.PASS
        assert result.tier_2.status == TierStatus.PASS
        assert result.tier_3.status == TierStatus.PASS

    @pytest.mark.asyncio
    async def test_pipeline_stops_at_first_failure(self, task_with_tier3):
        task_with_tier3["verification"]["tier_2"] = {
            "deterministic_checks": [
                {"check": "validate_field_exists", "params": {"fields": ["x"]}},
            ],
        }
        result = await run_verification_pipeline(
            output="not a dict",
            task=task_with_tier3,
            agent_interface=None,
        )
        assert result.failed_tier == 1
        assert result.tier_2 is None
        assert result.tier_3 is None

    @pytest.mark.asyncio
    async def test_execution_time_tracked(self, basic_task, valid_output):
        result = await run_verification_pipeline(
            output=valid_output,
            task=basic_task,
            agent_interface=None,
        )
        assert result.total_execution_time_ms >= 0
        assert result.tier_1.execution_time_ms >= 0


# ---- Retry Feedback Tests ----


class TestBuildRetryFeedback:
    """Tests for build_retry_feedback."""

    def test_tier_1_feedback(self):
        from modules.backend.agents.mission_control.verification import TierResult

        result = VerificationResult(
            passed=False,
            failed_tier=1,
            tier_1=TierResult(
                tier=1,
                status=TierStatus.FAIL,
                details="Missing field: summary",
                execution_time_ms=0.1,
            ),
        )
        feedback = build_retry_feedback(result, attempt=1)
        assert feedback["failure_tier"] == 1
        assert "Missing field" in feedback["feedback_provided"]
        assert feedback["attempt"] == 1

    def test_passed_returns_empty(self):
        result = VerificationResult(passed=True)
        feedback = build_retry_feedback(result, attempt=1)
        assert feedback == {}
