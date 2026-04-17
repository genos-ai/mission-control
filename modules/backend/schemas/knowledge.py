"""
Knowledge schemas — shared types for the knowledge platform.

Evidence is the canonical schema for linking learnings, decisions,
and future knowledge entries to their source data. Storage is uncapped;
render pagination is enforced by API and UI via ``evidence_render_limit``.
"""

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    """Structured evidence linking a knowledge entry to source data.

    All lists are uncapped at write time. API and UI paginate
    via ``knowledge.learnings.evidence_render_limit`` config.
    """

    model_config = ConfigDict(extra="forbid")

    task_attempt_ids: list[str] = Field(
        default_factory=list,
        description="TaskAttempt UUIDs that support this entry",
    )
    execution_ids: list[str] = Field(
        default_factory=list,
        description="ExecutionRecord UUIDs where this was observed",
    )
    failure_tiers: list[int] = Field(
        default_factory=list,
        description="Verification tiers where failures occurred (1/2/3)",
    )
    artifact_ids: list[str] = Field(
        default_factory=list,
        description="MissionArtifact UUIDs with supporting evidence",
    )


class KnowledgeEntry(BaseModel):
    """Unified knowledge entry returned by KnowledgeService.search().

    Wraps any of the five knowledge surfaces (learnings, intents,
    decisions, milestones, MCD sections) into a common shape for
    display and ranking.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    kind: str  # learning | intent | decision | milestone | mcd_section
    source_table: str
    title: str
    body: str
    domain_tags: list[str] = Field(default_factory=list)
    mission_id: str | None = None
    confidence: float | None = None
    distance: float | None = None  # cosine distance from query (semantic/hybrid)
    created_at: str | None = None
