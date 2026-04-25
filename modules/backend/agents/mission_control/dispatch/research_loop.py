"""Research loop executor (Plan 40 §2).

Implements the Plan→Search→Synthesize loop with parallel execution,
deterministic coverage scoring, and iterative refinement.

Integration: called from dispatch/loop.py when a task has
type=research_loop in its inputs.static. Follows the same structural
pattern as convergence.py.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic_ai import UsageLimits

from modules.backend.agents.mission_control.gate import (
    GateAction,
    GateContext,
    GateReviewer,
    NoOpGate,
)
from modules.backend.agents.mission_control.helpers import _emit
from modules.backend.agents.mission_control.models import (
    EventBusProtocol,
    ExecuteAgentFn,
    NoOpEventBus,
)
from modules.backend.agents.mission_control.outcome import (
    TaskResult,
    TaskStatus,
    TaskTokenUsage,
)
from modules.backend.core.logging import get_logger
from modules.backend.schemas.research import (
    CoverageAnalysisData,
    ResearchDecomposition,
    ResearchFinding,
    SearchFindings,
)

logger = get_logger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class ResearchConfig:
    """Configuration for a research loop."""

    depth: str = "comprehensive"
    max_iterations: int = 5
    min_coverage_ratio: float = 0.8
    max_sources_per_question: int = 10
    max_findings_for_synthesis: int = 50
    source_types: list[str] = field(default_factory=lambda: ["web"])
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    budget_usd: float = 25.0
    max_concurrent_searches: int = 10
    verification_enabled: bool = True

    # Agent names (configurable for testing)
    strategist_agent: str = "research.strategist.agent"
    searcher_agent: str = "research.searcher.agent"
    analyst_agent: str = "research.analyst.agent"
    synthesizer_agent: str = "research.synthesizer.agent"
    verifier_agent: str = "research.verifier.agent"

    # Depth presets: override defaults when depth is set but individual
    # fields are not explicitly provided in the input dict.
    _DEPTH_PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "quick": {
            "max_iterations": 1,
            "min_coverage_ratio": 0.5,
            "max_sources_per_question": 5,
            "max_findings_for_synthesis": 20,
            "budget_usd": 5.0,
            "verification_enabled": False,
        },
        "moderate": {
            "max_iterations": 3,
            "min_coverage_ratio": 0.7,
            "max_sources_per_question": 8,
            "max_findings_for_synthesis": 35,
            "budget_usd": 15.0,
        },
        # "comprehensive" uses the dataclass defaults — no overrides needed.
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchConfig:
        """Create from task input_data['loop_config'].

        Applies depth presets first, then lets explicit values override.
        """
        depth = data.get("depth", "comprehensive")
        preset = dict(cls._DEPTH_PRESETS.get(depth, {}))
        # Explicit values in data override preset defaults
        preset.update({k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        return cls(**preset)


@dataclass
class SearchRound:
    """Result of a single search iteration."""

    round_number: int
    sub_questions_searched: int = 0
    sources_found: int = 0
    new_findings: int = 0
    coverage_ratio: float = 0.0
    gaps_remaining: int = 0
    cost_usd: float = 0.0


# =============================================================================
# Coverage scoring (deterministic)
# =============================================================================


def compute_coverage_ratio(
    analysis: CoverageAnalysisData, total_questions: int
) -> float:
    """Fraction of sub-questions with >= 2 independent sources."""
    well_covered = sum(
        1 for q in analysis.covered_questions if len(q.source_ids) >= 2
    )
    return well_covered / total_questions if total_questions > 0 else 0.0


def should_stop(
    rounds: list[SearchRound], config: ResearchConfig
) -> tuple[bool, str]:
    """Evaluate deterministic stopping conditions."""
    if not rounds:
        return False, ""
    latest = rounds[-1]
    if latest.coverage_ratio >= config.min_coverage_ratio:
        return True, "sufficient"
    if sum(r.cost_usd for r in rounds) >= config.budget_usd:
        return True, "budget_exhausted"
    if len(rounds) >= config.max_iterations:
        return True, "max_iterations"
    if len(rounds) >= 2:
        improvement = latest.coverage_ratio - rounds[-2].coverage_ratio
        if improvement < 0.05:
            return True, "diminishing_returns"
    return False, ""


# =============================================================================
# Findings compression (pre-synthesis)
# =============================================================================


def compress_findings(
    all_findings: list[ResearchFinding], max_count: int
) -> list[ResearchFinding]:
    """Deduplicate, rank, and take top-K findings for synthesis."""
    # Deduplicate by source_url (keep highest relevance_score)
    by_url: dict[str, ResearchFinding] = {}
    for f in all_findings:
        existing = by_url.get(f.source_url)
        if existing is None or f.relevance_score > existing.relevance_score:
            by_url[f.source_url] = f

    # Sort by relevance descending, take top-K
    ranked = sorted(by_url.values(), key=lambda f: f.relevance_score, reverse=True)
    return ranked[:max_count]


# =============================================================================
# Main executor
# =============================================================================


async def execute_research_loop(
    *,
    task_id: str,
    query: str,
    config: ResearchConfig,
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None = None,
    gate: GateReviewer | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> TaskResult:
    """Execute a deep research loop.

    Phase 1: Decompose — strategist breaks query into sub-questions
    Phase 2: Search Loop (iterative)
    Phase 3: Compress — rank and deduplicate findings
    Phase 4: Synthesize — produce report with citations
    Phase 5: Verify — NLI citation verification
    Phase 6: Build result
    """
    logger.info("TRACE >>> execute_research_loop entered",
                 extra={"task_id": task_id, "query": query[:80],
                        "depth": config.depth, "budget": config.budget_usd,
                        "event_bus_type": type(event_bus).__name__ if event_bus else "None",
                        "session_id": session_id})
    _gate = gate or NoOpGate()
    _bus = event_bus or NoOpEventBus()
    _sid = session_id or ""
    start_time = time.monotonic()

    total_cost = 0.0
    total_tokens = TaskTokenUsage()
    all_findings: list[ResearchFinding] = []
    rounds: list[SearchRound] = []

    # Import research events lazily to avoid circular imports
    from modules.backend.events.types import (
        MissionNarrativeEvent,
        ResearchCompletedEvent,
        ResearchCoverageEvent,
        ResearchDecomposedEvent,
        ResearchFailedEvent,
        ResearchSearchCompletedEvent,
        ResearchStartedEvent,
        ResearchSubQuestionUpdatedEvent,
        ResearchSynthesizingEvent,
        SystemEvent,
    )

    async def _narrative(phase: str, message: str, iteration: int | None = None) -> None:
        await _emit(_bus, MissionNarrativeEvent,
            session_id=_sid,
            source=f"research:{task_id}",
            mission_id=mission_id or "",
            agent_id="research",
            narrative=message,
            phase="research",
            level="info",
        )

    try:
        # ── Phase 0: Started ────────────────────────────────────────
        await _emit(_bus, ResearchStartedEvent,
            session_id=_sid,
            source=f"research:{task_id}",
            research_id=task_id,
            query=query,
            depth=config.depth,
            max_iterations=config.max_iterations,
        )
        await _narrative("decompose", f"Starting deep research: \"{query}\"")

        # ── Phase 1: Decompose ──────────────────────────────────────
        await _narrative("decompose", "Breaking your question into sub-questions...")

        decompose_result = await execute_agent_fn(
            agent_name=config.strategist_agent,
            instructions=f"Decompose this research query into sub-questions: {query}",
            inputs={"query": query, "mode": "decompose"},
            usage_limits=UsageLimits(request_limit=3),
        )
        total_cost += decompose_result.get("_meta", {}).get("cost_usd", 0.0)
        _accumulate_tokens(total_tokens, decompose_result)

        decomposition = _parse_output(decompose_result, ResearchDecomposition)
        if decomposition is None:
            await _narrative("error", "Failed to decompose research query")
            return _failed_result(task_id, "Strategist failed to decompose query",
                                  total_cost, total_tokens, start_time)

        sub_questions = decomposition.sub_questions
        total_questions = len(sub_questions)

        await _emit(_bus, ResearchDecomposedEvent,
            session_id=_sid,
            source=f"research:{task_id}",
            research_id=task_id,
            sub_question_count=total_questions,
            sub_questions=[
                {"id": sq.id, "text": sq.text, "priority": sq.priority, "status": "pending"}
                for sq in sub_questions
            ],
        )
        for sq in sub_questions:
            await _narrative("decompose", f"Sub-question: {sq.text}")

        # ── Phase 2: Search Loop ────────────────────────────────────
        gap_question_ids = [sq.id for sq in sub_questions]
        previous_coverage: CoverageAnalysisData | None = None

        for iteration in range(1, config.max_iterations + 1):
            # Budget check before starting batch
            if total_cost >= config.budget_usd:
                logger.info("Budget exhausted before search round",
                            extra={"cost": total_cost, "budget": config.budget_usd})
                break

            gap_questions = [sq for sq in sub_questions if sq.id in gap_question_ids]
            if not gap_questions:
                break

            await _narrative("search",
                f"Search round {iteration} — investigating {len(gap_questions)} "
                f"sub-question{'s' if len(gap_questions) != 1 else ''} in parallel...",
                iteration=iteration)

            # Mark sub-questions as searching
            for sq in gap_questions:
                await _emit(_bus, ResearchSubQuestionUpdatedEvent,
                    session_id=_sid,
                    source=f"research:{task_id}",
                    research_id=task_id,
                    sub_question_id=sq.id,
                    text=sq.text,
                    status="searching",
                )

            # Fan out searchers in parallel with concurrency control
            semaphore = asyncio.Semaphore(config.max_concurrent_searches)
            round_findings: list[ResearchFinding] = []
            round_cost = 0.0

            # Build domain filter instructions if configured
            domain_hint = ""
            if config.include_domains:
                domains = ", ".join(config.include_domains)
                domain_hint = (
                    f"\n\nIMPORTANT: Only search these trusted domains: {domains}. "
                    f"Pass include_domains={config.include_domains} to search_web."
                )

            async def _search_one(
                sq_id: str, sq_text: str
            ) -> tuple[list[ResearchFinding], float]:
                async with semaphore:
                    result = await execute_agent_fn(
                        agent_name=config.searcher_agent,
                        instructions=f"Research this sub-question: {sq_text}{domain_hint}",
                        inputs={
                            "sub_question": sq_text,
                            "sub_question_id": sq_id,
                            "include_domains": config.include_domains,
                            "exclude_domains": config.exclude_domains,
                        },
                        usage_limits=UsageLimits(request_limit=10),
                    )
                    cost = result.get("_meta", {}).get("cost_usd", 0.0)
                    _accumulate_tokens(total_tokens, result)
                    return _extract_findings(result, sq_id), cost

            search_tasks = [
                _search_one(sq.id, sq.text) for sq in gap_questions
            ]
            search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

            for sq, result in zip(gap_questions, search_results):
                if isinstance(result, Exception):
                    error_msg = str(result)[:200]
                    logger.warning("Searcher failed for sub-question",
                                   extra={"sq_id": sq.id, "error": error_msg})
                    await _emit(_bus, SystemEvent,
                        session_id=_sid, source=f"research:{mission_id}",
                        level="warning",
                        message=f"Search failed for '{sq.text[:60]}': {error_msg}",
                        mission_id=mission_id,
                    )
                    continue
                findings_list, searcher_cost = result
                round_findings.extend(findings_list)
                round_cost += searcher_cost

            total_cost += round_cost

            all_findings.extend(round_findings)

            await _emit(_bus, ResearchSearchCompletedEvent,
                session_id=_sid,
                source=f"research:{task_id}",
                research_id=task_id,
                iteration=iteration,
                sources_found=len({f.source_url for f in round_findings}),
                new_findings=len(round_findings),
                cost_usd=round_cost,
            )
            await _narrative("search",
                f"Found {len(round_findings)} findings from "
                f"{len({f.source_url for f in round_findings})} sources")

            # ── Analyze coverage ────────────────────────────────────
            analyst_input = {
                "new_findings": [f.model_dump() for f in round_findings],
                "previous_coverage": previous_coverage.model_dump() if previous_coverage else None,
                "sub_questions": [sq.model_dump() for sq in sub_questions],
            }
            analyst_result = await execute_agent_fn(
                agent_name=config.analyst_agent,
                instructions="Evaluate coverage of the research sub-questions.",
                inputs=analyst_input,
                usage_limits=UsageLimits(request_limit=2),
            )
            total_cost += analyst_result.get("_meta", {}).get("cost_usd", 0.0)
            _accumulate_tokens(total_tokens, analyst_result)

            coverage = _parse_output(analyst_result, CoverageAnalysisData)
            if coverage is None:
                logger.warning("Analyst failed — continuing with previous coverage")
                coverage = previous_coverage or CoverageAnalysisData(
                    covered_questions=[], uncovered_question_ids=gap_question_ids
                )

            coverage_ratio = compute_coverage_ratio(coverage, total_questions)
            gap_question_ids = coverage.uncovered_question_ids
            previous_coverage = coverage

            # Update sub-question statuses
            covered_ids = {q.sub_question_id for q in coverage.covered_questions}
            for sq in sub_questions:
                status = "covered" if sq.id in covered_ids else "gap"
                source_count = 0
                for cq in coverage.covered_questions:
                    if cq.sub_question_id == sq.id:
                        source_count = len(cq.source_ids)
                        break
                await _emit(_bus, ResearchSubQuestionUpdatedEvent,
                    session_id=_sid,
                    source=f"research:{task_id}",
                    research_id=task_id,
                    sub_question_id=sq.id,
                    text=sq.text,
                    status=status,
                    source_count=source_count,
                )

            # Record the round
            search_round = SearchRound(
                round_number=iteration,
                sub_questions_searched=len(gap_questions),
                sources_found=len({f.source_url for f in round_findings}),
                new_findings=len(round_findings),
                coverage_ratio=coverage_ratio,
                gaps_remaining=len(gap_question_ids),
                cost_usd=round_cost,
            )
            rounds.append(search_round)

            stop, stop_reason = should_stop(rounds, config)
            await _emit(_bus, ResearchCoverageEvent,
                session_id=_sid,
                source=f"research:{task_id}",
                research_id=task_id,
                iteration=iteration,
                coverage_ratio=coverage_ratio,
                gaps_remaining=len(gap_question_ids),
                stop_reason=stop_reason,
            )
            await _narrative("analyze",
                f"Coverage: {len(covered_ids)}/{total_questions} sub-questions "
                f"answered ({coverage_ratio:.0%}). "
                f"{len(gap_question_ids)} gaps remaining.",
                iteration=iteration)

            if stop:
                await _narrative("analyze",
                    f"Stopping search: {stop_reason}", iteration=iteration)
                break

            # Gate check: should we continue?
            decision = await _gate.review(GateContext(
                gate_type="research_iteration",
                mission_id=mission_id or "",
                layer_index=iteration,
                total_layers=config.max_iterations,
                total_cost_usd=total_cost,
                budget_usd=config.budget_usd,
            ))
            if decision.action == GateAction.ABORT:
                await _narrative("analyze", "Research aborted by gate reviewer")
                break

            # Refine queries for remaining gaps
            if gap_question_ids:
                await _narrative("search",
                    f"Refining queries for {len(gap_question_ids)} remaining gaps...",
                    iteration=iteration)
                refine_result = await execute_agent_fn(
                    agent_name=config.strategist_agent,
                    instructions=(
                        f"Refine queries for uncovered sub-questions. "
                        f"Uncovered IDs: {gap_question_ids}. "
                        f"Original query: {query}"
                    ),
                    inputs={
                        "query": query,
                        "mode": "refine",
                        "uncovered_ids": gap_question_ids,
                        "original_decomposition": decomposition.model_dump(),
                    },
                    usage_limits=UsageLimits(request_limit=2),
                )
                total_cost += refine_result.get("_meta", {}).get("cost_usd", 0.0)
                _accumulate_tokens(total_tokens, refine_result)

                refined = _parse_output(refine_result, ResearchDecomposition)
                if refined and refined.sub_questions:
                    # Replace gap questions with refined versions
                    refined_map = {sq.id: sq for sq in refined.sub_questions}
                    sub_questions = [
                        refined_map.get(sq.id, sq) if sq.id in gap_question_ids else sq
                        for sq in sub_questions
                    ]

        # ── Phase 3: Compress ───────────────────────────────────────
        compressed = compress_findings(all_findings, config.max_findings_for_synthesis)
        await _emit(_bus, ResearchSynthesizingEvent,
            session_id=_sid,
            source=f"research:{task_id}",
            research_id=task_id,
            total_findings=len(all_findings),
            findings_after_compression=len(compressed),
        )
        await _narrative("synthesize",
            f"Compressing {len(all_findings)} findings to top "
            f"{len(compressed)} for synthesis...")

        # ── Phase 4: Synthesize ─────────────────────────────────────
        await _narrative("synthesize", "Writing research report...")

        source_map = {f.source_url: f.source_title for f in compressed}
        synthesis_result = await execute_agent_fn(
            agent_name=config.synthesizer_agent,
            instructions=(
                f"Produce a comprehensive research report answering: {query}\n\n"
                f"Use the provided findings with [N] inline citations."
            ),
            inputs={
                "findings": [f.model_dump() for f in compressed],
                "sources": source_map,
                "query": query,
            },
            # Synthesizer needs high token limit — reports are long structured JSON
            usage_limits=UsageLimits(request_limit=2, total_tokens_limit=200_000),
        )
        total_cost += synthesis_result.get("_meta", {}).get("cost_usd", 0.0)
        _accumulate_tokens(total_tokens, synthesis_result)

        report_output = synthesis_result.get("output", {})
        report_title = report_output.get("title", query[:80])

        # ── Phase 5: Verify ─────────────────────────────────────────
        verification_score: float | None = None
        if config.verification_enabled and compressed:
            await _narrative("verify", "Verifying citations against source material...")

            # Build citation list from report
            citations = _extract_citations_for_verification(report_output, compressed)
            source_texts = {f.source_url: f.evidence for f in compressed}

            verify_result = await execute_agent_fn(
                agent_name=config.verifier_agent,
                instructions="Verify whether cited sources support the claims made.",
                inputs={"citations": citations, "source_texts": source_texts},
                usage_limits=UsageLimits(request_limit=2),
            )
            total_cost += verify_result.get("_meta", {}).get("cost_usd", 0.0)
            _accumulate_tokens(total_tokens, verify_result)

            verify_output = verify_result.get("output", {})
            verification_score = verify_output.get("verification_score")
            if verification_score is not None:
                supported = verify_output.get("supported_count", 0)
                total_cites = verify_output.get("total_citations", 0)
                await _narrative("verify",
                    f"Verified {supported}/{total_cites} citations "
                    f"({verification_score:.0%} supported)")

        # ── Phase 6: Complete ───────────────────────────────────────
        duration = time.monotonic() - start_time
        final_coverage = rounds[-1].coverage_ratio if rounds else 0.0

        await _emit(_bus, ResearchCompletedEvent,
            session_id=_sid,
            source=f"research:{task_id}",
            research_id=task_id,
            report_title=report_title,
            total_sources=len({f.source_url for f in all_findings}),
            total_iterations=len(rounds),
            coverage_ratio=final_coverage,
            verification_score=verification_score,
            cost_usd=total_cost,
            duration_seconds=duration,
        )
        await _narrative("complete",
            f"Research complete. {len({f.source_url for f in all_findings})} sources, "
            f"{len(rounds)} iterations, ${total_cost:.2f}, "
            f"{duration:.0f}s.")

        # Build context_updates from synthesizer output
        context_updates = report_output.get("context_updates", [])

        return TaskResult(
            task_id=task_id,
            agent_name=f"research({config.strategist_agent})",
            status=TaskStatus.SUCCESS,
            output_reference={
                "report_title": report_title,
                "coverage_ratio": final_coverage,
                "verification_score": verification_score,
                "total_sources": len({f.source_url for f in all_findings}),
                "total_iterations": len(rounds),
                "total_findings": len(all_findings),
                "report": report_output,
            },
            cost_usd=total_cost,
            token_usage=total_tokens,
            duration_seconds=duration,
            context_updates=context_updates,
        )

    except Exception as e:
        duration = time.monotonic() - start_time
        logger.error("Research loop failed", extra={"task_id": task_id}, exc_info=True)
        await _emit(_bus, ResearchFailedEvent,
            session_id=_sid,
            source=f"research:{task_id}",
            research_id=task_id,
            error=str(e)[:500],
            iteration=len(rounds),
            cost_usd=total_cost,
        )
        return _failed_result(task_id, str(e), total_cost, total_tokens, start_time)


# =============================================================================
# Helpers
# =============================================================================


def _parse_output(result: dict, model_class: type) -> Any | None:
    """Parse agent output dict into a Pydantic model. Returns None on failure.

    The agent executor wraps output under result["output"]. This reads
    that key and validates it against the given Pydantic model class.
    """
    output = result.get("output")
    if output is None:
        return None
    try:
        if isinstance(output, model_class):
            return output
        if isinstance(output, dict):
            return model_class.model_validate(output)
        if isinstance(output, str):
            return model_class.model_validate_json(output)
        return None
    except Exception:
        logger.debug("Failed to parse output as %s", model_class.__name__, exc_info=True)
        return None


def _extract_findings(result: dict, sq_id: str) -> list[ResearchFinding]:
    """Extract ResearchFinding list from a searcher agent result."""
    sf = _parse_output(result, SearchFindings)
    if sf:
        return sf.findings

    # Fallback: try to extract findings from raw output
    output = result.get("output", {})
    if isinstance(output, dict):
        raw_findings = output.get("findings", [])
        findings = []
        for f in raw_findings:
            if isinstance(f, dict):
                f.setdefault("sub_question_id", sq_id)
                try:
                    findings.append(ResearchFinding.model_validate(f))
                except Exception:
                    continue
        return findings
    return []


def _extract_citations_for_verification(
    report_output: dict, findings: list[ResearchFinding]
) -> list[dict]:
    """Build citation list for verifier from report output + findings.

    Matches ALL claims per source URL — every finding that cites a given
    source becomes a separate citation to verify. The verifier receives
    all citations in a single call (Haiku), so the marginal cost of
    additional citations is minimal (extra input tokens, not extra calls).
    """
    citations = []
    sources = report_output.get("sources", [])
    source_urls = {source.get("url", "") for source in sources}
    citation_id = 0
    for f in findings:
        if f.source_url in source_urls:
            citation_id += 1
            citations.append({
                "citation_id": citation_id,
                "claim": f.claim,
                "source_url": f.source_url,
            })
    return citations


def _accumulate_tokens(total: TaskTokenUsage, result: dict) -> None:
    """Add token usage from an agent result to the running total."""
    meta = result.get("_meta", {})
    total.input += meta.get("input_tokens", 0)
    total.output += meta.get("output_tokens", 0)
    total.thinking += meta.get("thinking_tokens", 0)


def _failed_result(
    task_id: str,
    error: str,
    cost: float,
    tokens: TaskTokenUsage,
    start_time: float,
) -> TaskResult:
    """Build a failed TaskResult."""
    return TaskResult(
        task_id=task_id,
        agent_name="research",
        status=TaskStatus.FAILED,
        output_reference={"error": error[:500]},
        cost_usd=cost,
        token_usage=tokens,
        duration_seconds=time.monotonic() - start_time,
    )
