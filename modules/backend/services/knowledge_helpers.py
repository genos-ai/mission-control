"""
Knowledge Helpers — shared utilities for the knowledge platform.

Extracted to avoid duplication between KnowledgeService and
Temporal knowledge activities. Pure functions, no service state.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def get_embedding_version() -> int:
    """Get current embedding model version from config."""
    try:
        from modules.backend.core.config import get_app_config

        return get_app_config().missions.knowledge.embedding.version
    except Exception:
        logger.debug("Embedding version config unavailable, defaulting to 1")
        return 1


async def get_embed_text(source_table: str, source_id: str) -> str | None:
    """Load the text-to-embed from a source row.

    Each embeddable model provides its own text representation.
    Returns None if the row doesn't exist or can't be loaded.
    """
    from modules.backend.core.database import get_async_session

    async with get_async_session() as db:
        try:
            if source_table == "mission_learnings":
                from modules.backend.repositories.mission_learning import MissionLearningRepository

                row = await MissionLearningRepository(db).get_by_id(source_id)
                return row.embed_text

            elif source_table == "mission_intents":
                from modules.backend.repositories.mission_intent import MissionIntentRepository

                row = await MissionIntentRepository(db).get_by_id(source_id)
                return f"{row.intent_summary}\n{row.intent}"

            elif source_table == "mission_decisions":
                from modules.backend.repositories.mission_history import MissionDecisionRepository

                row = await MissionDecisionRepository(db).get_by_id(source_id)
                return f"{row.decision}\n{row.rationale}"

            elif source_table == "milestone_summaries":
                from modules.backend.repositories.mission_history import MilestoneSummaryRepository

                row = await MilestoneSummaryRepository(db).get_by_id(source_id)
                return f"{row.title}\n{row.summary}"

        except Exception:
            logger.warning(
                "Failed to load embed text for source row",
                extra={"source_table": source_table, "source_id": source_id},
                exc_info=True,
            )
            return None

    return None


async def get_source_mission_id(source_table: str, source_id: str) -> str | None:
    """Get mission_id from a source row for embedding CASCADE.

    Uses the appropriate repository rather than raw SQL.
    """
    from modules.backend.core.database import get_async_session

    async with get_async_session() as db:
        try:
            if source_table == "mission_learnings":
                from modules.backend.repositories.mission_learning import MissionLearningRepository

                row = await MissionLearningRepository(db).get_by_id(source_id)
                return row.mission_id

            elif source_table == "mission_intents":
                from modules.backend.repositories.mission_intent import MissionIntentRepository

                row = await MissionIntentRepository(db).get_by_id(source_id)
                return row.mission_id

            elif source_table in ("mission_decisions", "milestone_summaries"):
                from modules.backend.repositories.mission_history import (
                    MilestoneSummaryRepository,
                    MissionDecisionRepository,
                )

                if source_table == "mission_decisions":
                    row = await MissionDecisionRepository(db).get_by_id(source_id)
                else:
                    row = await MilestoneSummaryRepository(db).get_by_id(source_id)
                return row.mission_id

        except Exception:
            logger.warning(
                "Failed to resolve mission_id for source row",
                extra={"source_table": source_table, "source_id": source_id},
                exc_info=True,
            )
            return None

    return None
