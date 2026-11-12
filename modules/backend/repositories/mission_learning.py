"""
Mission Learning Repository.

Data access for the mission_learnings table. Structured queries only —
all vector operations go through EmbeddingRepository.
"""

from collections.abc import Callable

from sqlalchemy import and_, desc, func, select, update

from modules.backend.core.utils import utc_now
from modules.backend.models.mission_learning import LearningKind, LearningStatus, MissionLearning
from modules.backend.repositories.base import BaseRepository

_FAILURE_KINDS = (LearningKind.FAILURE_PATTERN.value, LearningKind.RETRY_STRATEGY.value)
_EVIDENCE_ID_KEYS = ("task_attempt_ids", "execution_ids", "failure_tiers", "artifact_ids")


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

    async def find_failure_learning(
        self,
        mission_id: str,
        agent_name: str,
        failure_tier: str,
    ) -> MissionLearning | None:
        """Find the active failure learning for one (agent, failure tier) group.

        Matches FAILURE_PATTERN and RETRY_STRATEGY so a kind flip updates the
        existing row instead of creating a duplicate. agent_names and
        evidence.failure_tiers are post-filtered in Python for JSON compat.
        Newest updated_at first; returns the first match or None.
        """
        result = await self.session.execute(
            select(MissionLearning)
            .where(
                and_(
                    MissionLearning.mission_id == mission_id,
                    MissionLearning.status == LearningStatus.ACTIVE.value,
                    MissionLearning.kind.in_(_FAILURE_KINDS),
                )
            )
            .order_by(desc(MissionLearning.updated_at))
        )
        for row in result.scalars().all():
            if agent_name not in (row.agent_names or []):
                continue
            if failure_tier in (row.evidence or {}).get("failure_tiers", []):
                return row
        return None

    async def merge_evidence(
        self,
        learning_id: str,
        new_evidence: dict,
        *,
        kind: str,
        confidence_fn: Callable[[int], float],
        title_fn: Callable[[int], str],
    ) -> int:
        """Union new evidence into a learning and re-derive its count-based fields.

        occurrence_count is len(evidence["task_attempt_ids"]), so merging the
        same evidence twice is a no-op. updated_at moves only when evidence,
        kind, confidence or title actually changed. Returns occurrence_count.
        """
        learning = await self.get_by_id(learning_id)

        existing = learning.evidence or {}
        merged = dict(existing)
        for key in _EVIDENCE_ID_KEYS:
            new_ids = new_evidence.get(key, [])
            if new_ids:
                merged[key] = list(dict.fromkeys(existing.get(key, []) + new_ids))

        count = len(merged.get("task_attempt_ids", []))
        confidence = confidence_fn(count)
        title = title_fn(count)

        changed = (
            merged != existing
            or learning.kind != kind
            or learning.confidence != confidence
            or learning.title != title
            or learning.occurrence_count != count
        )
        if changed:
            learning.evidence = merged
            learning.kind = kind
            learning.confidence = confidence
            learning.title = title
            learning.occurrence_count = count
            learning.updated_at = utc_now()
            await self.session.flush()
        return count

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
