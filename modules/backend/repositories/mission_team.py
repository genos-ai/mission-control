"""
Mission Team Repository.

Data access for per-mission agent team composition.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from modules.backend.models.mission_team import MissionTeamMember
from modules.backend.repositories.base import BaseRepository


class MissionTeamRepository(BaseRepository[MissionTeamMember]):
    """Repository for mission_team_members table."""

    model = MissionTeamMember

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_mission(
        self,
        mission_id: str,
        enabled_only: bool = True,
    ) -> list[MissionTeamMember]:
        """List team members for a mission with catalog data, ordered by display_order."""
        stmt = (
            select(MissionTeamMember)
            .options(joinedload(MissionTeamMember.agent_catalog))
            .where(MissionTeamMember.mission_id == mission_id)
            .order_by(MissionTeamMember.display_order)
        )
        if enabled_only:
            stmt = stmt.where(MissionTeamMember.enabled.is_(True))
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())

    async def get_by_mission_and_agent(
        self,
        mission_id: str,
        agent_catalog_id: str,
    ) -> MissionTeamMember | None:
        """Get a specific team member by mission + agent catalog entry."""
        result = await self.session.execute(
            select(MissionTeamMember).where(
                MissionTeamMember.mission_id == mission_id,
                MissionTeamMember.agent_catalog_id == agent_catalog_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_user_prompt(
        self,
        member_id: str,
        content: str,
    ) -> MissionTeamMember:
        """Update the user prompt and increment the version counter."""
        member = await self.get_by_id(member_id)
        member.user_prompt = content
        member.user_prompt_version += 1
        await self.session.flush()
        await self.session.refresh(member)
        return member
