"""
Synthesis Agent — human-readable narrative from structured outcome data.

Presentation-layer agent. Reads verified, structured mission/workflow
results and produces a concise narrative summary. Uses Haiku for cost
efficiency — the input is already structured, no complex reasoning needed.

P13 compliant: reports facts, does not evaluate agent performance.
"""

import json
from functools import lru_cache
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

_AGENT_NAME = "system.synthesis.agent"


@lru_cache(maxsize=1)
def _get_agent() -> Agent[None, str]:
    """Cached synthesis agent instance. Model loaded from agent.yaml."""
    agent_config = get_registry().get(_AGENT_NAME)
    model = _build_model(agent_config.model)
    instructions = assemble_instructions("system", "synthesis")

    return Agent(
        model,
        output_type=str,
        instructions=instructions,
    )


def create_agent(model: str | Model | None = None) -> Agent[None, str]:
    """Create a synthesis agent with the given model.

    Args:
        model: Model override for roster-driven execution. Falls back
            to the registry-configured model when None.
    """
    if model is not None:
        m = _build_model(model) if isinstance(model, str) else model
        instructions = assemble_instructions("system", "synthesis")
        return Agent(m, output_type=str, instructions=instructions)
    return _get_agent()


async def synthesize(outcome_data: dict[str, Any]) -> str:
    """Generate a human-readable narrative from outcome data.

    Public entry point. Returns indented text ready for CLI display.
    Raises on failure — caller decides fallback policy.
    """
    agent = create_agent()

    prompt = (
        "Summarize the following outcome data into a concise narrative "
        "for a human operator.\n\n"
        f"```json\n{json.dumps(outcome_data, indent=2, default=str)}\n```"
    )

    result = await agent.run(prompt)

    return result.output.strip()
