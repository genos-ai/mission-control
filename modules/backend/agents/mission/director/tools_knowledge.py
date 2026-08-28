"""Director tools: mission artifacts, intent capture, knowledge search.

Split out of agent.py (Plan 84 Phase 5.3). Pure move, no behavior change.
"""

from __future__ import annotations

import json

from pydantic_ai import Agent, RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import _emit_tool_failure
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def register_knowledge_tools(agent: Agent) -> None:
    """Register artifact/intent/knowledge-search tools."""

    @agent.tool
    async def get_artifacts(
        ctx: RunContext[MissionDirectorDeps],
        artifact_type: str | None = None,
    ) -> str:
        """Get artifacts (reports, findings) produced by this mission.

        Returns the latest artifacts from the mission_artifacts table.
        Use this to answer follow-up questions about completed research,
        code reviews, or any other agent-produced deliverables.

        Args:
            artifact_type: Optional filter (e.g. 'research_report',
                          'vulnerability_report'). If None, returns all.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.mission_artifact import MissionArtifactService

            artifacts = await MissionArtifactService(ctx.deps.db_session).list_for_mission(
                ctx.deps.mission_id,
                limit=5,
                artifact_type=artifact_type,
            )

            if not artifacts:
                return json.dumps(
                    {
                        "status": "no_artifacts",
                        "message": "No artifacts found for this mission.",
                    }
                )

            return json.dumps(
                [
                    {
                        "id": a.id,
                        "artifact_type": a.artifact_type,
                        "title": a.title,
                        "content_preview": (a.content_text or "")[:2000],
                        "created_at": str(a.created_at),
                    }
                    for a in artifacts
                ],
                indent=2,
                default=str,
            )

        except Exception as e:
            logger.error(
                "get_artifacts failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "get_artifacts", e)
            return json.dumps({"error": str(e)})

    # ── Intent Tools (Plan 57 Phase C) ─────────────────────

    @agent.tool
    async def capture_mission_intent(
        ctx: RunContext[MissionDirectorDeps],
        intent: str,
        scope_in: list[str] | None = None,
        scope_out: list[str] | None = None,
        reason: str = "Scope change detected in conversation",
    ) -> str:
        """Capture a revised intent when the user's goals or scope change.

        Call this when the user narrows, expands, or reprioritises
        the mission scope. Not for every message — only when scope
        actually shifts.

        Args:
            intent: The full current intent text.
            scope_in: What's in scope (optional list of items).
            scope_out: What's out of scope (optional list of items).
            reason: Why the intent changed.
        """
        from modules.backend.agents.adapters.intent import capture_intent

        scope = {}
        if scope_in:
            scope["in"] = scope_in
        if scope_out:
            scope["out"] = scope_out
        return await capture_intent(
            mission_id=ctx.deps.mission_id,
            intent=intent,
            scope=scope,
            reason=reason,
            session_id=ctx.deps.session_id,
        )

    @agent.tool
    async def get_current_mission_intent(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Retrieve the current mission intent and scope."""
        from modules.backend.agents.adapters.intent import restate_current_intent

        return await restate_current_intent(ctx.deps.mission_id)

    # ── Knowledge Query Tool (Plan 57 Phase D) ──────────────

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
        from modules.backend.tools.query_knowledge import query_knowledge as _query_knowledge

        return await _query_knowledge(
            ctx.deps.mission_id,
            query=query,
            kinds=kinds,
            domain_tags=domain_tags,
            platform_only=platform_only,
        )
