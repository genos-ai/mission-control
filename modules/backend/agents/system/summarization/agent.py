"""
Summarization Agent — compresses mission outcomes into milestone summaries.

Generates narrative summaries from structured mission outcome data for the
fractal summarization pipeline. Uses Haiku for cost efficiency — input is
structured data, output is compressed narrative.
"""

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

_AGENT_NAME = "system.summarization.agent"


class SummarizationOutput(BaseModel):
    """Structured output from the summarization agent."""

    title: str = Field(..., description="Short title for the milestone")
    summary: str = Field(..., description="Compressed narrative summary")
    key_outcomes: list[str] = Field(
        default_factory=list,
        description="Bullet-point key outcomes",
    )
    domain_tags: list[str] = Field(
        default_factory=list,
        description="Domain tags derived from the missions",
    )


class SessionSpanSummary(BaseModel):
    """Structured output from session span compression (Plan 57 Phase C).

    Factory.ai 4-category anchored rolling summary.
    """

    intent: str = Field(..., description="Current session goals and objectives")
    play_by_play: str = Field(..., description="Sequence of major actions and outcomes")
    artifact_trail: str = Field(..., description="Files created/modified, resources produced")
    breadcrumbs: str = Field(..., description="IDs, URLs, keys needed for continuity")


@lru_cache(maxsize=1)
def _get_agent() -> Agent[None, SummarizationOutput]:
    """Cached summarization agent instance. Model loaded from agent.yaml."""
    agent_config = get_registry().get(_AGENT_NAME)
    model = _build_model(agent_config.model)
    instructions = assemble_instructions("system", "summarization")

    return Agent(
        model,
        system_prompt=instructions,
        output_type=SummarizationOutput,
    )


def get_agent(model: Model | None = None) -> Agent[None, SummarizationOutput]:
    """Get or create the summarization agent.

    Args:
        model: Optional model override for testing or roster-driven execution.
    """
    if model is not None:
        instructions = assemble_instructions("system", "summarization")
        return Agent(
            model,
            system_prompt=instructions,
            output_type=SummarizationOutput,
        )
    return _get_agent()


async def summarize_missions(
    mission_outcomes: list[dict],
    *,
    target_length: int = 500,
    model: Model | None = None,
) -> dict[str, Any]:
    """Summarize a batch of mission outcomes into a milestone summary.

    Args:
        mission_outcomes: List of mission outcome dicts to compress.
        target_length: Target summary length in characters.
        model: Optional model override.

    Returns:
        Dict with title, summary, key_outcomes, and domain_tags.
    """
    agent = get_agent(model)

    prompt = (
        f"Summarize these {len(mission_outcomes)} mission outcomes "
        f"into a single milestone summary. "
        f"Target summary length: {target_length} characters.\n\n"
        f"Mission outcomes:\n"
    )
    for i, outcome in enumerate(mission_outcomes, 1):
        prompt += f"\n--- Mission {i} ---\n"
        prompt += str(outcome)

    result = await agent.run(prompt)
    output = result.output

    return {
        "title": output.title,
        "summary": output.summary,
        "key_outcomes": output.key_outcomes,
        "domain_tags": output.domain_tags,
    }


async def summarize_session_span(
    messages: list[dict],
    existing_summary: str | None = None,
    *,
    model: Model | None = None,
) -> str:
    """Compress a span of session messages into an anchored rolling summary.

    Uses the Factory.ai 4-category pattern:
    1. SESSION INTENT — goals and current objectives
    2. PLAY-BY-PLAY — sequence of actions and outcomes
    3. ARTIFACT TRAIL — files, paths, resources created/modified
    4. BREADCRUMBS — IDs, URLs, keys needed for continuity

    Only summarizes the new span. Merges with existing summary if present.
    Uses Haiku for cost efficiency.

    Args:
        messages: New messages to compress (dicts with 'role' and 'content').
        existing_summary: Previous rolling summary to merge with (not re-summarized).
        model: Optional model override.

    Returns:
        Formatted rolling summary string.
    """
    if not messages:
        return existing_summary or ""

    # Build a session-specific agent (different output type from milestone agent)
    agent_config = get_registry().get(_AGENT_NAME)
    m = model or _build_model(agent_config.model)
    session_agent: Agent[None, SessionSpanSummary] = Agent(
        m,
        system_prompt=(
            "You compress conversation spans into structured summaries. "
            "Preserve factual detail. Never fabricate information."
        ),
        output_type=SessionSpanSummary,
    )

    formatted_messages = "\n".join(
        f"[{msg.get('role', 'unknown')}] {msg.get('content', '')[:500]}"
        for msg in messages
    )

    prompt = (
        "Summarize the following conversation span. Preserve:\n"
        "1. SESSION INTENT: goals and current objectives\n"
        "2. PLAY-BY-PLAY: sequence of actions and outcomes\n"
        "3. ARTIFACT TRAIL: files, paths, resources created/modified\n"
        "4. BREADCRUMBS: IDs, URLs, keys needed for continuity\n\n"
    )
    if existing_summary:
        prompt += (
            f"Previous summary (DO NOT re-summarize this, only merge):\n"
            f"{existing_summary}\n\n"
        )
    prompt += f"New messages to summarize:\n{formatted_messages}"

    result = await session_agent.run(prompt)
    output = result.output

    # Format as a readable summary
    parts = []
    if output.intent:
        parts.append(f"**Intent:** {output.intent}")
    if output.play_by_play:
        parts.append(f"**Progress:** {output.play_by_play}")
    if output.artifact_trail:
        parts.append(f"**Artifacts:** {output.artifact_trail}")
    if output.breadcrumbs:
        parts.append(f"**Breadcrumbs:** {output.breadcrumbs}")

    return "\n\n".join(parts)
