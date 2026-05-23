"""
Tool: store_artifact

Persist a text artifact to the mission artifact store.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def store_artifact(
    mission_id: str,
    *,
    title: str,
    content: str,
    artifact_type: str = "report",
    content_type: str = "markdown",
) -> str:
    """Persist a text artifact to the mission artifact store.

    Args:
        mission_id: Mission to attach the artifact to.
        title: Short descriptive title.
        content: Full artifact text content.
        artifact_type: One of report, research_report, code, data,
            vulnerability_report, quality_audit, architecture_review.
        content_type: One of text, markdown.

    Returns:
        Confirmation string with the new artifact ID.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_artifact import MissionArtifactService

    async with get_async_session() as db:
        svc = MissionArtifactService(db)
        artifact = await svc.create_artifact(
            mission_id=mission_id,
            agent_id="workflow",
            title=title,
            content_text=content,
            artifact_type=artifact_type,
            content_type=content_type,
        )
        artifact_id = str(artifact.id)
        await db.commit()

    logger.info(
        "Artifact stored",
        extra={"artifact_id": artifact_id, "mission_id": mission_id, "title": title},
    )
    return f"Artifact stored (id={artifact_id}): {title}"


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "store_artifact",
    "description": "Persist a text artifact to the mission artifact store",
    "category": "knowledge",
    "deps": ["mission_id"],
}

_impl = store_artifact
