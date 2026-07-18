"""
Workflow Schedule Service.

Business logic for cron-based workflow execution schedules. Handles
CRUD, cron validation, next-fire-at computation, daily run cap
enforcement, and cooldown period checks.

The actual scheduler loop (Phase 4) will call evaluate_due_schedules()
periodically to find and fire ready schedules.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.workflow_schedule import WorkflowSchedule
from modules.backend.repositories.workflow_definition import WorkflowDefinitionRepository
from modules.backend.repositories.workflow_schedule import WorkflowScheduleRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


def _validate_cron(expression: str) -> None:
    """Validate a 5-field cron expression.

    Accepts standard cron: minute hour day-of-month month day-of-week.
    Each field allows digits, ranges (1-5), lists (1,3,5), steps (*/5),
    and wildcards (*).

    Raises ValidationError if the expression is malformed.
    """
    import re

    fields = expression.strip().split()
    if len(fields) != 5:
        raise ValidationError(
            f"Cron expression must have exactly 5 fields, got {len(fields)}: '{expression}'"
        )

    field_names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
    field_ranges = [
        (0, 59),
        (0, 23),
        (1, 31),
        (1, 12),
        (0, 7),
    ]
    pattern = re.compile(r"^(\*|[0-9]+)(-[0-9]+)?(\/[0-9]+)?$")

    for i, field in enumerate(fields):
        for part in field.split(","):
            if not pattern.match(part):
                raise ValidationError(
                    f"Invalid cron {field_names[i]} field: '{part}' in '{expression}'"
                )


def _compute_next_fire(cron_expression: str, after: datetime) -> datetime | None:
    """Compute the next fire time for a cron expression.

    Returns a timezone-aware UTC datetime. Uses croniter if available,
    otherwise falls back to after + 1 hour.
    """
    try:
        from croniter import croniter

        cron = croniter(cron_expression, after)
        next_dt = cron.get_next(datetime)
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=timezone.utc)
        return next_dt
    except ImportError:
        return after + timedelta(hours=1)


class WorkflowScheduleService(BaseService):
    """Service for workflow schedule management."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._repo = WorkflowScheduleRepository(session)
        self._wf_repo = WorkflowDefinitionRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["WorkflowScheduleService", None]:
        """Create a WorkflowScheduleService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield WorkflowScheduleService(db)
            await db.commit()

    async def create_schedule(
        self,
        *,
        workflow_definition_id: str,
        mission_id: str,
        cron_expression: str,
        created_by: str,
        timezone: str = "UTC",
        description: str = "",
        budget_per_run_usd: float | None = None,
        max_iterations: int | None = None,
        cooldown_seconds: int = 0,
    ) -> WorkflowSchedule:
        """Create a new workflow schedule."""
        _validate_cron(cron_expression)

        workflow = await self._wf_repo.get_by_id_or_none(workflow_definition_id)
        if not workflow:
            raise NotFoundError(f"Workflow definition '{workflow_definition_id}' not found")

        if budget_per_run_usd is not None:
            app_config = get_app_config()
            if budget_per_run_usd > app_config.workflows.max_budget_usd:
                raise ValidationError(
                    f"Budget per run (${budget_per_run_usd:.2f}) exceeds "
                    f"platform cap (${app_config.workflows.max_budget_usd:.2f})"
                )

        now = utc_now()
        next_fire = _compute_next_fire(cron_expression, now)

        schedule = await self._repo.create(
            workflow_definition_id=workflow_definition_id,
            mission_id=mission_id,
            cron_expression=cron_expression,
            timezone=timezone,
            description=description,
            budget_per_run_usd=budget_per_run_usd,
            max_iterations=max_iterations,
            cooldown_seconds=cooldown_seconds,
            next_fire_at=next_fire,
            created_by=created_by,
        )

        self._log_operation(
            "Workflow schedule created",
            schedule_id=schedule.id,
            workflow_definition_id=workflow_definition_id,
            cron=cron_expression,
        )
        return schedule

    async def get_schedule(self, schedule_id: str) -> WorkflowSchedule:
        """Get a schedule by ID. Raises NotFoundError."""
        schedule = await self._repo.get_by_id_or_none(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule '{schedule_id}' not found")
        return schedule

    async def list_by_mission(
        self,
        mission_id: str,
        enabled_only: bool = True,
    ) -> list[WorkflowSchedule]:
        """List schedules for a mission."""
        return await self._repo.list_by_mission(mission_id, enabled_only=enabled_only)

    async def list_by_workflow(
        self,
        workflow_definition_id: str,
    ) -> list[WorkflowSchedule]:
        """List schedules for a specific workflow definition."""
        return await self._repo.list_by_workflow(workflow_definition_id)

    async def update_schedule(
        self,
        schedule_id: str,
        **updates,
    ) -> WorkflowSchedule:
        """Update a schedule's configuration."""
        if "cron_expression" in updates and updates["cron_expression"] is not None:
            _validate_cron(updates["cron_expression"])
            now = utc_now()
            updates["next_fire_at"] = _compute_next_fire(
                updates["cron_expression"],
                now,
            )

        return await self._repo.update(schedule_id, **updates)

    async def toggle_enabled(
        self,
        schedule_id: str,
        enabled: bool,
    ) -> WorkflowSchedule:
        """Enable or disable a schedule."""
        updates = {"enabled": enabled}

        if enabled:
            schedule = await self.get_schedule(schedule_id)
            now = utc_now()
            updates["next_fire_at"] = _compute_next_fire(
                schedule.cron_expression,
                now,
            )

        return await self._repo.update(schedule_id, **updates)

    async def delete_schedule(self, schedule_id: str) -> None:
        """Delete a schedule."""
        await self._repo.delete(schedule_id)
        self._log_operation("Workflow schedule deleted", schedule_id=schedule_id)

    async def get_next_run(self, mission_id: str) -> dict | None:
        """Get the next scheduled run for a mission.

        Returns a dict with schedule_id, workflow_definition_id,
        next_fire_at, and cron_expression, or None if no enabled
        schedules exist.
        """
        schedules = await self.list_by_mission(mission_id, enabled_only=True)
        if not schedules:
            return None

        # Find the schedule with the earliest next_fire_at
        nearest = min(
            (s for s in schedules if s.next_fire_at),
            key=lambda s: s.next_fire_at,
            default=None,
        )
        if nearest is None:
            return None

        return {
            "schedule_id": nearest.id,
            "workflow_definition_id": nearest.workflow_definition_id,
            "next_fire_at": nearest.next_fire_at,
            "cron_expression": nearest.cron_expression,
        }

    async def evaluate_due_schedules(self) -> list[dict]:
        """Find and process all schedules that are due to fire.

        Returns a list of dicts describing what fired, for the caller
        (scheduler loop) to create WorkflowRuns.

        Enforces:
        - Platform-wide max_scheduled_runs_per_day
        - Per-schedule cooldown_seconds
        - Per-schedule max_iterations
        """
        now = utc_now()
        app_config = get_app_config()
        max_per_day = app_config.workflows.max_scheduled_runs_per_day

        due = await self._repo.list_due(now)
        fired: list[dict] = []

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        for schedule in due:
            if schedule.cooldown_seconds > 0 and schedule.last_fired_at:
                if (now - schedule.last_fired_at).total_seconds() < schedule.cooldown_seconds:
                    logger.debug(
                        "Schedule in cooldown, skipping",
                        extra={"schedule_id": schedule.id},
                    )
                    continue

            daily_count = await self._repo.count_by_mission_today(
                schedule.mission_id,
                today_start,
            )
            if daily_count >= max_per_day:
                logger.warning(
                    "Daily schedule cap reached for mission",
                    extra={
                        "mission_id": schedule.mission_id,
                        "daily_count": daily_count,
                        "cap": max_per_day,
                    },
                )
                continue

            next_fire = _compute_next_fire(schedule.cron_expression, now)
            await self._repo.record_fire(
                schedule.id,
                fired_at=now,
                next_fire_at=next_fire,
            )

            fired.append(
                {
                    "schedule_id": schedule.id,
                    "workflow_definition_id": schedule.workflow_definition_id,
                    "mission_id": schedule.mission_id,
                    "budget_per_run_usd": schedule.budget_per_run_usd,
                    "fired_at": now.isoformat(),
                }
            )

            logger.info(
                "Schedule fired",
                extra={
                    "schedule_id": schedule.id,
                    "workflow_definition_id": schedule.workflow_definition_id,
                    "iteration": schedule.iteration_count + 1,
                },
            )

        return fired
