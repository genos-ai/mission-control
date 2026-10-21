"""
Mission Repository.

Data access for missions and mission membership.
"""

from sqlalchemy import or_, select

from modules.backend.models.mission import Mission, MissionMember, MissionStatus, MissionTier
from modules.backend.repositories.base import BaseRepository


class MissionRepository(BaseRepository[Mission]):
    """Repository for Mission CRUD and queries."""

    model = Mission

    async def get_by_name(self, name: str) -> Mission | None:
        """Get a mission by unique name."""
        result = await self.session.execute(select(Mission).where(Mission.name == name))
        return result.scalar_one_or_none()

    async def list_by_owner(
        self,
        owner_id: str,
        status: MissionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Mission]:
        """List missions owned by a user, optionally filtered by status."""
        query = select(Mission).where(Mission.owner_id == owner_id)
        if status:
            query = query.where(Mission.status == status)
        query = query.order_by(Mission.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_open_for_user(self, user_id: str | None) -> list[Mission]:
        """Missions that are not archived and that a user may see.

        A user sees the missions they own or are a member of, never platform missions.
        `None` means an admin: every non-archived mission, platform ones included.
        """
        query = select(Mission).where(Mission.status != MissionStatus.ARCHIVED)
        if user_id is not None:
            member_of = select(MissionMember.mission_id).where(MissionMember.user_id == user_id)
            query = query.where(
                or_(Mission.owner_id == user_id, Mission.id.in_(member_of)),
                Mission.tier != MissionTier.platform,
            )
        result = await self.session.execute(query.order_by(Mission.name))
        return list(result.scalars().all())

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Mission]:
        """List all missions regardless of status."""
        result = await self.session.execute(
            select(Mission).order_by(Mission.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())


class MissionMemberRepository(BaseRepository[MissionMember]):
    """Repository for mission membership queries."""

    model = MissionMember

    async def get_members(
        self,
        mission_id: str,
    ) -> list[MissionMember]:
        """Get all members of a mission."""
        result = await self.session.execute(
            select(MissionMember)
            .where(MissionMember.mission_id == mission_id)
            .order_by(MissionMember.created_at)
        )
        return list(result.scalars().all())

    async def get_membership(
        self,
        mission_id: str,
        user_id: str,
    ) -> MissionMember | None:
        """Get a specific user's membership in a mission."""
        result = await self.session.execute(
            select(MissionMember)
            .where(MissionMember.mission_id == mission_id)
            .where(MissionMember.user_id == user_id)
        )
        return result.scalar_one_or_none()
