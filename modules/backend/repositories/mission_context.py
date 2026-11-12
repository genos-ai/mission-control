"""
Mission Context Repository.

Data access for MCD and context change audit trail.
"""

from datetime import datetime

from sqlalchemy import func, select, update

from modules.backend.models.mission_context import ContextChange, ContextMilestone, MissionContext
from modules.backend.repositories.base import BaseRepository


class MissionContextRepository(BaseRepository[MissionContext]):
    """Repository for MissionContext CRUD."""

    model = MissionContext

    async def get_by_mission_id(self, mission_id: str) -> MissionContext | None:
        """Get MCD by mission ID."""
        result = await self.session.execute(
            select(MissionContext).where(MissionContext.mission_id == mission_id)
        )
        return result.scalar_one_or_none()

    async def get_by_mission_id_for_update(self, mission_id: str) -> MissionContext | None:
        """Get MCD by mission ID with a row lock held until the caller commits.

        populate_existing refreshes an instance already in the identity map, so
        the locked row's current version is what the caller sees.
        """
        result = await self.session.execute(
            select(MissionContext)
            .where(MissionContext.mission_id == mission_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_version(self, mission_id: str) -> int:
        """Current MCD version for the mission; 0 when no MCD exists."""
        result = await self.session.execute(
            select(MissionContext.version).where(MissionContext.mission_id == mission_id)
        )
        version = result.scalar_one_or_none()
        return version if version is not None else 0

    async def update_context(
        self,
        mission_id: str,
        context_data: dict,
        new_version: int,
        size_characters: int,
        size_tokens: int,
    ) -> int:
        """Atomically update MCD with optimistic concurrency.

        Returns number of rows updated (0 if version conflict).
        """
        result = await self.session.execute(
            update(MissionContext)
            .where(MissionContext.mission_id == mission_id)
            .where(MissionContext.version == new_version - 1)
            .values(
                context_data=context_data,
                version=new_version,
                size_characters=size_characters,
                size_tokens=size_tokens,
            )
        )
        return result.rowcount


class ContextChangeRepository(BaseRepository[ContextChange]):
    """Repository for context change audit trail."""

    model = ContextChange

    async def list_by_context(
        self,
        context_id: str,
        limit: int = 50,
    ) -> list[ContextChange]:
        """List recent changes for a MCD."""
        result = await self.session.execute(
            select(ContextChange)
            .where(ContextChange.context_id == context_id)
            .order_by(ContextChange.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_between(
        self,
        context_id: str,
        after_version: int,
        up_to_version: int,
        limit: int,
    ) -> list[ContextChange]:
        """Changes with after_version < version <= up_to_version, newest first.

        Filters on context_id, never mission_id: legacy rows have mission_id NULL.
        When truncated by limit, the newest changes are kept.
        """
        result = await self.session.execute(
            select(ContextChange)
            .where(ContextChange.context_id == context_id)
            .where(ContextChange.version > after_version)
            .where(ContextChange.version <= up_to_version)
            .order_by(ContextChange.version.desc(), ContextChange.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_between(self, context_id: str, after_version: int, up_to_version: int) -> int:
        """Count of changes with the same predicate as list_between."""
        result = await self.session.execute(
            select(func.count())
            .select_from(ContextChange)
            .where(ContextChange.context_id == context_id)
            .where(ContextChange.version > after_version)
            .where(ContextChange.version <= up_to_version)
        )
        return int(result.scalar_one())

    async def latest_change_at_by_root(self, context_id: str) -> dict[str, datetime]:
        """Most recent change time per MCD root key (first segment of path)."""
        root = func.split_part(ContextChange.path, ".", 1).label("root")
        result = await self.session.execute(
            select(root, func.max(ContextChange.created_at))
            .where(ContextChange.context_id == context_id)
            .group_by(root)
        )
        return {row[0]: row[1] for row in result.all()}

    async def list_by_agent(
        self,
        context_id: str,
        agent_id: str,
        limit: int = 20,
    ) -> list[ContextChange]:
        """List changes made by a specific agent."""
        result = await self.session.execute(
            select(ContextChange)
            .where(ContextChange.context_id == context_id)
            .where(ContextChange.agent_id == agent_id)
            .order_by(ContextChange.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class ContextMilestoneRepository(BaseRepository[ContextMilestone]):
    """Repository for context milestones."""

    model = ContextMilestone

    async def list_by_mission(
        self,
        mission_id: str,
        limit: int = 50,
    ) -> list[ContextMilestone]:
        """List milestones for a mission, newest first."""
        result = await self.session.execute(
            select(ContextMilestone)
            .where(ContextMilestone.mission_id == mission_id)
            .order_by(ContextMilestone.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
