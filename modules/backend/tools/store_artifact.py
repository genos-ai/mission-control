"""
Tool: store_artifact

Persist a text or structured artifact to the mission artifact store.

Plan 79 §9.1 — accepts content as str, dict, or list. dict/list values
are JSON-encoded so the schema-validated FinalDeliverable from the
synthesiser can be persisted as a structured artifact that
programmatic consumers can query. Fails loud when content type and
content_type disagree (e.g. dict content with content_type=markdown).
"""

import json

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def store_artifact(
    mission_id: str,
    *,
    title: str,
    content: str | dict | list,
    artifact_type: str = "report",
    content_type: str = "markdown",
) -> str:
    """Persist an artifact to the mission artifact store.

    Args:
        mission_id: Mission to attach the artifact to.
        title: Short descriptive title.
        content: Artifact body. May be a str (used as-is), a dict, or a
            list (JSON-encoded). When content is dict/list, content_type
            MUST be "json" — passing dict content with content_type
            other than json fails loud with ValueError so YAML authors
            find the mismatch immediately.
        artifact_type: Domain tag (report, deliberation_deliverable,
            deliberation_transcript, etc).
        content_type: One of text, markdown, json.

    Returns:
        Confirmation string with the new artifact ID.

    Raises:
        ValueError: when content type and content_type disagree.
        TypeError: when content is not str/dict/list.
    """
    if isinstance(content, (dict, list)):
        if content_type != "json":
            raise ValueError(
                f"store_artifact: content is {type(content).__name__} but "
                f"content_type is {content_type!r}; structured content "
                f"requires content_type='json'"
            )
        content_text = json.dumps(content, default=str, indent=2)
    elif isinstance(content, str):
        content_text = content
    else:
        raise TypeError(
            f"store_artifact: content must be str/dict/list, got "
            f"{type(content).__name__}"
        )

    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_artifact import MissionArtifactService

    async with get_async_session() as db:
        svc = MissionArtifactService(db)
        artifact = await svc.create_artifact(
            mission_id=mission_id,
            agent_id="workflow",
            title=title,
            content_text=content_text,
            artifact_type=artifact_type,
            content_type=content_type,
        )
        artifact_id = str(artifact.id)
        await db.commit()

    logger.info(
        "Artifact stored",
        extra={
            "artifact_id": artifact_id,
            "mission_id": mission_id,
            "title": title,
            "content_type": content_type,
            "artifact_type": artifact_type,
            "content_bytes": len(content_text),
        },
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
