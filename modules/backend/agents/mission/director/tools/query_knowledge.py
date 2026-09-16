"""
Tool: query_knowledge

Search the knowledge platform before spending tokens on discovery.

The implementation is the shared tool in `modules/backend/tools/`. This
module only holds the Director's registration, which unpacks deps and
delegates, exactly as the shared-tool pattern intends (P7).
"""

from __future__ import annotations

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps


def register(agent) -> None:
    """Register this tool on a PydanticAI agent.

    Does not use `run_tool`: the shared tool already returns a formatted
    string, and this tool had no session guard or error handling before
    extraction.
    """

    @agent.tool
    async def query_knowledge(
        ctx: RunContext[MissionDirectorDeps],
        query: str,
        domain_tags: list[str] | None = None,
        kinds: list[str] | None = None,
        platform_only: bool = False,
    ) -> str:
        """Search the knowledge platform for relevant learnings, decisions, and milestones.

        Use this to check "has anyone encountered this before?" before
        spending tokens on discovery. Returns matching entries with
        confidence scores and recommendations.

        Args:
            query: Free-text search query.
            domain_tags: Filter by domain tags (e.g. ["auth", "testing"]).
            kinds: Filter by kind (learning, decision, milestone).
            platform_only: Only search platform-promoted entries.
        """
        from modules.backend.tools.query_knowledge import query_knowledge as shared_impl

        return await shared_impl(
            ctx.deps.mission_id,
            query=query,
            kinds=kinds,
            domain_tags=domain_tags,
            platform_only=platform_only,
        )
