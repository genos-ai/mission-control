"""
Agent Catalog Repository.

Data access for the global agent registry. Provides filtered listing,
keyword search, and name-based lookups.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.agent_catalog import AgentCatalog
from modules.backend.repositories.base import BaseRepository


class AgentCatalogRepository(BaseRepository[AgentCatalog]):
    """Repository for agent_catalog table."""

    model = AgentCatalog

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_name(self, agent_name: str) -> AgentCatalog | None:
        """Get an agent by its unique name."""
        result = await self.session.execute(
            select(AgentCatalog).where(AgentCatalog.agent_name == agent_name)
        )
        return result.scalar_one_or_none()

    async def list_enabled(
        self,
        visibility: str | None = None,
        limit: int = 200,
    ) -> list[AgentCatalog]:
        """List enabled agents, optionally filtered by visibility."""
        stmt = (
            select(AgentCatalog)
            .where(AgentCatalog.enabled.is_(True))
            .order_by(AgentCatalog.agent_name)
            .limit(limit)
        )
        if visibility:
            stmt = stmt.where(AgentCatalog.visibility == visibility)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_type(
        self,
        agent_type: str,
        enabled_only: bool = True,
    ) -> list[AgentCatalog]:
        """List agents filtered by type (vertical, horizontal, system)."""
        stmt = (
            select(AgentCatalog)
            .where(AgentCatalog.agent_type == agent_type)
            .order_by(AgentCatalog.agent_name)
        )
        if enabled_only:
            stmt = stmt.where(AgentCatalog.enabled.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_by_keyword(self, text: str) -> list[AgentCatalog]:
        """Find agents whose keywords overlap with the search text.

        Loads all enabled agents and filters in Python since keywords
        are stored as JSON arrays (no efficient SQL LIKE on JSON arrays
        across both PostgreSQL and SQLite).
        """
        all_enabled = await self.list_enabled()
        text_lower = text.lower()
        return [
            agent
            for agent in all_enabled
            if any(kw.lower() in text_lower for kw in (agent.keywords or []))
        ]

    async def is_empty(self) -> bool:
        """Check if the catalog has any entries (for seeding logic)."""
        return await self.count() == 0
