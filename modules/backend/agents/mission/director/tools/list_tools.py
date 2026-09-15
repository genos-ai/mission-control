"""
Tool: list_tools

Report the Director's own tool surface, so it does not invent tool names.
"""

from __future__ import annotations

import json

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps

_NOTE = "You can ONLY call tools in this list. Do not invent tool names."


def list_tools(registered_tools: list[dict]) -> dict:
    """Summarise the tools registered on the agent.

    Args:
        registered_tools: Name/description pairs collected by
            `create_agent` after every tool has registered.

    Returns:
        The count, the list, and a note constraining the model to it.
    """
    return {
        "available_tools": len(registered_tools),
        "tools": registered_tools,
        "note": _NOTE,
    }


# ── Registry integration ─────────────────────────────────

_impl = list_tools


def register(agent) -> None:
    """Register this tool on a PydanticAI agent.

    Deliberately does not use `run_tool`. This tool touches no session and
    had no error handling before extraction, so routing it through the
    shared scaffold would add a missing-session guard and a try/except it
    never had. `create_agent` sets `_registered_tools` on the registered
    wrapper by looking it up in the agent's toolset by name, so the
    attribute is read back off the wrapper here.
    """

    @agent.tool
    async def list_tools(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List all tools available to you. Call this when unsure what
        tools you have or before attempting an action you're not sure
        you can perform. You can ONLY use tools listed here."""
        # Tool names are collected after all @agent.tool registrations
        # and stored on the _registered_tools attribute by create_agent.
        tools = getattr(list_tools, "_registered_tools", [])
        return json.dumps(_impl(tools), indent=2)
