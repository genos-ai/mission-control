"""
Tool: browse_catalog

Browse the full agent catalog, flagging which entries are on the mission
team already.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import run_tool

# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _searchable_text(entry) -> str:
    """Build the haystack a keyword is matched against.

    Concatenates description, keywords and agent name, lowercased. Note
    that description and the joined keywords are not separated, which is
    pre-existing behaviour: a keyword spanning that join can match.
    """
    return (
        (entry.description or "").lower()
        + " ".join(entry.keywords or []).lower()
        + (entry.agent_name or "").lower()
    )


def _matches_keyword(entry, keyword: str | None) -> bool:
    """True when no keyword is given, or the entry's text contains it."""
    if not keyword:
        return True
    return keyword.lower() in _searchable_text(entry)


def _as_catalog_entry(entry, team_names: set[str]) -> dict:
    """Shape one catalog row for the model, flagging team membership."""
    return {
        "agent_name": entry.agent_name,
        "description": entry.description,
        "agent_type": entry.agent_type,
        "enabled": entry.enabled,
        "on_team": entry.agent_name in team_names,
        "keywords": entry.keywords or [],
        "tools": entry.tools or [],
        "scope": entry.scope or {},
        "interface": entry.interface,
        "constraints": entry.constraints or {},
        "chat_enabled": entry.chat_enabled,
    }


async def browse_catalog(
    db_session: AsyncSession,
    mission_id: str,
    keyword: str | None = None,
) -> list[dict]:
    """List catalog agents, optionally filtered, with team membership.

    Args:
        db_session: Active async session.
        mission_id: Mission whose team is compared against the catalog.
        keyword: Optional filter matched against description, keywords
            and agent name.

    Returns:
        One entry per matching catalog agent, including disabled ones.
    """
    from modules.backend.services.agent_catalog import AgentCatalogService
    from modules.backend.services.mission_team import MissionTeamService

    all_agents = await AgentCatalogService(db_session).list_catalog(enabled_only=False)
    members = await MissionTeamService(db_session).list_team_with_names(mission_id)
    team_names = {m["agent_name"] for m in members}

    return [
        _as_catalog_entry(entry, team_names)
        for entry in all_agents
        if _matches_keyword(entry, keyword)
    ]


# ── Registry integration ─────────────────────────────────

_impl = browse_catalog


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def browse_catalog(
        ctx: RunContext[MissionDirectorDeps],
        keyword: str | None = None,
    ) -> str:
        """Browse the full agent catalog to see what agents are available.

        Use this to discover agents that are NOT on the current mission
        team. If a needed agent is in the catalog but not on the team,
        suggest the user adds it via the Team tab or 'mc team add'.

        Args:
            keyword: Optional search keyword to filter by capabilities.

        Returns:
            JSON array of all catalog agents with name, type, description,
            enabled status, and whether they're on the current team.
        """
        return await run_tool(
            ctx,
            "browse_catalog",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id, keyword),
        )
