"""
Knowledge Service — unified facade for the knowledge platform.

Composer: delegates to existing services and repositories.
Does not reimplement HistoryQueryService, MissionContextManager,
or SummarizationService. See Plan 57 §10a reuse contract.

Search modes:
  structured — tag/kind/status filter only (zero embedding calls)
  semantic   — pure vector search via EmbeddingRepository
  hybrid     — structured filter → vector rerank (default)
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.embeddings import get_embedder
from modules.backend.core.logging import get_logger
from modules.backend.repositories.embedding import EmbeddingRepository
from modules.backend.repositories.mission_history import (
    MilestoneSummaryRepository,
    MissionDecisionRepository,
)
from modules.backend.repositories.mission_intent import MissionIntentRepository
from modules.backend.repositories.mission_learning import MissionLearningRepository
from modules.backend.schemas.knowledge import KnowledgeEntry
from modules.backend.services.base import BaseService
from modules.backend.services.history_query import HistoryQueryService
from modules.backend.services.mission_context import MissionContextManager

logger = get_logger(__name__)


class KnowledgeService(BaseService):
    """Unified read/search surface over all five knowledge surfaces."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        # Compose — don't reimplement
        self._context_manager = MissionContextManager(session)
        self._history_service = HistoryQueryService(session)
        self._intent_repo = MissionIntentRepository(session)
        self._learning_repo = MissionLearningRepository(session)
        self._embedding_repo = EmbeddingRepository(session)
        self._decision_repo = MissionDecisionRepository(session)
        self._milestone_repo = MilestoneSummaryRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["KnowledgeService", None]:
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield KnowledgeService(db)

    async def get_mission_knowledge(
        self,
        mission_id: str,
        *,
        domain_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Unified view of all knowledge for a mission.

        Returns a dict with keys: mcd, intent, learnings, decisions,
        milestones, failures.
        """
        mcd = await self._context_manager.get_context(mission_id)
        intent = await self._intent_repo.get_current(mission_id)
        learnings = await self._learning_repo.list_by_mission(
            mission_id,
            domain_tags=domain_tags,
            limit=20,
        )
        failures = await self._history_service.get_recent_failures(
            mission_id,
            domain_tags=domain_tags,
            limit=5,
        )
        summaries = await self._history_service.get_mission_summaries(
            mission_id,
            limit=10,
        )

        return {
            "mcd": mcd,
            "intent": (
                {
                    "id": intent.id,
                    "summary": intent.intent_summary,
                    "intent": intent.intent,
                    "scope": intent.scope,
                    "source": intent.source,
                    "created_at": str(intent.created_at),
                }
                if intent
                else None
            ),
            "learnings": [
                {
                    "id": lrn.id,
                    "kind": lrn.kind,
                    "title": lrn.title,
                    "confidence": lrn.confidence,
                    "occurrence_count": lrn.occurrence_count,
                    "recommendation": lrn.recommendation,
                    "domain_tags": lrn.domain_tags,
                }
                for lrn in learnings
            ],
            "recent_failures": failures,
            "recent_summaries": summaries,
        }

    async def search(
        self,
        query: str,
        *,
        mission_id: str | None = None,
        platform_only: bool = False,
        kinds: list[str] | None = None,
        domain_tags: list[str] | None = None,
        mode: str = "hybrid",
        limit: int = 20,
    ) -> list[KnowledgeEntry]:
        """Search across all knowledge surfaces.

        Args:
            query: Search text.
            mission_id: Scope to a specific mission (None = all visible).
            platform_only: Only platform-promoted entries.
            kinds: Filter by entry kind (learning, decision, milestone).
            domain_tags: Filter by domain tags.
            mode: "structured" | "semantic" | "hybrid" (default).
            limit: Max results.
        """
        if mode == "structured":
            return await self._search_structured(
                mission_id=mission_id,
                platform_only=platform_only,
                kinds=kinds,
                domain_tags=domain_tags,
                query=query,
                limit=limit,
            )
        elif mode == "semantic":
            return await self._search_semantic(
                query=query,
                mission_id=mission_id,
                limit=limit,
            )
        else:  # hybrid
            return await self._search_hybrid(
                query=query,
                mission_id=mission_id,
                platform_only=platform_only,
                kinds=kinds,
                domain_tags=domain_tags,
                limit=limit,
            )

    async def similar(
        self,
        source_table: str,
        source_id: str,
        *,
        limit: int = 10,
    ) -> list[KnowledgeEntry]:
        """Find entries similar to a given one by vector distance."""
        version = self._get_embedding_version()

        existing = await self._embedding_repo.get_by_source(
            source_table,
            source_id,
            version,
        )
        if not existing or not existing.embedding_data:
            return []

        # Parse the stored vector
        vec = _parse_vector(existing.embedding_data)
        if not vec:
            return []

        results = await self._embedding_repo.semantic_search(
            vec,
            limit=limit + 1,  # +1 to exclude self
        )

        entries: list[KnowledgeEntry] = []
        for r in results:
            if r["source_id"] == source_id and r["source_table"] == source_table:
                continue  # skip self
            entry = await self._fetch_entry(r["source_table"], r["source_id"])
            if entry:
                entry.distance = r["distance"]
                entries.append(entry)
            if len(entries) >= limit:
                break

        return entries

    async def get_current_intent(self, mission_id: str) -> dict | None:
        """Get the current intent for a mission."""
        intent = await self._intent_repo.get_current(mission_id)
        if not intent:
            return None
        return {
            "id": intent.id,
            "intent": intent.intent,
            "intent_summary": intent.intent_summary,
            "scope": intent.scope,
            "source": intent.source,
            "reason": intent.reason,
            "created_at": str(intent.created_at),
        }

    async def list_decisions(
        self,
        *,
        mission_id: str | None = None,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List archived decisions, optionally filtered by mission/domain."""
        decisions = await self._decision_repo.list_all(
            mission_id=mission_id,
            domain=domain,
            limit=limit,
        )
        return [
            {
                "id": d.id,
                "mission_id": d.mission_id,
                "decision_id": d.decision_id,
                "domain": d.domain,
                "decision": d.decision,
                "rationale": d.rationale,
                "made_by": d.made_by,
                "status": d.status,
                "created_at": str(d.created_at),
            }
            for d in decisions
        ]

    async def list_milestones(
        self,
        *,
        mission_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List milestone summaries, optionally filtered by mission."""
        milestones = await self._milestone_repo.list_all(
            mission_id=mission_id,
            limit=limit,
        )
        return [
            {
                "id": m.id,
                "mission_id": m.mission_id,
                "title": m.title,
                "summary": m.summary,
                "domain_tags": m.domain_tags,
                "key_outcomes": m.key_outcomes,
                "created_at": str(m.created_at),
            }
            for m in milestones
        ]

    # ------------------------------------------------------------------
    # Internal search implementations
    # ------------------------------------------------------------------

    async def _search_structured(
        self,
        *,
        mission_id: str | None,
        platform_only: bool,
        kinds: list[str] | None,
        domain_tags: list[str] | None,
        query: str,
        limit: int,
    ) -> list[KnowledgeEntry]:
        """Filter-only search. Zero embedding calls."""
        entries: list[KnowledgeEntry] = []

        # Learnings
        if not kinds or "learning" in kinds:
            if platform_only:
                learnings = await self._learning_repo.list_platform_promoted(
                    domain_tags=domain_tags,
                    limit=limit,
                )
            elif mission_id:
                learnings = await self._learning_repo.list_by_mission(
                    mission_id,
                    domain_tags=domain_tags,
                    limit=limit,
                )
            else:
                learnings = []

            for lrn in learnings:
                if query and query.lower() not in f"{lrn.title} {lrn.body}".lower():
                    continue
                entries.append(
                    KnowledgeEntry(
                        id=lrn.id,
                        kind="learning",
                        source_table="mission_learnings",
                        title=lrn.title,
                        body=lrn.recommendation,
                        domain_tags=lrn.domain_tags or [],
                        mission_id=lrn.mission_id,
                        confidence=lrn.confidence,
                        created_at=str(lrn.created_at),
                    )
                )

        # Decisions (from HistoryQueryService pattern)
        if not kinds or "decision" in kinds:
            if mission_id:
                from modules.backend.repositories.mission_history import MissionDecisionRepository

                decision_repo = MissionDecisionRepository(self.session)
                decisions = await decision_repo.list_active(mission_id, limit=limit)
                for d in decisions:
                    if query and query.lower() not in f"{d.decision} {d.rationale}".lower():
                        continue
                    entries.append(
                        KnowledgeEntry(
                            id=d.id,
                            kind="decision",
                            source_table="mission_decisions",
                            title=f"d-{d.decision_id}: {d.domain}",
                            body=f"{d.decision}\n{d.rationale}",
                            domain_tags=[d.domain] if d.domain else [],
                            mission_id=d.mission_id,
                            created_at=str(d.created_at),
                        )
                    )

        return entries[:limit]

    async def _search_semantic(
        self,
        *,
        query: str,
        mission_id: str | None,
        limit: int,
    ) -> list[KnowledgeEntry]:
        """Pure vector search. Embeds query, finds nearest."""
        embedder = get_embedder()
        query_vec = await embedder.embed(query)
        if not query_vec:
            # Provider failed (fail-open) — fall back to structured
            return await self._search_structured(
                mission_id=mission_id,
                platform_only=False,
                kinds=None,
                domain_tags=None,
                query=query,
                limit=limit,
            )

        results = await self._embedding_repo.semantic_search(
            query_vec,
            source_tables=["mission_learnings", "mission_decisions", "milestone_summaries"],
            mission_id=mission_id,
            limit=limit,
        )

        entries: list[KnowledgeEntry] = []
        for r in results:
            entry = await self._fetch_entry(
                r["source_table"],
                r["source_id"],
                mission_id=mission_id,
            )
            if entry:
                entry.distance = r["distance"]
                entries.append(entry)

        return entries

    async def _search_hybrid(
        self,
        *,
        query: str,
        mission_id: str | None,
        platform_only: bool,
        kinds: list[str] | None,
        domain_tags: list[str] | None,
        limit: int,
    ) -> list[KnowledgeEntry]:
        """Structured filter → vector rerank."""
        # Step 1: structured filter to get candidate IDs
        structured = await self._search_structured(
            mission_id=mission_id,
            platform_only=platform_only,
            kinds=kinds,
            domain_tags=domain_tags,
            query="",  # no text filter in step 1
            limit=200,
        )

        if not structured:
            return []

        # Step 2: embed query
        embedder = get_embedder()
        query_vec = await embedder.embed(query)
        if not query_vec:
            # Provider failed — return structured results with text filter
            return [e for e in structured if query.lower() in f"{e.title} {e.body}".lower()][:limit]

        # Step 3: rerank by vector distance
        filter_ids: dict[str, list[str]] = {}
        for e in structured:
            filter_ids.setdefault(e.source_table, []).append(e.id)

        reranked = await self._embedding_repo.hybrid_search(
            query_vec,
            filter_ids,
            limit=limit,
        )

        # Build ordered result
        entries: list[KnowledgeEntry] = []
        # Map structured entries by (source_table, id)
        entry_map = {(e.source_table, e.id): e for e in structured}

        for r in reranked:
            entry = entry_map.get((r["source_table"], r["source_id"]))
            if entry:
                entry.distance = r["distance"]
                entries.append(entry)

        # Add entries that have no embedding (not yet embedded)
        embedded_ids = {(r["source_table"], r["source_id"]) for r in reranked}
        for e in structured:
            if (e.source_table, e.id) not in embedded_ids:
                entries.append(e)
            if len(entries) >= limit:
                break

        return entries[:limit]

    async def _fetch_entry(
        self,
        source_table: str,
        source_id: str,
        mission_id: str | None = None,
    ) -> KnowledgeEntry | None:
        """Fetch a source row and convert to KnowledgeEntry.

        mission_id is the search scope (when known) — used only for log
        context; the entry's own mission_id comes from the fetched row.
        """
        if source_table == "mission_learnings":
            try:
                lrn = await self._learning_repo.get_by_id(source_id)
                return KnowledgeEntry(
                    id=lrn.id,
                    kind="learning",
                    source_table=source_table,
                    title=lrn.title,
                    body=lrn.recommendation,
                    domain_tags=lrn.domain_tags or [],
                    mission_id=lrn.mission_id,
                    confidence=lrn.confidence,
                    created_at=str(lrn.created_at),
                )
            except Exception:
                logger.warning(
                    "Failed to fetch learning entry",
                    extra={
                        "source_table": source_table,
                        "source_id": source_id,
                        "mission_id": mission_id,
                    },
                    exc_info=True,
                )
                return None

        elif source_table == "mission_decisions":
            try:
                from modules.backend.repositories.mission_history import MissionDecisionRepository

                repo = MissionDecisionRepository(self.session)
                d = await repo.get_by_id(source_id)
                return KnowledgeEntry(
                    id=d.id,
                    kind="decision",
                    source_table=source_table,
                    title=f"d-{d.decision_id}: {d.domain}",
                    body=f"{d.decision}\n{d.rationale}",
                    domain_tags=[d.domain] if d.domain else [],
                    mission_id=d.mission_id,
                    created_at=str(d.created_at),
                )
            except Exception:
                logger.warning(
                    "Failed to fetch decision entry",
                    extra={
                        "source_table": source_table,
                        "source_id": source_id,
                        "mission_id": mission_id,
                    },
                    exc_info=True,
                )
                return None

        elif source_table == "milestone_summaries":
            try:
                from modules.backend.repositories.mission_history import MilestoneSummaryRepository

                repo = MilestoneSummaryRepository(self.session)
                m = await repo.get_by_id(source_id)
                return KnowledgeEntry(
                    id=m.id,
                    kind="milestone",
                    source_table=source_table,
                    title=m.title,
                    body=m.summary,
                    domain_tags=m.domain_tags or [],
                    mission_id=m.mission_id,
                    created_at=str(m.created_at),
                )
            except Exception:
                logger.warning(
                    "Failed to fetch milestone entry",
                    extra={
                        "source_table": source_table,
                        "source_id": source_id,
                        "mission_id": mission_id,
                    },
                    exc_info=True,
                )
                return None

        return None

    @staticmethod
    def _get_embedding_version() -> int:
        """Get current embedding version from config."""
        from modules.backend.services.knowledge_helpers import get_embedding_version

        return get_embedding_version()


def _parse_vector(vec_str: str | None) -> list[float] | None:
    """Parse a pgvector literal string back to a list of floats."""
    if not vec_str:
        return None
    try:
        cleaned = vec_str.strip("[]")
        return [float(x) for x in cleaned.split(",")]
    except Exception:
        logger.warning(
            "Failed to parse vector string",
            # Module-level parse helper — no mission in scope by design.
            extra={
                "vec_preview": vec_str[:50] if vec_str else None,
                "mission_id": None,
            },
            exc_info=True,
        )
        return None
