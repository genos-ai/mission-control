"""
Mission Learning Service + Deterministic Extractor.

MissionLearningService: CRUD, promote, retract, contradiction candidates.
MissionLearningExtractor: reads TaskAttempt history and produces structured
learnings. No LLM — pure deterministic pattern matching (P2).
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.backend.core.domain_tags import normalize_tag, validate_tags
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.execution_record import (
    ExecutionRecord,
    ExecutionRecordStatus,
    TaskAttempt,
    TaskAttemptStatus,
    TaskExecution,
)
from modules.backend.models.mission_learning import LearningKind, LearningStatus, MissionLearning
from modules.backend.repositories.mission_learning import MissionLearningRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


def _schedule_embed(source_table: str, source_id: str) -> None:
    """Fire embed_source as a background task. Best-effort, non-blocking."""
    import asyncio

    async def _fire():
        try:
            from modules.backend.temporal.client import get_temporal_client, get_temporal_config

            client = await get_temporal_client()
            config = get_temporal_config()

            from modules.backend.temporal.knowledge_activities import embed_source

            await client.execute_workflow(
                "no-op",  # Not a workflow — use start_activity pattern
                task_queue=config.task_queue,
            )
        except Exception:
            logger.debug("Embed-on-write skipped (Temporal unavailable)", exc_info=True)

    # Can't reliably fire a Temporal activity from a service without
    # a workflow context. Use asyncio.create_task as a fallback —
    # the daily backfill sweep catches any misses.
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_fire_embed_direct(source_table, source_id))
    except RuntimeError:
        pass  # No event loop — skip (e.g. CLI context)


async def _fire_embed_direct(source_table: str, source_id: str) -> None:
    """Directly embed a source row. Called from create_task."""
    try:
        from modules.backend.core.database import get_async_session
        from modules.backend.core.embeddings import content_hash, get_embedder
        from modules.backend.repositories.embedding import EmbeddingRepository
        from modules.backend.services.knowledge_helpers import (
            get_embed_text,
            get_embedding_version,
            get_source_mission_id,
        )

        embed_text = await get_embed_text(source_table, source_id)
        if not embed_text:
            return

        embedder = get_embedder()
        vec = await embedder.embed(embed_text)
        if not vec:
            return

        version = get_embedding_version()
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
    except Exception:
        logger.debug("Embed-on-write failed (backfill will catch)", exc_info=True)


def _load_learning_config() -> dict:
    """Load knowledge.learnings config with safe defaults."""
    try:
        from modules.backend.core.config import get_app_config

        cfg = get_app_config().missions.knowledge.learnings
        return {
            "min_occurrence": cfg.min_occurrence_for_extraction,
            "promotion_threshold": cfg.promotion_confidence_threshold,
            "promotion_min_missions": cfg.promotion_min_missions,
            "dedup_threshold": cfg.dedup_similarity_threshold,
        }
    except Exception:
        return {
            "min_occurrence": 2,
            "promotion_threshold": 0.7,
            "promotion_min_missions": 2,
            "dedup_threshold": 0.92,
        }


class MissionLearningService(BaseService):
    """CRUD + governance operations for mission learnings."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._learning_repo = MissionLearningRepository(session)
        self._embed_queue: list[str] = []

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["MissionLearningService", None]:
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            svc = MissionLearningService(db)
            yield svc
            await db.commit()
            svc.flush_embeds()

    async def create_learning(
        self,
        mission_id: str,
        *,
        kind: str,
        title: str,
        body: str,
        recommendation: str,
        evidence: dict | None = None,
        domain_tags: list[str] | None = None,
        agent_names: list[str] | None = None,
        confidence: float = 0.0,
        occurrence_count: int = 1,
    ) -> MissionLearning:
        """Create a new learning entry with tag validation."""
        validated_tags, _ = validate_tags(domain_tags or [])

        learning = await self._learning_repo.create(
            mission_id=mission_id,
            kind=kind,
            title=title,
            body=body,
            recommendation=recommendation,
            evidence=evidence or {},
            domain_tags=validated_tags,
            agent_names=agent_names or [],
            confidence=confidence,
            occurrence_count=occurrence_count,
        )

        self._embed_queue.append(str(learning.id))
        return learning

    def flush_embeds(self) -> None:
        """Fire embed tasks for all queued learning IDs. Call after committing."""
        for learning_id in self._embed_queue:
            _schedule_embed("mission_learnings", learning_id)
        self._embed_queue.clear()

    async def get_by_id(self, learning_id: str) -> MissionLearning:
        """Get a single learning by ID. Raises NotFoundError if missing."""
        return await self._learning_repo.get_by_id(learning_id)

    async def count_by_mission(
        self,
        mission_id: str,
        *,
        status: str | None = LearningStatus.ACTIVE.value,
    ) -> int:
        """Count learnings for a mission."""
        return await self._learning_repo.count_by_mission(
            mission_id,
            status=status,
        )

    async def list_by_mission(
        self,
        mission_id: str,
        *,
        kind: str | None = None,
        domain_tags: list[str] | None = None,
        status: str | None = LearningStatus.ACTIVE.value,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MissionLearning]:
        return await self._learning_repo.list_by_mission(
            mission_id,
            kind=kind,
            domain_tags=domain_tags,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def list_platform(
        self,
        *,
        kind: str | None = None,
        domain_tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MissionLearning]:
        return await self._learning_repo.list_platform_promoted(
            kind=kind,
            domain_tags=domain_tags,
            limit=limit,
            offset=offset,
        )

    async def promote(self, learning_id: str, promoted_by: str) -> None:
        """Promote a learning to platform scope. Idempotent."""
        await self._learning_repo.promote(learning_id, promoted_by)
        self._log_operation(
            "Learning promoted to platform",
            learning_id=learning_id,
            promoted_by=promoted_by,
        )

    async def retract(self, learning_id: str) -> None:
        """Retract a learning. Idempotent."""
        await self._learning_repo.retract(learning_id)
        self._log_operation("Learning retracted", learning_id=learning_id)

    async def find_contradiction_candidates(
        self,
        mission_id: str | None = None,
    ) -> list[tuple[MissionLearning, MissionLearning]]:
        """Find learning pairs that may contradict each other.

        Phase 1 of two-phase contradiction detection (deterministic).
        Looks for active learnings with overlapping domain_tags + agent_names
        and opposing recommendation verbs.
        """
        query = select(MissionLearning).where(MissionLearning.status == LearningStatus.ACTIVE.value)
        if mission_id:
            query = query.where(MissionLearning.mission_id == mission_id)

        result = await self.session.execute(
            query.order_by(desc(MissionLearning.confidence)).limit(200)
        )
        learnings = list(result.scalars().all())

        # Simple heuristic: opposing verbs in recommendations
        _PREFER = {"prefer", "use", "always", "should", "recommend"}
        _AVOID = {"avoid", "never", "don't", "stop", "skip"}

        candidates: list[tuple[MissionLearning, MissionLearning]] = []
        for i, a in enumerate(learnings):
            for b in learnings[i + 1 :]:
                # Must share at least one domain tag or agent
                shared_tags = set(a.domain_tags or []) & set(b.domain_tags or [])
                shared_agents = set(a.agent_names or []) & set(b.agent_names or [])
                if not shared_tags and not shared_agents:
                    continue

                # Check opposing verbs
                a_words = set(a.recommendation.lower().split())
                b_words = set(b.recommendation.lower().split())
                a_prefers = bool(a_words & _PREFER)
                a_avoids = bool(a_words & _AVOID)
                b_prefers = bool(b_words & _PREFER)
                b_avoids = bool(b_words & _AVOID)

                if (a_prefers and b_avoids) or (a_avoids and b_prefers):
                    candidates.append((a, b))

        return candidates


class MissionLearningExtractor:
    """Deterministic extractor: TaskAttempt failures → structured learnings.

    No LLM (P2). Groups failures by (agent_name, failure_tier, domain_tags),
    detects retry strategies, and identifies capability gaps.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._learning_repo = MissionLearningRepository(session)

    async def extract_for_mission(self, mission_id: str) -> list[MissionLearning]:
        """Extract learnings from a mission's execution history.

        Returns list of newly created learnings.
        """
        config = _load_learning_config()
        min_occurrence = config["min_occurrence"]

        # Load all failed attempts with their task execution context
        result = await self._session.execute(
            select(TaskAttempt, TaskExecution)
            .join(TaskExecution, TaskAttempt.task_execution_id == TaskExecution.id)
            .join(ExecutionRecord, TaskExecution.execution_record_id == ExecutionRecord.id)
            .where(ExecutionRecord.mission_id == mission_id)
            .where(TaskAttempt.status == TaskAttemptStatus.FAILED)
            .order_by(desc(TaskAttempt.created_at))
        )
        rows = result.all()

        if not rows:
            return []

        # Group by (agent_name, kind_key)
        groups: dict[str, list[tuple]] = {}
        for attempt, execution in rows:
            tier = attempt.failure_tier or "unknown"
            agent = execution.agent_name or "unknown"
            key = f"{agent}::{tier}"
            groups.setdefault(key, []).append((attempt, execution))

        created: list[MissionLearning] = []

        for key, items in groups.items():
            if len(items) < min_occurrence:
                continue

            agent_name, failure_tier = key.split("::", 1)
            first_attempt, first_execution = items[0]

            # Collect evidence
            attempt_ids = [a.id for a, _ in items]
            execution_ids = list({e.id for _, e in items})
            domain_tags = list({t for _, e in items for t in (e.domain_tags or [])})

            # Check for retry strategy: same agent+domain succeeded after failures
            has_success = await self._check_success_after_failures(
                mission_id,
                agent_name,
                domain_tags,
            )

            kind = (
                LearningKind.RETRY_STRATEGY.value
                if has_success
                else LearningKind.FAILURE_PATTERN.value
            )
            title = f"{agent_name} — {failure_tier} failures ({len(items)}x)"
            body = self._build_body(items)
            recommendation = self._build_recommendation(items, has_success)
            confidence = self._compute_confidence(len(items))

            # Dedup: check for existing learning with same agent + kind
            existing = await self._learning_repo.find_by_agent_and_kind(
                mission_id,
                agent_name,
                kind,
            )
            if existing:
                # Increment occurrence instead of creating duplicate
                await self._learning_repo.increment_occurrence(
                    existing[0].id,
                    new_evidence={
                        "task_attempt_ids": attempt_ids,
                        "execution_ids": execution_ids,
                    },
                )
                logger.debug(
                    "Learning dedup: incremented occurrence",
                    extra={
                        "learning_id": existing[0].id,
                        "new_count": existing[0].occurrence_count + 1,
                    },
                )
                continue

            learning = await self._learning_repo.create(
                mission_id=mission_id,
                kind=kind,
                title=title,
                body=body,
                recommendation=recommendation,
                evidence={
                    "task_attempt_ids": attempt_ids,
                    "execution_ids": execution_ids,
                    "failure_tiers": [failure_tier],
                },
                domain_tags=domain_tags,
                agent_names=[agent_name],
                confidence=confidence,
                occurrence_count=len(items),
            )
            created.append(learning)
            logger.info(
                "Learning extracted",
                extra={
                    "learning_id": learning.id,
                    "kind": kind,
                    "agent": agent_name,
                    "occurrences": len(items),
                },
            )

        return created

    async def _check_success_after_failures(
        self,
        mission_id: str,
        agent_name: str,
        domain_tags: list[str],
    ) -> bool:
        """Check if this agent succeeded in any execution with overlapping tags."""
        result = await self._session.execute(
            select(func.count())
            .select_from(TaskExecution)
            .join(ExecutionRecord, TaskExecution.execution_record_id == ExecutionRecord.id)
            .where(
                and_(
                    ExecutionRecord.mission_id == mission_id,
                    TaskExecution.agent_name == agent_name,
                    TaskExecution.status == "completed",
                )
            )
        )
        return (result.scalar_one() or 0) > 0

    @staticmethod
    def _build_body(items: list[tuple]) -> str:
        """Build learning body from failure items."""
        reasons: list[str] = []
        for attempt, execution in items[:5]:
            reason = attempt.failure_reason or "No reason recorded"
            reasons.append(f"- {execution.task_id}: {reason[:200]}")
        if len(items) > 5:
            reasons.append(f"  ... and {len(items) - 5} more failures")
        return "\n".join(reasons)

    @staticmethod
    def _build_recommendation(items: list[tuple], has_success: bool) -> str:
        """Build recommendation from failure + success pattern."""
        if has_success:
            # Find what feedback led to success
            for attempt, execution in items:
                if attempt.feedback_provided:
                    return f"Retry with feedback: {attempt.feedback_provided[:300]}"
            return "Agent eventually succeeded — review the successful attempt for the working approach."
        return "Recurring failure pattern — consider a different agent or approach."

    @staticmethod
    def _compute_confidence(occurrence_count: int) -> float:
        """Confidence = min(0.95, 0.3 + 0.15 * count)."""
        return min(0.95, 0.3 + 0.15 * occurrence_count)
