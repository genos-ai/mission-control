"""
Knowledge Platform Temporal Activities (Plan 57).

Local activities for learning extraction and embedding generation.
Scheduled via Temporal: daily extraction + daily sweep for missing embeddings.

Uses shared helpers from services/knowledge_helpers.py to avoid
duplicating source-row loading and config resolution.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@activity.defn
async def extract_mission_learnings(mission_id: str) -> dict:
    """Extract learnings from a mission's execution history.

    Called post-mission-completion and as a daily sweep.
    Deterministic — no LLM (P2).
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_learning import MissionLearningExtractor

    async with get_async_session() as db:
        extractor = MissionLearningExtractor(db)
        created = await extractor.extract_for_mission(mission_id)
        await db.commit()

    result = {
        "mission_id": mission_id,
        "learnings_created": len(created),
        "learning_ids": [learning.id for learning in created],
    }
    logger.info("Learning extraction complete", extra=result)
    return result


@activity.defn
async def embed_source(source_table: str, source_id: str) -> dict:
    """Generate and store an embedding for a source row.

    Fired on every write to an embeddable source row. Async —
    never blocks the source write. Idempotent via upsert.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.core.embeddings import content_hash, get_embedder
    from modules.backend.repositories.embedding import EmbeddingRepository
    from modules.backend.services.knowledge_helpers import (
        get_embed_text,
        get_embedding_version,
        get_source_mission_id,
    )

    embedder = get_embedder()
    version = get_embedding_version()

    embed_text = await get_embed_text(source_table, source_id)
    if not embed_text:
        return {"status": "skipped", "reason": "no embed text"}

    vec = await embedder.embed(embed_text)
    if not vec:
        return {"status": "skipped", "reason": "provider returned empty"}

    mission_id = await get_source_mission_id(source_table, source_id)

    async with get_async_session() as db:
        repo = EmbeddingRepository(db)
        await repo.upsert(
            source_table=source_table,
            source_id=source_id,
            embedding=vec,
            model=embedder.model_name,
            version=version,
            mission_id=mission_id,
            content_hash=content_hash(embed_text),
        )
        await db.commit()

    return {
        "status": "embedded",
        "source_table": source_table,
        "source_id": source_id,
        "model": embedder.model_name,
        "version": version,
    }


@activity.defn
async def backfill_embeddings(
    source_table: str | None = None,
    to_version: int | None = None,
) -> dict:
    """Re-embed rows missing at the current version.

    Called daily as a safety net and manually via admin CLI.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.core.embeddings import content_hash, get_embedder
    from modules.backend.repositories.embedding import EmbeddingRepository
    from modules.backend.services.knowledge_helpers import (
        get_embed_text,
        get_embedding_version,
        get_source_mission_id,
    )

    embedder = get_embedder()
    version = to_version or get_embedding_version()
    tables = (
        [source_table]
        if source_table
        else [
            "mission_learnings",
            "mission_intents",
            "mission_decisions",
            "milestone_summaries",
        ]
    )

    total_embedded = 0
    for table in tables:
        async with get_async_session() as db:
            repo = EmbeddingRepository(db)
            missing = await repo.list_missing(table, version, limit=50)

            for row in missing:
                embed_text = await get_embed_text(table, row["source_id"])
                if not embed_text:
                    continue
                vec = await embedder.embed(embed_text)
                if not vec:
                    continue

                mission_id = await get_source_mission_id(table, row["source_id"])
                await repo.upsert(
                    source_table=table,
                    source_id=row["source_id"],
                    embedding=vec,
                    model=embedder.model_name,
                    version=version,
                    mission_id=mission_id,
                    content_hash=content_hash(embed_text),
                )
                total_embedded += 1

            await db.commit()

    result = {"total_embedded": total_embedded, "version": version}
    logger.info("Embedding backfill complete", extra=result)
    return result


@activity.defn
async def extract_all_missions() -> dict:
    """Extract learnings across all active missions.

    Called daily by KnowledgeExtractionWorkflow.
    Walks every active mission and runs the extractor.
    """
    from sqlalchemy import select

    from modules.backend.core.database import get_async_session
    from modules.backend.models.mission import Mission, MissionStatus
    from modules.backend.services.mission_learning import MissionLearningExtractor

    total_created = 0
    missions_processed = 0

    async with get_async_session() as db:
        result = await db.execute(select(Mission.id).where(Mission.status == MissionStatus.ACTIVE))
        mission_ids = [row[0] for row in result.all()]

    for mid in mission_ids:
        async with get_async_session() as db:
            extractor = MissionLearningExtractor(db)
            created = await extractor.extract_for_mission(mid)
            await db.commit()
            total_created += len(created)
            missions_processed += 1

    result = {
        "missions_processed": missions_processed,
        "learnings_created": total_created,
    }
    logger.info("Daily learning extraction complete", extra=result)
    return result


@activity.defn
async def run_knowledge_officer() -> dict:
    """Run the Knowledge Officer curation cycle.

    Called daily by KnowledgeOfficerWorkflow.
    """
    from modules.backend.agents.system.knowledge.officer.agent import run_officer

    return await run_officer()
