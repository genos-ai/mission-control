"""
Mission Learning Repository.

Data access for the mission_learnings table. Structured queries only —
all vector operations go through EmbeddingRepository.
"""

from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.mission_learning import LearningStatus, MissionLearning
from modules.backend.repositories.base import BaseRepository


class MissionLearningRepository(BaseRepository[MissionLearning]):
    """Repository for mission learnings."""

    model = MissionLearning

    async def list_by_mission(
        self,
        mission_id: str,
        *,
        kind: str | None = None,
        status: str | None = LearningStatus.ACTIVE.value,
        domain_tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MissionLearning]:
        """List learnings for a mission with optional filters.

        Domain tag filtering uses Python post-filter for SQLite
        compatibility (same pattern as HistoryQueryService).
        """
        fetch_limit = limit * 3 if domain_tags else limit
        query = select(MissionLearning).where(MissionLearning.mission_id == mission_id)
        if kind:
            query = query.where(MissionLearning.kind == kind)
        if status:
            query = query.where(MissionLearning.status == status)

        query = (
            query.order_by(
                desc(MissionLearning.confidence),
                desc(MissionLearning.created_at),
            )
            .limit(fetch_limit)
            .offset(offset)
        )

        result = await self.session.execute(query)
        rows = list(result.scalars().all())

        # Post-filter domain tags for SQLite compat
        if domain_tags:
            rows = [
                r for r in rows if r.domain_tags and any(t in r.domain_tags for t in domain_tags)
            ]
            rows = rows[:limit]

        return rows

    async def list_platform_promoted(
        self,
        *,
        kind: str | None = None,
        domain_tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MissionLearning]:
        """List platform-promoted learnings across all missions."""
        fetch_limit = limit * 3 if domain_tags else limit
        query = (
            select(MissionLearning)
            .where(MissionLearning.platform_promoted == True)  # noqa: E712
            .where(MissionLearning.status == LearningStatus.ACTIVE.value)
        )
        if kind:
            query = query.where(MissionLearning.kind == kind)

        query = (
            query.order_by(
                desc(MissionLearning.confidence),
                desc(MissionLearning.created_at),
            )
            .limit(fetch_limit)
            .offset(offset)
        )

        result = await self.session.execute(query)
        rows = list(result.scalars().all())

        if domain_tags:
            rows = [
                r for r in rows if r.domain_tags and any(t in r.domain_tags for t in domain_tags)
            ]
            rows = rows[:limit]

        return rows

    async def count_by_mission(
        self,
        mission_id: str,
        *,
        status: str | None = LearningStatus.ACTIVE.value,
    ) -> int:
        """Count learnings for a mission."""
        query = (
            select(func.count())
            .select_from(MissionLearning)
            .where(MissionLearning.mission_id == mission_id)
        )
        if status:
            query = query.where(MissionLearning.status == status)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def find_by_agent_and_kind(
        self,
        mission_id: str,
        agent_name: str,
        kind: str,
        *,
        status: str = LearningStatus.ACTIVE.value,
    ) -> list[MissionLearning]:
        """Find learnings for a specific agent and kind (for dedup)."""
        result = await self.session.execute(
            select(MissionLearning)
            .where(
                and_(
                    MissionLearning.mission_id == mission_id,
                    MissionLearning.kind == kind,
                    MissionLearning.status == status,
                )
            )
            .order_by(desc(MissionLearning.confidence))
        )
        rows = list(result.scalars().all())
        # Post-filter agent_names for SQLite JSON compat
        return [r for r in rows if agent_name in (r.agent_names or [])]

    async def increment_occurrence(
        self,
        learning_id: str,
        *,
        new_evidence: dict | None = None,
    ) -> int:
        """Increment occurrence_count for an existing learning.

        Optionally merges new evidence IDs into the existing evidence.
        Returns the updated occurrence count.
        """
        learning = await self.get_by_id(learning_id)

        learning.occurrence_count += 1
        learning.updated_at = utc_now()

        # Merge evidence if provided
        if new_evidence:
            existing = learning.evidence or {}
            for key in ("task_attempt_ids", "execution_ids", "failure_tiers", "artifact_ids"):
                new_ids = new_evidence.get(key, [])
                if new_ids:
                    existing_ids = existing.get(key, [])
                    merged = list(dict.fromkeys(existing_ids + new_ids))  # dedup, preserve order
                    existing[key] = merged
            learning.evidence = existing

        await self.session.flush()
        return learning.occurrence_count

    async def promote(
        self,
        learning_id: str,
        promoted_by: str,
    ) -> None:
        """Mark a learning as platform-promoted. Idempotent."""
        await self.session.execute(
            update(MissionLearning)
            .where(MissionLearning.id == learning_id)
            .where(MissionLearning.platform_promoted == False)  # noqa: E712
            .values(
                platform_promoted=True,
                promoted_at=utc_now(),
                promoted_by=promoted_by,
            )
        )

    async def retract(
        self,
        learning_id: str,
    ) -> None:
        """Retract a learning. Idempotent."""
        await self.session.execute(
            update(MissionLearning)
            .where(MissionLearning.id == learning_id)
            .values(status=LearningStatus.RETRACTED.value)
        )
