"""
Mission Run Repository (Plan 88, contract 3.5.2).

Data access for mission_runs. Every by-id load is mission-scoped; the service
raises NotFoundError on None. Status rules live in MissionRun.transition_status
and the services, not here.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from modules.backend.models.mission_run import (
    ACTIVE_RUN_STATUSES,
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_run_digest import MissionRunDigest
from modules.backend.repositories.base import BaseRepository


class MissionRunRepository(BaseRepository[MissionRun]):
    """Repository for MissionRun rows."""

    model = MissionRun

    async def get_for_mission(self, mission_id: str, run_id: str) -> MissionRun | None:
        """The run with this id, only if it belongs to the mission."""
        stmt = select(MissionRun).where(
            MissionRun.id == run_id, MissionRun.mission_id == mission_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def lock_for_mission(self, mission_id: str, run_id: str) -> MissionRun | None:
        """As get_for_mission, holding a row lock until the transaction ends."""
        stmt = (
            select(MissionRun)
            .where(MissionRun.id == run_id, MissionRun.mission_id == mission_id)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def lock_current(self, mission_id: str, run_id: str) -> MissionRun | None:
        """As lock_for_mission, reloading the row so a status read under the lock is current."""
        stmt = (
            select(MissionRun)
            .where(MissionRun.id == run_id, MissionRun.mission_id == mission_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_active_for_mission(self, mission_id: str) -> MissionRun | None:
        """The mission's non-terminal run; uq_mission_runs_one_active allows at most one."""
        stmt = select(MissionRun).where(
            MissionRun.mission_id == mission_id,
            MissionRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_latest_with_digest(self, mission_id: str) -> MissionRun | None:
        """The highest-sequence run of the mission that has a digest."""
        stmt = (
            select(MissionRun)
            .join(MissionRunDigest, MissionRunDigest.mission_run_id == MissionRun.id)
            .where(MissionRun.mission_id == mission_id)
            .order_by(MissionRun.sequence.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_sequence(self, mission_id: str, seq: int) -> MissionRun | None:
        """The run with this per-mission sequence number."""
        stmt = select(MissionRun).where(
            MissionRun.mission_id == mission_id, MissionRun.sequence == seq
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_slot(self, schedule_id: str, scheduled_for: datetime) -> MissionRun | None:
        """The run that claimed this schedule slot."""
        stmt = select(MissionRun).where(
            MissionRun.schedule_id == schedule_id,
            MissionRun.scheduled_for == scheduled_for,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert_occurrence(
        self,
        *,
        id: str,
        mission_id: str,
        plan_id: str,
        schedule_id: str,
        sequence: int,
        scheduled_for: datetime,
        status: MissionRunStatus,
        status_reason: MissionRunStatusReason | None,
        status_detail: str | None,
        objective: str | None,
        workflow_definition_id: str | None,
        workflow_parameters: dict,
        temporal_workflow_id: str | None,
        config_snapshot: dict,
    ) -> MissionRun | None:
        """Insert the run for a schedule slot; None when the slot is already claimed.

        ON CONFLICT ON CONSTRAINT uq_mission_runs_schedule_slot DO NOTHING RETURNING *.
        Any other conflict (one active run, workflow id) raises.
        """
        stmt = (
            pg_insert(MissionRun)
            .values(
                id=id,
                mission_id=mission_id,
                plan_id=plan_id,
                schedule_id=schedule_id,
                sequence=sequence,
                trigger=MissionRunTrigger.SCHEDULE,
                scheduled_for=scheduled_for,
                status=status,
                status_reason=status_reason,
                status_detail=status_detail,
                objective=objective,
                workflow_definition_id=workflow_definition_id,
                workflow_parameters=workflow_parameters,
                temporal_workflow_id=temporal_workflow_id,
                config_snapshot=config_snapshot,
            )
            .on_conflict_do_nothing(constraint="uq_mission_runs_schedule_slot")
            .returning(MissionRun)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active_older_than(self, cutoff: datetime) -> list[MissionRun]:
        """Non-terminal runs not updated since cutoff (reconciler input)."""
        stmt = select(MissionRun).where(
            MissionRun.status.in_(ACTIVE_RUN_STATUSES),
            MissionRun.updated_at < cutoff,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def lock_stale(
        self, run_id: str, status: MissionRunStatus, cutoff: datetime
    ) -> MissionRun | None:
        """Lock the run if it is still in ``status`` and not updated since cutoff.

        SKIP LOCKED: a row another transaction holds, or one that progressed,
        returns None (reconciler write re-select).
        """
        stmt = (
            select(MissionRun)
            .where(
                MissionRun.id == run_id,
                MissionRun.status == status,
                MissionRun.updated_at < cutoff,
            )
            .execution_options(populate_existing=True)
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        statuses: list[MissionRunStatus] | None,
        limit: int,
        before_sequence: int | None,
    ) -> list[MissionRun]:
        """The mission's runs, newest sequence first, keyset-paginated by sequence."""
        stmt = select(MissionRun).where(MissionRun.mission_id == mission_id)
        if statuses:
            stmt = stmt.where(MissionRun.status.in_(statuses))
        if before_sequence is not None:
            stmt = stmt.where(MissionRun.sequence < before_sequence)
        stmt = stmt.order_by(MissionRun.sequence.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
