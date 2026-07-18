"""
Knowledge Officer Agent — curates the knowledge platform.

Thin agent file (P7). All business logic lives in MissionLearningService.
Tools are registered wrappers that delegate to the service layer.

Runs daily via Temporal schedule. Budget: $0.10/run (Haiku).
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import _build_model, assemble_instructions
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

_AGENT_NAME = "system.knowledge.officer.agent"


class KnowledgeOfficerReport(BaseModel):
    """Structured output from the Knowledge Officer."""

    contradictions_flagged: int = Field(
        default=0,
        description="Number of contradiction pairs flagged",
    )
    promoted: int = Field(
        default=0,
        description="Number of learnings promoted to platform",
    )
    retracted: int = Field(
        default=0,
        description="Number of learnings retracted",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Free-text notes from the officer",
    )


def create_agent(
    model: Model | None = None, tool_names: list[str] | None = None
) -> Agent[None, KnowledgeOfficerReport]:
    """Create a Knowledge Officer agent with all tools registered.

    Always creates a fresh agent so tools are bound to the returned
    instance regardless of whether a model override is supplied. This
    matches the standard factory pattern used by other agents (research
    searcher, etc.) so that agent_executor.py always gets a fully-
    equipped agent.
    """
    if model is None:
        agent_config = get_registry().get(_AGENT_NAME)
        model = _build_model(agent_config.model)

    instructions = assemble_instructions("system.knowledge.officer")
    agent: Agent[None, KnowledgeOfficerReport] = Agent(
        model,
        instructions=instructions,
        output_type=KnowledgeOfficerReport,
    )

    # ── Tools (thin wrappers over MissionLearningService — P7) ──

    @agent.tool_plain
    async def query_knowledge(
        mission_id: str,
        query: str,
        domain_tags: list[str] | None = None,
        kinds: list[str] | None = None,
        platform_only: bool = False,
    ) -> str:
        """Search the knowledge platform for existing learnings, decisions, and milestones.

        Call this BEFORE create_learning to check whether a finding already
        exists. If it does, note its UUID and update occurrence_count via
        the service instead of creating a duplicate.

        Args:
            mission_id: Scope the search to this mission (+ platform entries).
            query: Free-text search query matching titles, body, or recommendations.
            domain_tags: Narrow by domain labels e.g. ["ai", "security"].
            kinds: Filter by entry kind — "finding", "insight", "decision", "risk".
            platform_only: Only return platform-promoted cross-mission entries.
        """
        from modules.backend.tools.query_knowledge import query_knowledge as _query

        return await _query(
            mission_id,
            query=query,
            kinds=kinds,
            domain_tags=domain_tags,
            platform_only=platform_only,
        )

    @agent.tool_plain
    async def create_learning(
        mission_id: str,
        title: str,
        body: str,
        recommendation: str,
        kind: str = "finding",
        domain_tags: list[str] | None = None,
        confidence: float = 0.8,
    ) -> str:
        """Record a new learning or finding into the knowledge platform.

        Use this to add findings extracted from research reports or other
        mission outputs. Returns the new learning's UUID, which can then
        be passed to promote_to_platform if it meets the threshold.

        Args:
            mission_id: The mission this learning belongs to.
            title: Short descriptive title (max 120 chars).
            body: Full detail of the finding.
            recommendation: Actionable recommendation derived from the finding.
            kind: Learning type — "finding", "insight", "decision", or "risk".
            domain_tags: Domain labels e.g. ["ai", "security", "research"].
            confidence: Confidence score 0.0–1.0 (default 0.8 for curated findings).
        """
        import json as _json

        from modules.backend.services.mission_learning import MissionLearningService

        async with MissionLearningService.factory() as svc:
            learning = await svc.create_learning(
                mission_id=mission_id,
                kind=kind,
                title=title,
                body=body,
                recommendation=recommendation,
                domain_tags=domain_tags or [],
                agent_names=[_AGENT_NAME],
                confidence=confidence,
                occurrence_count=1,
            )
        logger.info("Learning created", extra={"learning_id": learning.id, "title": title})
        return _json.dumps({"learning_id": learning.id, "title": title})

    @agent.tool_plain
    async def flag_contradictions() -> str:
        """Find and flag contradictory learning pairs in the platform.

        Phase 1: deterministic candidate detection.
        Phase 2: LLM confirmation (only if candidates found).
        """
        import json as _json

        from modules.backend.services.mission_learning import MissionLearningService

        async with MissionLearningService.factory() as svc:
            candidates = await svc.find_contradiction_candidates()

        if not candidates:
            return "No contradictions found."

        flagged = [
            {
                "learning_a": {
                    "id": a.id,
                    "title": a.title,
                    "recommendation": a.recommendation[:200],
                },
                "learning_b": {
                    "id": b.id,
                    "title": b.title,
                    "recommendation": b.recommendation[:200],
                },
                "shared_tags": list(set(a.domain_tags or []) & set(b.domain_tags or [])),
            }
            for a, b in candidates
        ]
        return _json.dumps({"contradictions_found": len(flagged), "pairs": flagged}, indent=2)

    @agent.tool_plain
    async def promote_to_platform(learning_id: str) -> str:
        """Promote an existing learning to platform scope for cross-mission discovery.

        Requires: confidence >= 0.7 AND occurrence_count >= 3.
        Idempotent — re-promotion is a no-op.

        Args:
            learning_id: UUID returned by create_learning.
        """
        from modules.backend.services.mission_learning import MissionLearningService

        async with MissionLearningService.factory() as svc:
            learning = await svc._learning_repo.get_by_id(learning_id)

            if learning.confidence < 0.7:
                return f"Confidence {learning.confidence:.2f} below 0.7 threshold. Not promoted."
            if learning.occurrence_count < 3:
                return f"Occurrence count {learning.occurrence_count} < 3. Not promoted."
            if learning.platform_promoted:
                return "Already promoted. No-op."

            await svc.promote(learning_id, _AGENT_NAME)
        return f"Promoted learning {learning_id} to platform scope."

    @agent.tool_plain
    async def retract_learning(learning_id: str, reason: str) -> str:
        """Retract a stale or superseded learning entry. Idempotent.

        Args:
            learning_id: UUID of the learning to retract.
            reason: Human-readable reason for retraction.
        """
        from modules.backend.services.mission_learning import MissionLearningService

        async with MissionLearningService.factory() as svc:
            await svc.retract(learning_id)
        logger.info("Learning retracted", extra={"learning_id": learning_id, "reason": reason})
        return f"Retracted learning {learning_id}. Reason: {reason}"

    return agent


async def run_officer(*, model: Model | None = None) -> dict:
    """Run the Knowledge Officer curation cycle.

    Called by Temporal daily schedule. Returns the report dict.
    """
    agent = create_agent(model)

    prompt = (
        "Run your daily curation cycle:\n"
        "1. Call flag_contradictions() to find conflicting learnings\n"
        "2. Review active learnings and call promote_to_platform() for any "
        "that meet the threshold (confidence >= 0.7, occurrences >= 3)\n"
        "3. Call retract_learning() for any that are clearly superseded or stale\n"
        "4. Return your KnowledgeOfficerReport with counts and notes"
    )

    result = await agent.run(prompt)
    output = result.output

    logger.info(
        "Knowledge Officer run complete",
        extra={
            "contradictions": output.contradictions_flagged,
            "promoted": output.promoted,
            "retracted": output.retracted,
        },
    )

    return {
        "contradictions_flagged": output.contradictions_flagged,
        "promoted": output.promoted,
        "retracted": output.retracted,
        "notes": output.notes,
    }
