"""
Mission Intent Repository.

Data access for the append-only mission_intents table.
Current intent = most recent row for a mission_id.
"""

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission_intent import MissionIntent
from modules.backend.repositories.base import BaseRepository


class MissionIntentRepository(BaseRepository[MissionIntent]):
    """Repository for mission intent revisions."""

    model = MissionIntent

    async def get_current(self, mission_id: str) -> MissionIntent | None:
        """Get the most recent intent revision for a mission."""
        result = await self.session.execute(
            select(MissionIntent)
            .where(MissionIntent.mission_id == mission_id)
            .order_by(desc(MissionIntent.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_revisions(
        self,
        mission_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MissionIntent]:
        """List intent revisions for a mission, newest first."""
        result = await self.session.execute(
            select(MissionIntent)
            .where(MissionIntent.mission_id == mission_id)
            .order_by(desc(MissionIntent.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_mission(self, mission_id: str) -> int:
        """Count total revisions for a mission."""
        result = await self.session.execute(
            select(func.count())
            .select_from(MissionIntent)
            .where(MissionIntent.mission_id == mission_id)
        )
        return result.scalar_one()

    async def get_by_mission_and_source(
        self,
        mission_id: str,
        source: str,
        *,
        limit: int = 10,
    ) -> list[MissionIntent]:
        """Get revisions by source type (e.g. all director-inferred intents)."""
        result = await self.session.execute(
            select(MissionIntent)
            .where(MissionIntent.mission_id == mission_id)
            .where(MissionIntent.source == source)
            .order_by(desc(MissionIntent.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())
