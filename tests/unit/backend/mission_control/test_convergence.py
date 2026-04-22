"""Tests for the convergence loop — iterative QA/fix cycle (Plan 51 Phase B).

Covers: ConvergenceConfig, execute_convergence_loop(), helper extractors,
and convergence condition logic. All tests use mocked execute_agent_fn
(no real LLM calls).

Note: convergence.py calls execute_agent_fn with keyword args
agent_name=, task_instructions=, resolved_inputs= which differ from
the ExecuteAgentFn Protocol's positional names. Mocks accept **kwargs.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.backend.agents.mission_control.dispatch.convergence import (
    ConvergenceConfig,
    _check_convergence,
    _extract_findings_count,
    _extract_fixes_count,
    _extract_metric,
    _to_task_result,
    execute_convergence_loop,
)
from modules.backend.agents.mission_control.gate import GateAction, GateContext, GateDecision
from modules.backend.agents.mission_control.outcome import TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_result(
    findings_count: int = 0,
    *,
    fixes_applied: int = 0,
    cost_usd: float = 0.01,
    input_tokens: int = 100,
    output_tokens: int = 50,
    success: bool = True,
    composite_score: float | None = None,
) -> dict:
    """Build a mock agent result dict matching what execute_agent_fn returns."""
    output: dict = {}
    if findings_count > 0:
        output["findings_count"] = findings_count
    if fixes_applied > 0:
        output["fixes_applied"] = fixes_applied
    if composite_score is not None:
        output["composite_score"] = composite_score
    return {
        "output": output,
        "success": success,
        "summary": f"{findings_count} findings",
        "cost_usd": cost_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _make_executor(*results: dict) -> AsyncMock:
    """Build a mock execute_agent_fn that returns results in sequence."""
    fn = AsyncMock(side_effect=list(results))
    return fn


def _abort_gate() -> MagicMock:
    """Gate that always aborts."""
    gate = MagicMock()
    gate.review = AsyncMock(
        return_value=GateDecision(action=GateAction.ABORT, reason="test abort"),
    )
    return gate


# ---------------------------------------------------------------------------
# A.1.1 — ConvergenceConfig.from_dict
# ---------------------------------------------------------------------------


class TestConvergenceConfig:
    def test_valid_config(self):
        cfg = ConvergenceConfig.from_dict({
            "max_iterations": 3,
            "convergence_condition": "zero_findings",
            "evaluation_agent": "qa.agent",
            "remediation_agent": "coder.agent",
        })
        assert cfg.max_iterations == 3
        assert cfg.convergence_condition == "zero_findings"
        assert cfg.evaluation_agent == "qa.agent"
        assert cfg.remediation_agent == "coder.agent"

    def test_missing_optional_fields_use_defaults(self):
        cfg = ConvergenceConfig.from_dict({})
        assert cfg.max_iterations == 5
        assert cfg.convergence_condition == "zero_critical_findings"
        assert cfg.final_verification is False

    def test_unknown_fields_ignored(self):
        cfg = ConvergenceConfig.from_dict({
            "max_iterations": 2,
            "unknown_field": "should be dropped",
            "another_junk": 999,
        })
        assert cfg.max_iterations == 2
        assert not hasattr(cfg, "unknown_field")


# ---------------------------------------------------------------------------
# A.1.8–A.1.9 — Extraction helpers
# ---------------------------------------------------------------------------


class TestExtractFindingsCount:
    def test_int_value(self):
        assert _extract_findings_count({"output": {"findings_count": 5}}) == 5

    def test_list_value(self):
        assert _extract_findings_count({"output": {"findings": [1, 2, 3]}}) == 3

    def test_violation_count_key(self):
        assert _extract_findings_count({"output": {"violation_count": 7}}) == 7

    def test_non_dict_returns_zero(self):
        assert _extract_findings_count("not a dict") == 0

    def test_missing_output_key_returns_zero(self):
        assert _extract_findings_count({"other": "data"}) == 0

    def test_empty_output_dict_returns_zero(self):
        assert _extract_findings_count({"output": {}}) == 0

    def test_output_not_dict_returns_zero(self):
        assert _extract_findings_count({"output": "string"}) == 0


class TestExtractFixesCount:
    def test_fixes_applied(self):
        assert _extract_fixes_count({"output": {"fixes_applied": 3}}) == 3

    def test_fix_count_key(self):
        assert _extract_fixes_count({"output": {"fix_count": 2}}) == 2

    def test_missing_key_returns_zero(self):
        assert _extract_fixes_count({"output": {}}) == 0

    def test_non_dict_returns_zero(self):
        assert _extract_fixes_count(42) == 0


# ---------------------------------------------------------------------------
# A.1.10–A.1.12 — Convergence condition checks
# ---------------------------------------------------------------------------


class TestCheckConvergence:
    def test_zero_findings_with_zero(self):
        assert _check_convergence("zero_findings", 0, None, None) is True

    def test_zero_findings_with_nonzero(self):
        assert _check_convergence("zero_findings", 1, None, None) is False

    def test_zero_critical_findings_with_zero(self):
        assert _check_convergence("zero_critical_findings", 0, None, None) is True

    def test_zero_critical_findings_with_nonzero(self):
        assert _check_convergence("zero_critical_findings", 3, None, None) is False

    def test_all_tests_pass_with_zero(self):
        assert _check_convergence("all_tests_pass", 0, None, None) is True

    def test_quality_threshold_above(self):
        assert _check_convergence("quality_threshold", 0, 0.85, 0.80) is True

    def test_quality_threshold_below(self):
        assert _check_convergence("quality_threshold", 0, 0.75, 0.80) is False

    def test_quality_threshold_equal(self):
        assert _check_convergence("quality_threshold", 0, 0.80, 0.80) is True

    def test_quality_threshold_metric_none_falls_back_to_findings(self):
        # When metric is None, quality_threshold condition doesn't match,
        # so falls through to default (findings_count == 0)
        assert _check_convergence("quality_threshold", 0, None, 0.80) is True
        assert _check_convergence("quality_threshold", 1, None, 0.80) is False

    def test_quality_threshold_threshold_none_falls_back_to_findings(self):
        assert _check_convergence("quality_threshold", 0, 0.85, None) is True
        assert _check_convergence("quality_threshold", 1, 0.85, None) is False

    def test_unknown_condition_falls_back_to_zero_findings(self):
        assert _check_convergence("unknown_condition", 0, None, None) is True
        assert _check_convergence("unknown_condition", 1, None, None) is False


# ---------------------------------------------------------------------------
# A.1.x — _extract_metric
# ---------------------------------------------------------------------------


class TestExtractMetric:
    def test_quality_threshold_extracts_composite_score(self):
        cfg = ConvergenceConfig(convergence_condition="quality_threshold")
        result = {"output": {"composite_score": 0.92}}
        assert _extract_metric(result, cfg) == 0.92

    def test_quality_threshold_extracts_pqi_score(self):
        cfg = ConvergenceConfig(convergence_condition="quality_threshold")
        result = {"output": {"pqi_score": 0.88}}
        assert _extract_metric(result, cfg) == 0.88

    def test_non_quality_condition_returns_none(self):
        cfg = ConvergenceConfig(convergence_condition="zero_findings")
        result = {"output": {"composite_score": 0.92}}
        assert _extract_metric(result, cfg) is None


# ---------------------------------------------------------------------------
# A.1.x — _to_task_result
# ---------------------------------------------------------------------------


class TestToTaskResult:
    def test_dict_result(self):
        raw = {
            "output": {"findings_count": 0},
            "success": True,
            "cost_usd": 0.05,
            "input_tokens": 200,
            "output_tokens": 80,
        }
        result = _to_task_result("task-1", "qa.agent", raw)
        assert result.task_id == "task-1"
        assert result.agent_name == "qa.agent"
        assert result.status == TaskStatus.SUCCESS
        assert result.cost_usd == 0.05
        assert result.token_usage.input == 200
        assert result.token_usage.output == 80

    def test_non_dict_result(self):
        result = _to_task_result("task-1", "qa.agent", "unexpected string")
        assert result.status == TaskStatus.FAILED

    def test_failed_result(self):
        raw = {"output": {}, "success": False}
        result = _to_task_result("task-1", "qa.agent", raw)
        assert result.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# A.1.2 — Happy path: converges in 1 cycle
# ---------------------------------------------------------------------------


class TestConvergenceLoopHappyPath:
    @pytest.mark.asyncio
    async def test_converges_in_one_cycle(self):
        executor = _make_executor(
            _agent_result(findings_count=0),  # eval: zero findings → converged
        )
        config = ConvergenceConfig(max_iterations=5)

        result = await execute_convergence_loop(
            task_id="conv-1",
            config=config,
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.SUCCESS
        assert result.output_reference["outcome"] == "converged"
        assert result.output_reference["total_cycles"] == 1
        # Only eval called (no remediation needed)
        assert executor.call_count == 1


# ---------------------------------------------------------------------------
# A.1.3 — Multi-cycle convergence
# ---------------------------------------------------------------------------


class TestConvergenceLoopMultiCycle:
    @pytest.mark.asyncio
    async def test_three_cycle_convergence(self):
        executor = _make_executor(
            _agent_result(findings_count=3),   # eval cycle 1: 3 findings
            _agent_result(fixes_applied=3),    # fix cycle 1
            _agent_result(findings_count=1),   # eval cycle 2: 1 finding
            _agent_result(fixes_applied=1),    # fix cycle 2
            _agent_result(findings_count=0),   # eval cycle 3: clean → converged
        )
        config = ConvergenceConfig(max_iterations=5)

        result = await execute_convergence_loop(
            task_id="conv-2",
            config=config,
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.SUCCESS
        assert result.output_reference["outcome"] == "converged"
        assert result.output_reference["total_cycles"] == 3
        assert executor.call_count == 5

        # Verify cycle detail structure
        cycles = result.output_reference["cycles"]
        assert cycles[0]["findings"] == 3
        assert cycles[1]["findings"] == 1
        assert cycles[2]["findings"] == 0
        assert cycles[2]["converged"] is True


# ---------------------------------------------------------------------------
# A.1.4 — Max iterations exhausted
# ---------------------------------------------------------------------------


class TestConvergenceLoopMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_exhausted(self):
        # Every eval returns findings — never converges
        executor = _make_executor(
            _agent_result(findings_count=5),
            _agent_result(fixes_applied=2),
            _agent_result(findings_count=3),
            _agent_result(fixes_applied=1),
        )
        config = ConvergenceConfig(max_iterations=2)

        result = await execute_convergence_loop(
            task_id="conv-3",
            config=config,
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.FAILED
        assert result.output_reference["outcome"] == "max_iterations"
        assert result.output_reference["total_cycles"] == 2


# ---------------------------------------------------------------------------
# A.1.5 — Gate abort mid-cycle
# ---------------------------------------------------------------------------


class TestConvergenceLoopGateAbort:
    @pytest.mark.asyncio
    async def test_gate_abort_stops_loop(self):
        executor = _make_executor(
            _agent_result(findings_count=5),  # eval cycle 1: findings
            # Remediation would be next, but gate aborts
        )
        gate = _abort_gate()
        config = ConvergenceConfig(max_iterations=5)

        result = await execute_convergence_loop(
            task_id="conv-4",
            config=config,
            execute_agent_fn=executor,
            gate=gate,
        )

        # Loop exits after gate abort — no remediation called
        assert executor.call_count == 1
        assert result.output_reference["total_cycles"] == 1
        # Gate was called once (after eval, before remediation)
        gate.review.assert_called_once()


# ---------------------------------------------------------------------------
# A.1.6 — Cost/token accumulation
# ---------------------------------------------------------------------------


class TestConvergenceLoopCostAccumulation:
    @pytest.mark.asyncio
    async def test_costs_accumulate_across_cycles(self):
        executor = _make_executor(
            _agent_result(findings_count=2, cost_usd=0.10, input_tokens=100, output_tokens=50),
            _agent_result(fixes_applied=2, cost_usd=0.20, input_tokens=200, output_tokens=80),
            _agent_result(findings_count=0, cost_usd=0.05, input_tokens=100, output_tokens=30),
        )
        config = ConvergenceConfig(max_iterations=5)

        result = await execute_convergence_loop(
            task_id="conv-5",
            config=config,
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.SUCCESS
        # Cost: eval1(0.10) + fix1(0.20) accumulated in cycle loop
        # eval2(0.05) converges so no fix — but eval2 cost is in _to_task_result
        # only cycle 1 tokens accumulated (converged cycle eval not in loop accumulation)
        assert result.cost_usd == pytest.approx(0.30, abs=0.001)
        assert result.token_usage.input == 300  # 100 + 200 (cycle 1 only)
        assert result.token_usage.output == 130  # 50 + 80 (cycle 1 only)


# ---------------------------------------------------------------------------
# A.1.7 — Final verification failure
# ---------------------------------------------------------------------------


class TestConvergenceLoopFinalVerification:
    @pytest.mark.asyncio
    async def test_final_verification_fails(self):
        executor = _make_executor(
            _agent_result(findings_count=0),   # eval: converged
            # Final verification: agent reports failure
            _agent_result(findings_count=2, cost_usd=0.03, success=False),
        )
        config = ConvergenceConfig(
            max_iterations=5,
            final_verification=True,
        )

        result = await execute_convergence_loop(
            task_id="conv-6",
            config=config,
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.FAILED
        assert result.output_reference["outcome"] == "verification_failed"
        assert result.output_reference["final_verification_passed"] is False

    @pytest.mark.asyncio
    async def test_final_verification_passes(self):
        executor = _make_executor(
            _agent_result(findings_count=0),  # eval: converged
            _agent_result(findings_count=0),  # final verification: clean
        )
        config = ConvergenceConfig(
            max_iterations=5,
            final_verification=True,
        )

        result = await execute_convergence_loop(
            task_id="conv-7",
            config=config,
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.SUCCESS
        assert result.output_reference["outcome"] == "converged"
        assert result.output_reference["final_verification_passed"] is True

    @pytest.mark.asyncio
    async def test_final_verification_skipped_when_not_converged(self):
        executor = _make_executor(
            _agent_result(findings_count=5),
            _agent_result(fixes_applied=2),
        )
        config = ConvergenceConfig(
            max_iterations=1,
            final_verification=True,  # enabled but won't fire
        )

        result = await execute_convergence_loop(
            task_id="conv-8",
            config=config,
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.FAILED
        assert result.output_reference["outcome"] == "max_iterations"
        assert result.output_reference["final_verification_passed"] is None
        # Only eval + fix called, no final verification
        assert executor.call_count == 2
