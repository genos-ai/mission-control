"""
Prompt Version Repository.

Data access for prompt version history. Handles version number
auto-increment and filtered lookups by entity.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.prompt_version import PromptVersion
from modules.backend.repositories.base import BaseRepository


class PromptVersionRepository(BaseRepository[PromptVersion]):
    """Repository for prompt_versions table."""

    model = PromptVersion

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_versions(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 50,
    ) -> list[PromptVersion]:
        """List version history for an entity, newest first."""
        result = await self.session.execute(
            select(PromptVersion)
            .where(
                PromptVersion.entity_type == entity_type,
                PromptVersion.entity_id == entity_id,
            )
            .order_by(PromptVersion.version.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest(
        self,
        entity_type: str,
        entity_id: str,
    ) -> PromptVersion | None:
        """Get the most recent version for an entity."""
        result = await self.session.execute(
            select(PromptVersion)
            .where(
                PromptVersion.entity_type == entity_type,
                PromptVersion.entity_id == entity_id,
            )
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _next_version(self, entity_type: str, entity_id: str) -> int:
        """Compute the next version number for an entity."""
        result = await self.session.execute(
            select(func.max(PromptVersion.version)).where(
                PromptVersion.entity_type == entity_type,
                PromptVersion.entity_id == entity_id,
            )
        )
        current_max = result.scalar_one_or_none()
        return (current_max or 0) + 1

    async def create_version(
        self,
        entity_type: str,
        entity_id: str,
        prompt_type: str,
        content: str,
        changed_by: str,
        change_reason: str | None = None,
    ) -> PromptVersion:
        """Create a new prompt version with auto-incremented version number."""
        next_ver = await self._next_version(entity_type, entity_id)
        return await self.create(
            entity_type=entity_type,
            entity_id=entity_id,
            prompt_type=prompt_type,
            content=content,
            version=next_ver,
            changed_by=changed_by,
            change_reason=change_reason,
        )
