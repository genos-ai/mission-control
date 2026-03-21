"""
Mission Team Service.

Business logic for assembling and managing per-mission agent teams.
Handles adding/removing agents, updating user prompts with version
tracking, and listing team composition with catalog detail.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.models.mission_team import MissionTeamMember
from modules.backend.repositories.agent_catalog import AgentCatalogRepository
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_team import MissionTeamRepository
from modules.backend.repositories.prompt_version import PromptVersionRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class MissionTeamService(BaseService):
    """Service for per-mission agent team management."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._team_repo = MissionTeamRepository(session)
        self._catalog_repo = AgentCatalogRepository(session)
        self._mission_repo = MissionRepository(session)
        self._prompt_repo = PromptVersionRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["MissionTeamService", None]:
        """Create a MissionTeamService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield MissionTeamService(db)
            await db.commit()

    async def add_agent(
        self,
        mission_id: str,
        agent_catalog_id: str,
        *,
        user_prompt: str | None = None,
        display_order: int = 0,
        custom_constraints: dict | None = None,
    ) -> MissionTeamMember:
        """Add an agent from the catalog to a mission's team."""
        await self._mission_repo.get_by_id(mission_id)
        await self._catalog_repo.get_by_id(agent_catalog_id)

        existing = await self._team_repo.get_by_mission_and_agent(
            mission_id, agent_catalog_id,
        )
        if existing:
            raise ConflictError(
                "Agent is already on this mission's team"
            )

        member = await self._team_repo.create(
            mission_id=mission_id,
            agent_catalog_id=agent_catalog_id,
            user_prompt=user_prompt,
            display_order=display_order,
            custom_constraints=custom_constraints,
        )

        if user_prompt:
            await self._prompt_repo.create_version(
                entity_type="mission_team_member",
                entity_id=member.id,
                prompt_type="user",
                content=user_prompt,
                changed_by="system",
                change_reason="Initial assignment",
            )

        self._log_operation(
            "Agent added to mission team",
            mission_id=mission_id,
            agent_catalog_id=agent_catalog_id,
        )
        return member

    async def remove_agent(self, member_id: str) -> None:
        """Remove an agent from a mission's team."""
        await self._team_repo.delete(member_id)
        self._log_operation("Agent removed from mission team", member_id=member_id)

    async def update_user_prompt(
        self,
        member_id: str,
        content: str,
        changed_by: str,
        change_reason: str | None = None,
    ) -> MissionTeamMember:
        """Update a team member's user prompt and create a version record."""
        member = await self._team_repo.update_user_prompt(member_id, content)

        await self._prompt_repo.create_version(
            entity_type="mission_team_member",
            entity_id=member_id,
            prompt_type="user",
            content=content,
            changed_by=changed_by,
            change_reason=change_reason,
        )

        self._log_operation(
            "User prompt updated",
            member_id=member_id,
            changed_by=changed_by,
            version=member.user_prompt_version,
        )
        return member

    async def list_team(
        self,
        mission_id: str,
        enabled_only: bool = True,
    ) -> list[MissionTeamMember]:
        """List team members for a mission."""
        return await self._team_repo.list_by_mission(
            mission_id, enabled_only=enabled_only,
        )

    async def get_member(self, member_id: str) -> MissionTeamMember:
        """Get a specific team member. Raises NotFoundError."""
        member = await self._team_repo.get_by_id_or_none(member_id)
        if not member:
            raise NotFoundError(f"Team member '{member_id}' not found")
        return member

    async def toggle_enabled(
        self,
        member_id: str,
        enabled: bool,
    ) -> MissionTeamMember:
        """Enable or disable a team member."""
        return await self._team_repo.update(member_id, enabled=enabled)
