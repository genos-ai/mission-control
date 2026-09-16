"""Director tools: mission artifacts, intent capture, knowledge search.

Registration only. Each tool lives in its own module under `tools/`,
holding its implementation as a plain async function plus the thin
`@agent.tool` wrapper (P7). Registration order is preserved from the
pre-refactor file, since it determines the order the model sees tools in.
"""

from __future__ import annotations

from pydantic_ai import Agent

from modules.backend.agents.mission.director.tools import (
    capture_mission_intent,
    get_artifacts,
    get_current_mission_intent,
    query_knowledge,
)


def register_knowledge_tools(agent: Agent) -> None:
    """Register artifact/intent/knowledge-search tools."""
    get_artifacts.register(agent)
    capture_mission_intent.register(agent)
    get_current_mission_intent.register(agent)
    query_knowledge.register(agent)
