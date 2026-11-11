"""Tests for the research loop executor (Plan 40 §2 / Plan 84 Phase 2.1).

Covers the deterministic helpers (compute_coverage_ratio, should_stop,
compress_findings) and execute_research_loop() end-to-end with a stubbed
execute_agent_fn (no real LLM calls, per P11).
"""

import pytest

from modules.backend.agents.mission_control.dispatch.research_loop import (
    ResearchConfig,
    SearchRound,
    compress_findings,
    compute_coverage_ratio,
    execute_research_loop,
    should_stop,
)
from modules.backend.agents.mission_control.outcome import TaskStatus
from modules.backend.core.protocols import NoOpEventBus
from modules.backend.schemas.research import CoverageAnalysisData, CoveredQuestion, ResearchFinding
from modules.backend.schemas.task_failure import FailureClass
from modules.backend.schemas.task_plan import TaskDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _research_task(task_id: str) -> TaskDefinition:
    return TaskDefinition(task_id=task_id, agent="research", description="research task")


def _finding(
    url: str,
    *,
    sub_question_id: str = "q1",
    relevance_score: float = 0.5,
) -> ResearchFinding:
    return ResearchFinding(
        sub_question_id=sub_question_id,
        claim=f"claim about {url}",
        evidence=f"evidence from {url}",
        source_url=url,
        source_title=url,
        relevance_score=relevance_score,
    )


def _make_executor(agent_name_to_result: dict) -> callable:
    """Build a stub execute_agent_fn keyed by agent_name.

    research_loop.py always calls execute_agent_fn with keyword args
    (agent_name=, instructions=, inputs=, usage_limits=) per the
    ExecuteAgentFn Protocol. Records the call order for assertions.
    """
    calls: list[str] = []

    async def _fn(*, agent_name, instructions, inputs, usage_limits):
        calls.append(agent_name)
        return agent_name_to_result[agent_name]

    _fn.calls = calls
    return _fn


def _happy_path_results(config: ResearchConfig) -> dict:
    """Canned per-agent results that converge in exactly one search round."""
    return {
        config.strategist_agent: {
            "output": {
                "original_query": "what is X",
                "sub_questions": [
                    {"id": "q1", "text": "What is X?", "priority": 1, "source_hints": ["web"]}
                ],
            },
            "_meta": {"cost_usd": 0.01, "input_tokens": 10, "output_tokens": 5},
        },
        config.searcher_agent: {
            "output": {
                "sub_question_id": "q1",
                "findings": [
                    {
                        "sub_question_id": "q1",
                        "claim": "X is a thing",
                        "evidence": "source says so",
                        "source_url": "https://example.com/a",
                        "source_title": "Example A",
                        "relevance_score": 0.9,
                    }
                ],
                "sources_searched": 1,
                "urls_extracted": ["https://example.com/a"],
            },
            "_meta": {"cost_usd": 0.02, "input_tokens": 20, "output_tokens": 10},
        },
        config.analyst_agent: {
            "output": {
                "covered_questions": [
                    {
                        "sub_question_id": "q1",
                        "source_ids": ["https://example.com/a", "https://example.com/b"],
                        "confidence_note": "well covered",
                    }
                ],
                "uncovered_question_ids": [],
            },
            "_meta": {"cost_usd": 0.01, "input_tokens": 15, "output_tokens": 8},
        },
        config.synthesizer_agent: {
            "output": {
                "title": "X: a report",
                "executive_summary": "X is a thing.",
                "sources": [{"url": "https://example.com/a", "title": "Example A"}],
                "context_updates": [],
            },
            "_meta": {"cost_usd": 0.03, "input_tokens": 30, "output_tokens": 20},
        },
        config.verifier_agent: {
            "output": {
                "citation_verdicts": [],
                "verification_score": 1.0,
                "total_citations": 1,
                "supported_count": 1,
                "unsupported_count": 0,
            },
            "_meta": {"cost_usd": 0.01, "input_tokens": 5, "output_tokens": 3},
        },
    }


# ---------------------------------------------------------------------------
# compute_coverage_ratio
# ---------------------------------------------------------------------------


class TestComputeCoverageRatio:
    def test_empty_analysis(self):
        analysis = CoverageAnalysisData(covered_questions=[], uncovered_question_ids=["q1", "q2"])
        assert compute_coverage_ratio(analysis, total_questions=2) == 0.0

    def test_zero_total_questions(self):
        analysis = CoverageAnalysisData(covered_questions=[], uncovered_question_ids=[])
        assert compute_coverage_ratio(analysis, total_questions=0) == 0.0

    def test_partial_coverage(self):
        analysis = CoverageAnalysisData(
            covered_questions=[
                CoveredQuestion(sub_question_id="q1", source_ids=["a", "b"]),
                # Only 1 source — doesn't count as well-covered
                CoveredQuestion(sub_question_id="q2", source_ids=["a"]),
            ],
            uncovered_question_ids=["q3"],
        )
        assert compute_coverage_ratio(analysis, total_questions=3) == pytest.approx(1 / 3)

    def test_full_coverage(self):
        analysis = CoverageAnalysisData(
            covered_questions=[
                CoveredQuestion(sub_question_id="q1", source_ids=["a", "b"]),
                CoveredQuestion(sub_question_id="q2", source_ids=["c", "d", "e"]),
            ],
            uncovered_question_ids=[],
        )
        assert compute_coverage_ratio(analysis, total_questions=2) == 1.0


# ---------------------------------------------------------------------------
# should_stop
# ---------------------------------------------------------------------------


