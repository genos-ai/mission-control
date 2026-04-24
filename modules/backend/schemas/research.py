"""
Research schemas (Plan 40 §6).

Pydantic models for the deep research system: query decomposition,
search findings, coverage analysis, synthesis output, citation
verification, and search infrastructure types.
"""

from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# Sub-question decomposition (strategist output)
# =============================================================================


class ResearchSubQuestion(BaseModel):
    """A single sub-question produced by the strategist."""

    id: str
    text: str
    priority: int = Field(ge=1, le=5, description="1=highest, 5=lowest")
    source_hints: list[str] = Field(default_factory=lambda: ["web"])


class ResearchDecomposition(BaseModel):
    """Output from strategist 'decompose' phase."""

    original_query: str
    sub_questions: list[ResearchSubQuestion]
    source_strategy: dict[str, Any] = Field(default_factory=dict)
    estimated_complexity: str = "comprehensive"


# =============================================================================
# Coverage analysis (analyst output — structured, NOT a score)
# =============================================================================


class CoveredQuestion(BaseModel):
    """A sub-question the analyst considers covered."""

    sub_question_id: str
    source_ids: list[str]
    confidence_note: str = ""


class CoverageAnalysisData(BaseModel):
    """Output from analyst agent. Score computed by code, not LLM.

    The analyst only classifies: which questions are covered (with >= 2
    sources), which are not. The strategist takes the uncovered IDs and
    generates refined queries for the next iteration.
    """

    covered_questions: list[CoveredQuestion]
    uncovered_question_ids: list[str]


# =============================================================================
# Search findings (searcher output)
# =============================================================================


class ResearchFinding(BaseModel):
    """A single finding from a searcher agent."""

    sub_question_id: str
    claim: str
    evidence: str
    source_url: str
    source_title: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    extraction_method: str = ""


class SearchFindings(BaseModel):
    """Output from one searcher agent invocation (one sub-question)."""

    sub_question_id: str
    findings: list[ResearchFinding]
    sources_searched: int = 0
    urls_extracted: list[str] = Field(default_factory=list)


# =============================================================================
# Synthesis output (synthesizer agent)
# =============================================================================


class ResearchReportOutput(BaseModel):
    """Output from synthesizer agent."""

    title: str
    executive_summary: str
    report_markdown: str = ""
    sections: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    methodology: str = ""
    limitations: str = ""
    context_updates: list[dict] = Field(default_factory=list)


# =============================================================================
# Citation verification (verifier agent)
# =============================================================================


class CitationVerdict(BaseModel):
    """Verdict for a single citation."""

    citation_id: int
    claim: str
    source_url: str
    verdict: str = Field(description="supported | partially_supported | unsupported")
    explanation: str = ""


class CitationVerificationResult(BaseModel):
    """Output from verifier agent.

    Named CitationVerificationResult (not VerificationResult) to avoid
    collision with the existing 3-tier verification pipeline in
    step_executor.py.
    """

    citation_verdicts: list[CitationVerdict]
    verification_score: float = Field(ge=0.0, le=1.0)
    total_citations: int = 0
    supported_count: int = 0
    unsupported_count: int = 0


# =============================================================================
# Search infrastructure types
# =============================================================================


class SearchResult(BaseModel):
    """A single result from a web search provider."""

    url: str
    title: str
    snippet: str = ""
    content: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    provider: str = "tavily"


class ExtractedContent(BaseModel):
    """Content extracted from a URL."""

    url: str
    title: str | None = None
    text: str = ""
    word_count: int = 0
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    extraction_method: str = "trafilatura"
