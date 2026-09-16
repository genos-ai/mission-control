"""
Tool: get_artifacts

Artifacts produced by the mission: reports, findings and other
agent-produced deliverables.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import CompactResult, run_tool

# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_ARTIFACT_LIMIT = 5
_PREVIEW_CHARS = 2000
_NO_ARTIFACTS = {
    "status": "no_artifacts",
    "message": "No artifacts found for this mission.",
}


def _as_artifact(artifact) -> dict:
    """Shape one artifact for the model, truncating the body.

    Only a preview is returned: artifact bodies are full reports and
    would otherwise dominate the Director's context.
    """
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "content_preview": (artifact.content_text or "")[:_PREVIEW_CHARS],
        "created_at": str(artifact.created_at),
    }


async def get_artifacts(
    db_session: AsyncSession,
    mission_id: str,
    artifact_type: str | None = None,
) -> list[dict] | CompactResult:
    """Read the mission's most recent artifacts.

    Args:
        db_session: Active async session.
        mission_id: Mission whose artifacts to read.
        artifact_type: Optional type filter.

    Returns:
        Up to five artifacts with truncated previews, or a
        `CompactResult` status payload when the mission has none.
    """
    from modules.backend.services.mission_artifact import MissionArtifactService

    artifacts = await MissionArtifactService(db_session).list_for_mission(
        mission_id,
        limit=_ARTIFACT_LIMIT,
        artifact_type=artifact_type,
    )

    if not artifacts:
        return CompactResult(dict(_NO_ARTIFACTS))

    return [_as_artifact(artifact) for artifact in artifacts]


# ── Registry integration ─────────────────────────────────

_impl = get_artifacts


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

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
        return await run_tool(
            ctx,
            "get_artifacts",
            partial(_impl, ctx.deps.db_session, ctx.deps.mission_id, artifact_type),
        )
