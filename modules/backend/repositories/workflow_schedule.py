"""
Workflow Schedule Repository.

Data access for cron-based workflow execution schedules.
Provides queries for the scheduler service (due schedules),
mission-scoped listing, and iteration tracking.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.workflow_schedule import WorkflowSchedule
from modules.backend.repositories.base import BaseRepository


class WorkflowScheduleRepository(BaseRepository[WorkflowSchedule]):
    """Repository for workflow_schedules table."""

    model = WorkflowSchedule

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_mission(
        self,
        mission_id: str,
        enabled_only: bool = True,
    ) -> list[WorkflowSchedule]:
        """List schedules for a mission."""
        stmt = (
            select(WorkflowSchedule)
            .where(WorkflowSchedule.mission_id == mission_id)
            .order_by(WorkflowSchedule.created_at)
        )
        if enabled_only:
            stmt = stmt.where(WorkflowSchedule.enabled.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_workflow(
        self,
        workflow_definition_id: str,
    ) -> list[WorkflowSchedule]:
        """List all schedules for a specific workflow definition."""
        result = await self.session.execute(
            select(WorkflowSchedule)
            .where(WorkflowSchedule.workflow_definition_id == workflow_definition_id)
            .order_by(WorkflowSchedule.created_at)
        )
        return list(result.scalars().all())

    async def list_due(self, current_time: datetime) -> list[WorkflowSchedule]:
        """List enabled schedules whose next_fire_at <= current_time.

        Used by the scheduler service to find schedules that need to fire.
        """
        result = await self.session.execute(
            select(WorkflowSchedule)
            .where(
                WorkflowSchedule.enabled.is_(True),
                WorkflowSchedule.next_fire_at.isnot(None),
                WorkflowSchedule.next_fire_at <= current_time,
            )
            .order_by(WorkflowSchedule.next_fire_at)
        )
        return list(result.scalars().all())

    async def record_fire(
        self,
        schedule_id: str,
        fired_at: datetime,
        next_fire_at: datetime | None,
    ) -> WorkflowSchedule:
        """Record that a schedule has fired and update iteration count.

        Sets last_fired_at, increments iteration_count, and updates
        next_fire_at. If max_iterations is reached, disables the schedule.
        """
        schedule = await self.get_by_id(schedule_id)

        schedule.last_fired_at = fired_at
        schedule.iteration_count += 1
        schedule.next_fire_at = next_fire_at

        if (
            schedule.max_iterations is not None
            and schedule.iteration_count >= schedule.max_iterations
        ):
            schedule.enabled = False

        await self.session.flush()
        await self.session.refresh(schedule)
        return schedule

    async def count_by_mission_today(
        self,
        mission_id: str,
        today_start: datetime,
    ) -> int:
        """Count how many times schedules in a mission have fired today.

        Used for the platform-wide max_scheduled_runs_per_day safety limit.
        """
        result = await self.session.execute(
            select(WorkflowSchedule).where(
                WorkflowSchedule.mission_id == mission_id,
                WorkflowSchedule.last_fired_at.isnot(None),
                WorkflowSchedule.last_fired_at >= today_start,
            )
        )
        return len(list(result.scalars().all()))