class TestShouldStop:
    def test_no_rounds_never_stops(self):
        config = ResearchConfig()
        assert should_stop([], config) == (False, "")

    def test_sufficient_coverage_stops(self):
        config = ResearchConfig(min_coverage_ratio=0.8, max_iterations=5, budget_usd=100.0)
        rounds = [SearchRound(round_number=1, coverage_ratio=0.9, cost_usd=1.0)]
        assert should_stop(rounds, config) == (True, "sufficient")

    def test_budget_exhausted_stops(self):
        config = ResearchConfig(min_coverage_ratio=0.99, max_iterations=10, budget_usd=1.0)
        rounds = [SearchRound(round_number=1, coverage_ratio=0.1, cost_usd=1.5)]
        assert should_stop(rounds, config) == (True, "budget_exhausted")

    def test_max_iterations_stops(self):
        config = ResearchConfig(min_coverage_ratio=0.99, max_iterations=2, budget_usd=100.0)
        rounds = [
            SearchRound(round_number=1, coverage_ratio=0.1, cost_usd=0.1),
            SearchRound(round_number=2, coverage_ratio=0.2, cost_usd=0.1),
        ]
        assert should_stop(rounds, config) == (True, "max_iterations")

    def test_diminishing_returns_stops(self):
        config = ResearchConfig(min_coverage_ratio=0.99, max_iterations=10, budget_usd=100.0)
        rounds = [
            SearchRound(round_number=1, coverage_ratio=0.50, cost_usd=0.1),
            SearchRound(round_number=2, coverage_ratio=0.52, cost_usd=0.1),
        ]
        assert should_stop(rounds, config) == (True, "diminishing_returns")

    def test_meaningful_progress_continues(self):
        config = ResearchConfig(min_coverage_ratio=0.99, max_iterations=10, budget_usd=100.0)
        rounds = [
            SearchRound(round_number=1, coverage_ratio=0.30, cost_usd=0.1),
            SearchRound(round_number=2, coverage_ratio=0.50, cost_usd=0.1),
        ]
        assert should_stop(rounds, config) == (False, "")


# ---------------------------------------------------------------------------
# compress_findings
# ---------------------------------------------------------------------------


class TestCompressFindings:
    def test_under_max_count_returns_all_sorted_by_relevance(self):
        findings = [
            _finding("https://a", relevance_score=0.3),
            _finding("https://b", relevance_score=0.9),
            _finding("https://c", relevance_score=0.6),
        ]
        result = compress_findings(findings, max_count=10)
        assert [f.source_url for f in result] == ["https://b", "https://c", "https://a"]

    def test_over_max_count_takes_top_k(self):
        findings = [_finding(f"https://{i}", relevance_score=i / 10) for i in range(10)]
        result = compress_findings(findings, max_count=3)
        assert len(result) == 3
        assert [f.source_url for f in result] == ["https://9", "https://8", "https://7"]

    def test_dedup_by_source_url_keeps_highest_relevance(self):
        findings = [
            _finding("https://dup", relevance_score=0.4),
            _finding("https://dup", relevance_score=0.8),
        ]
        result = compress_findings(findings, max_count=10)
        assert len(result) == 1
        assert result[0].relevance_score == 0.8


# ---------------------------------------------------------------------------
# execute_research_loop — end to end
# ---------------------------------------------------------------------------


class TestExecuteResearchLoopHappyPath:
    @pytest.mark.asyncio
    async def test_converges_in_one_round_and_produces_task_result(self):
        config = ResearchConfig(max_iterations=3, min_coverage_ratio=0.8, budget_usd=10.0)
        executor = _make_executor(_happy_path_results(config))

        result = await execute_research_loop(
            task=_research_task("research-1"),
            query="what is X",
            config=config,
            event_bus=NoOpEventBus(),
            execute_agent_fn=executor,
        )

        assert result.status == TaskStatus.SUCCESS
        assert result.output_reference["report_title"] == "X: a report"
        assert result.output_reference["total_iterations"] == 1
        assert result.output_reference["total_findings"] == 1
        assert result.output_reference["verification_score"] == 1.0
        assert result.cost_usd > 0

        # Phases execute in order: decompose -> search -> analyze -> synthesize -> verify
        assert executor.calls == [
            config.strategist_agent,
            config.searcher_agent,
            config.analyst_agent,
            config.synthesizer_agent,
            config.verifier_agent,
        ]


class TestExecuteResearchLoopFailure:
    @pytest.mark.asyncio
    async def test_decompose_failure_surfaces_error_not_silent_empty_result(self):
        config = ResearchConfig(max_iterations=3)

        async def _fn(*, agent_name, instructions, inputs, usage_limits):
            # Strategist returns output that fails to validate as ResearchDecomposition
            return {"output": {"not": "a valid decomposition"}, "_meta": {"cost_usd": 0.0}}

        result = await execute_research_loop(
            task=_research_task("research-2"),
            query="what is X",
            config=config,
            event_bus=NoOpEventBus(),
            execute_agent_fn=_fn,
        )

        assert result.status == TaskStatus.FAILED
        assert result.failure.failure_class is FailureClass.AGENT_REPORTED_FAILURE
        assert "decompose" in result.failure.summary.lower()

    @pytest.mark.asyncio
    async def test_exception_in_agent_call_surfaces_as_failed_result(self):
        config = ResearchConfig(max_iterations=3)

        async def _fn(*, agent_name, instructions, inputs, usage_limits):
            raise RuntimeError("provider exploded")

        result = await execute_research_loop(
            task=_research_task("research-3"),
            query="what is X",
            config=config,
            event_bus=NoOpEventBus(),
            execute_agent_fn=_fn,
        )

        assert result.status == TaskStatus.FAILED
        assert "provider exploded" in result.failure.summary
