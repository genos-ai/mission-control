"""
Mission Repository.

Data access for missions and mission membership.
"""

from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import selectinload

from modules.backend.core.exceptions import NotFoundError
from modules.backend.models.mission import Mission, MissionMember, MissionStatus, MissionTier
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.repositories.base import BaseRepository


class MissionRepository(BaseRepository[Mission]):
    """Repository for Mission CRUD and queries."""

    model = Mission

    async def get_by_id(self, id: str | UUID) -> Mission:
        """Get a mission with its members loaded.

        Access checks read `mission.members`, and a lazy load on an async session
        raises MissingGreenlet, so a member who is not the owner would get a 500.
        """
        result = await self.session.execute(
            select(Mission).options(selectinload(Mission.members)).where(Mission.id == str(id))
        )
        mission = result.scalar_one_or_none()
        if mission is None:
            raise NotFoundError("Mission not found")
        return mission

    async def lock(self, mission_id: str) -> Mission:
        """SELECT ... FOR UPDATE on the mission row, overwriting any stale loaded copy."""
        stmt = (
            select(Mission)
            .where(Mission.id == str(mission_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        mission = (await self.session.execute(stmt)).scalar_one_or_none()
        if mission is None:
            raise NotFoundError("Mission not found")
        return mission

    async def list_ids_by_status_and_gate_mode(
        self, status: MissionStatus, gate_mode: GateMode
    ) -> list[str]:
        """Ids of the missions in ``status`` whose plan runs in ``gate_mode``."""
        stmt = (
            select(Mission.id)
            .join(MissionPlan, MissionPlan.mission_id == Mission.id)
            .where(Mission.status == status, MissionPlan.gate_mode == gate_mode)
            .order_by(Mission.created_at)
        )
        return [str(i) for i in (await self.session.execute(stmt)).scalars().all()]

    async def increment_run_sequence(self, mission_id: str) -> int:
        """Issue the mission's next run sequence number.

        The UPDATE's row lock makes this race-free. The increment rolls back with
        the transaction or savepoint that contains it, so sequences stay gap-free.
        """
        stmt = (
            update(Mission)
            .where(Mission.id == mission_id)
            .values(run_sequence_counter=Mission.run_sequence_counter + 1)
            .returning(Mission.run_sequence_counter)
        )
        return (await self.session.execute(stmt)).scalar_one()

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
