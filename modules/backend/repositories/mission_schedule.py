"""
Mission Schedule Repository (Plan 88, contract 3.5.2).

Data access for mission_schedules. By-id loads are mission-scoped; the service
raises NotFoundError on None.
"""

from sqlalchemy import func, or_, select

from modules.backend.models.mission_schedule import (
    MissionSchedule,
    MissionScheduleStatus,
    TemporalSyncState,
)
from modules.backend.repositories.base import BaseRepository


class MissionScheduleRepository(BaseRepository[MissionSchedule]):
    """Repository for MissionSchedule rows."""

    model = MissionSchedule

    async def get_for_mission(self, mission_id: str, schedule_id: str) -> MissionSchedule | None:
        """The schedule with this id, only if it belongs to the mission."""
        stmt = select(MissionSchedule).where(
            MissionSchedule.id == schedule_id,
            MissionSchedule.mission_id == mission_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def lock(self, schedule_id: str) -> MissionSchedule | None:
        """SELECT ... FOR UPDATE on the schedule row, overwriting any stale loaded copy."""
        stmt = (
            select(MissionSchedule)
            .where(MissionSchedule.id == schedule_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_mission(
        self, mission_id: str, include_archived: bool
    ) -> list[MissionSchedule]:
        """The mission's schedules, oldest first."""
        stmt = select(MissionSchedule).where(MissionSchedule.mission_id == mission_id)
        if not include_archived:
            stmt = stmt.where(MissionSchedule.status != MissionScheduleStatus.ARCHIVED)
        stmt = stmt.order_by(MissionSchedule.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_syncable(self) -> list[MissionSchedule]:
        """Rows not SYNCED with Temporal, plus every ACTIVE or PAUSED row."""
        stmt = select(MissionSchedule).where(
            or_(
                MissionSchedule.temporal_sync_state != TemporalSyncState.SYNCED,
                MissionSchedule.status.in_(
                    [MissionScheduleStatus.ACTIVE, MissionScheduleStatus.PAUSED]
                ),
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_non_archived(self, mission_id: str) -> int:
        """How many of the mission's schedules are not ARCHIVED."""
        stmt = (
            select(func.count())
            .select_from(MissionSchedule)
            .where(
                MissionSchedule.mission_id == mission_id,
                MissionSchedule.status != MissionScheduleStatus.ARCHIVED,
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def list_temporal_schedule_ids(self) -> set[str]:
        """Every row's temporal_schedule_id, archived rows included (orphan sweep)."""
        stmt = select(MissionSchedule.temporal_schedule_id)
        return set((await self.session.execute(stmt)).scalars().all())
