"""
Mission History Repository.

Data access for archived decisions and milestone summaries.
"""

from sqlalchemy import desc, select

from modules.backend.models.mission_history import DecisionStatus, MilestoneSummary, MissionDecision
from modules.backend.repositories.base import BaseRepository


class MissionDecisionRepository(BaseRepository[MissionDecision]):
    """Repository for mission decisions."""

    model = MissionDecision

    async def list_by_domain(
        self,
        mission_id: str,
        domain: str,
        limit: int = 20,
    ) -> list[MissionDecision]:
        """Get active decisions for a domain, most recent first."""
        result = await self.session.execute(
            select(MissionDecision)
            .where(MissionDecision.mission_id == mission_id)
            .where(MissionDecision.domain == domain)
            .where(MissionDecision.status == DecisionStatus.ACTIVE)
            .order_by(desc(MissionDecision.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_active(
        self,
        mission_id: str,
        limit: int = 50,
    ) -> list[MissionDecision]:
        """Get all active decisions for a mission."""
        result = await self.session.execute(
            select(MissionDecision)
            .where(MissionDecision.mission_id == mission_id)
            .where(MissionDecision.status == DecisionStatus.ACTIVE)
            .order_by(desc(MissionDecision.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        mission_id: str | None = None,
        domain: str | None = None,
        limit: int = 20,
    ) -> list[MissionDecision]:
        """List decisions with optional filters (cross-mission admin view)."""
        query = select(MissionDecision)
        if domain:
            query = query.where(MissionDecision.domain == domain)
        if mission_id:
            query = query.where(MissionDecision.mission_id == mission_id)
        query = query.order_by(desc(MissionDecision.created_at)).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())


class MilestoneSummaryRepository(BaseRepository[MilestoneSummary]):
    """Repository for milestone summaries."""

    model = MilestoneSummary

    async def list_by_mission(
        self,
        mission_id: str,
        limit: int = 20,
    ) -> list[MilestoneSummary]:
        """Get milestones for a mission, most recent first."""
        result = await self.session.execute(
            select(MilestoneSummary)
            .where(MilestoneSummary.mission_id == mission_id)
            .order_by(desc(MilestoneSummary.period_end))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        mission_id: str | None = None,
        limit: int = 20,
    ) -> list[MilestoneSummary]:
        """List milestones with optional mission filter (cross-mission admin view)."""
        query = select(MilestoneSummary)
        if mission_id:
            query = query.where(MilestoneSummary.mission_id == mission_id)
        query = query.order_by(desc(MilestoneSummary.period_end)).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())
