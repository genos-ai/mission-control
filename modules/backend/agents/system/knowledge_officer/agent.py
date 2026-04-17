"""
Knowledge Officer Agent — curates the knowledge platform.

Thin agent file (P7). All business logic lives in MissionLearningService.
Tools are registered wrappers that delegate to the service layer.

Runs daily via Temporal schedule. Budget: $0.10/run (Haiku).
"""

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

_AGENT_NAME = "system.knowledge.officer.agent"


class KnowledgeOfficerReport(BaseModel):
    """Structured output from the Knowledge Officer."""

    contradictions_flagged: int = Field(
        default=0, description="Number of contradiction pairs flagged",
    )
    promoted: int = Field(
        default=0, description="Number of learnings promoted to platform",
    )
    retracted: int = Field(
        default=0, description="Number of learnings retracted",
    )
    notes: list[str] = Field(
        default_factory=list, description="Free-text notes from the officer",
    )


@lru_cache(maxsize=1)
def _get_agent() -> Agent[None, KnowledgeOfficerReport]:
    """Cached officer agent instance."""
    agent_config = get_registry().get(_AGENT_NAME)
    model = _build_model(agent_config.model)
    instructions = assemble_instructions("system", "knowledge_officer")

    agent: Agent[None, KnowledgeOfficerReport] = Agent(
        model,
        system_prompt=instructions,
        output_type=KnowledgeOfficerReport,
    )

    # ── Tools (thin wrappers over MissionLearningService — P7) ──

    @agent.tool_plain
    async def flag_contradictions() -> str:
        """Find and flag contradictory learning pairs.

        Phase 1: deterministic candidate detection.
        Phase 2: LLM confirmation (only if candidates found).
        """
        import json

        from modules.backend.services.mission_learning import MissionLearningService

        async with MissionLearningService.factory() as svc:
            candidates = await svc.find_contradiction_candidates()

        if not candidates:
            return "No contradictions found."

        # Flag each pair
        flagged = []
        for a, b in candidates:
            flagged.append({
                "learning_a": {"id": a.id, "title": a.title, "recommendation": a.recommendation[:200]},
                "learning_b": {"id": b.id, "title": b.title, "recommendation": b.recommendation[:200]},
                "shared_tags": list(set(a.domain_tags or []) & set(b.domain_tags or [])),
            })

        return json.dumps({
            "contradictions_found": len(flagged),
            "pairs": flagged,
        }, indent=2)

    @agent.tool_plain
    async def promote_to_platform(learning_id: str) -> str:
        """Promote a high-confidence learning to platform scope.

        Enforces: confidence >= 0.7, occurrence_count >= 3.
        Idempotent — re-promotion is a no-op.
        """
        from modules.backend.services.mission_learning import MissionLearningService

        async with MissionLearningService.factory() as svc:
            learning = await svc._learning_repo.get_by_id(learning_id)

            config_threshold = 0.7
            if learning.confidence < config_threshold:
                return f"Confidence {learning.confidence:.2f} below threshold {config_threshold}. Not promoted."
            if learning.occurrence_count < 3:
                return f"Occurrence count {learning.occurrence_count} < 3. Not promoted."
            if learning.platform_promoted:
                return "Already promoted. No-op."

            await svc.promote(learning_id, "system.knowledge.officer.agent")
        return f"Promoted learning {learning_id} to platform scope."

    @agent.tool_plain
    async def retract_learning(learning_id: str, reason: str) -> str:
        """Retract a learning entry. Idempotent."""
        from modules.backend.services.mission_learning import MissionLearningService

        async with MissionLearningService.factory() as svc:
            await svc.retract(learning_id)
        logger.info("Learning retracted by officer", extra={"learning_id": learning_id, "reason": reason})
        return f"Retracted learning {learning_id}. Reason: {reason}"

    return agent


def get_agent(model: Model | None = None) -> Agent[None, KnowledgeOfficerReport]:
    """Get or create the Knowledge Officer agent."""
    if model is not None:
        instructions = assemble_instructions("system", "knowledge_officer")
        agent: Agent[None, KnowledgeOfficerReport] = Agent(
            model,
            system_prompt=instructions,
            output_type=KnowledgeOfficerReport,
        )
        return agent
    return _get_agent()


async def run_officer(*, model: Model | None = None) -> dict:
    """Run the Knowledge Officer curation cycle.

    Called by Temporal daily schedule. Returns the report dict.
    """
    agent = get_agent(model)

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
