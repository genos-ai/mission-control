"""Director tools: mission/team/catalog introspection and background-task status.

Registration only. Each tool lives in its own module under `tools/`,
holding its implementation as a plain async function plus the thin
`@agent.tool` wrapper (P7). Registration order is preserved from the
pre-refactor file, since it determines the order the model sees tools in.
"""

from __future__ import annotations

from pydantic_ai import Agent

from modules.backend.agents.mission.director.tools import (
    browse_catalog,
    check_background_tasks,
    get_execution_detail,
    get_execution_history,
    get_mission_context,
    get_mission_info,
    list_team,
    list_tools,
)


def register_mission_tools(agent: Agent) -> None:
    """Register mission/team/catalog/history introspection tools."""
    list_tools.register(agent)
    get_mission_info.register(agent)
    list_team.register(agent)
    browse_catalog.register(agent)
    get_execution_history.register(agent)
    get_execution_detail.register(agent)
    get_mission_context.register(agent)
    check_background_tasks.register(agent)
