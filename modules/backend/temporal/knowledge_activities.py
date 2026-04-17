"""
Knowledge Platform Temporal Activities (Plan 57).

Local activities for learning extraction and embedding generation.
Scheduled via Temporal: daily extraction + daily sweep for missing embeddings.
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
        "learning_ids": [l.id for l in created],
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

    embedder = get_embedder()
    version = _get_embedding_version()

    # Load the source row's embed text
    embed_text = await _get_embed_text(source_table, source_id)
    if not embed_text:
        return {"status": "skipped", "reason": "no embed text"}

    # Generate embedding
    vec = await embedder.embed(embed_text)
    if not vec:
        return {"status": "skipped", "reason": "provider returned empty"}

    # Get mission_id for cascade
    mission_id = await _get_mission_id(source_table, source_id)

    # Upsert
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

    embedder = get_embedder()
    version = to_version or _get_embedding_version()
    tables = [source_table] if source_table else [
        "mission_learnings",
        "mission_intents",
        "mission_decisions",
        "milestone_summaries",
    ]

    total_embedded = 0
    for table in tables:
        async with get_async_session() as db:
            repo = EmbeddingRepository(db)
            missing = await repo.list_missing(table, version, limit=50)

            for row in missing:
                embed_text = await _get_embed_text(table, row["source_id"])
                if not embed_text:
                    continue
                vec = await embedder.embed(embed_text)
                if not vec:
                    continue

                mission_id = await _get_mission_id(table, row["source_id"])
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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_embedding_version() -> int:
    """Get current embedding version from config."""
    try:
        from modules.backend.core.config import get_app_config
        return get_app_config().missions.knowledge.embedding.version
    except Exception:
        return 1


async def _get_embed_text(source_table: str, source_id: str) -> str | None:
    """Load the text to embed from a source row."""
    from modules.backend.core.database import get_async_session

    async with get_async_session() as db:
        if source_table == "mission_learnings":
            from modules.backend.repositories.mission_learning import MissionLearningRepository
            repo = MissionLearningRepository(db)
            try:
                row = await repo.get_by_id(source_id)
                return row.embed_text
            except Exception:
                return None

        elif source_table == "mission_intents":
            from modules.backend.repositories.mission_intent import MissionIntentRepository
            repo = MissionIntentRepository(db)
            try:
                row = await repo.get_by_id(source_id)
                return f"{row.intent_summary}\n{row.intent}"
            except Exception:
                return None

        elif source_table == "mission_decisions":
            from modules.backend.repositories.mission_history import MissionDecisionRepository
            repo = MissionDecisionRepository(db)
            try:
                row = await repo.get_by_id(source_id)
                return f"{row.decision}\n{row.rationale}"
            except Exception:
                return None

        elif source_table == "milestone_summaries":
            from modules.backend.repositories.mission_history import MilestoneSummaryRepository
            repo = MilestoneSummaryRepository(db)
            try:
                row = await repo.get_by_id(source_id)
                return f"{row.title}\n{row.summary}"
            except Exception:
                return None

    return None


async def _get_mission_id(source_table: str, source_id: str) -> str | None:
    """Get mission_id from a source row for embedding CASCADE."""
    from modules.backend.core.database import get_async_session

    async with get_async_session() as db:
        if source_table in ("mission_learnings", "mission_intents", "mission_decisions", "milestone_summaries"):
            from sqlalchemy import select, text
            result = await db.execute(
                text(f"SELECT mission_id FROM {source_table} WHERE id = :id").bindparams(id=source_id)
            )
            row = result.first()
            return row[0] if row else None
    return None
