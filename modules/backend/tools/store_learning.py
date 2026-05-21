"""
Tool: store_learning

Store a new learning entry in the mission knowledge base.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def store_learning(
    mission_id: str,
    *,
    title: str,
    body: str,
    recommendation: str = "",
    kind: str = "learning",
    domain_tags: list[str] | None = None,
    confidence: float = 0.8,
) -> str:
    """Store a new learning entry in the mission knowledge base.

    Args:
        mission_id: Mission to store the learning under.
        title: Short title for the learning.
        body: Full text of the learning.
        recommendation: Actionable recommendation derived from the learning.
        kind: Entry kind — learning, decision, or milestone.
        domain_tags: Domain tags for categorisation.
        confidence: Confidence score 0.0–1.0.

    Returns:
        Confirmation string with the new learning ID.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_learning import MissionLearningService, _schedule_embed

    async with get_async_session() as db:
        svc = MissionLearningService(db)
        learning = await svc.create_learning(
            mission_id,
            kind=kind,
            title=title,
            body=body,
            recommendation=recommendation or body,
            domain_tags=domain_tags or [],
            confidence=confidence,
            agent_names=["workflow"],
        )
        learning_id = str(learning.id)
        await db.commit()

    # Fire embeds after commit so rows are visible to new sessions
    for lid in svc._embed_queue:
        _schedule_embed("mission_learnings", lid)

    logger.info("Learning stored", extra={"learning_id": learning_id, "mission_id": mission_id})
    return f"Learning stored (id={learning_id}): {title}"


# ── Registry integration ─────────────────────────────────

TOOL_DEF = {
    "name": "store_learning",
    "description": "Store a new learning entry in the mission knowledge base",
    "category": "knowledge",
    "deps": ["mission_id"],
}

_impl = store_learning
