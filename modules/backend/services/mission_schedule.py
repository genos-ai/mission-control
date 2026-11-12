"""Mission schedules (Plan 88 step 88.1.6, contracts 3.2.3, 3.3.2 and 3.5.1).

Postgres is the source of truth; each row is mirrored to one Temporal Schedule
through TemporalScheduleGateway. Every transition writes Postgres, commits, then
calls sync_to_temporal. A sync failure is recorded on the row and never raised;
the reconciler retries. claim_occurrence lives in mission_schedule_claim.py.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.service import RPCError

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema_missions import RecurrenceSchema
from modules.backend.core.exceptions import (
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from modules.backend.core.protocols import EventBusProtocol
from modules.backend.core.redaction import redact_secrets
from modules.backend.core.utils import utc_now
from modules.backend.events.base import SessionEvent
from modules.backend.events.mission_run_types import (
    MissionScheduleChangedEvent,
    MissionScheduleSyncFailedEvent,
)
from modules.backend.models.mission import MissionStatus
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.mission_schedule import (
    TEMPORAL_SCHEDULE_ID_PREFIX,
    MissionSchedule,
    MissionScheduleCompletedReason,
    MissionScheduleKind,
    MissionScheduleStatus,
    TemporalSyncState,
)
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_schedule import MissionScheduleRepository
from modules.backend.repositories.workflow_definition import WorkflowDefinitionRepository
from modules.backend.schemas.mission_schedule import (
    MissionScheduleCreate,
    MissionScheduleUpdate,
    OccurrenceClaim,
)
from modules.backend.services.base import BaseService
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_schedule_checks import (
    build_spec,
    build_tick_schedule,
    check_definition,
    check_template,
    check_update_target,
    probe_spec,
    resolve_catch_up,
)
from modules.backend.services.mission_schedule_claim import claim_occurrence
from modules.backend.temporal.config_snapshots import build_tick_config_snapshot
from modules.backend.temporal.mission_run_models import ScheduleSyncStats
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway

_SOURCE = "mission_schedule_service"
_SPEC_FIELDS = ("cron_expression", "time_zone_name", "starts_at", "ends_at")
_WATERMARK_FIELDS = frozenset({"cron_expression", "time_zone_name", "starts_at"})
_ABSENT_STATUSES = frozenset({MissionScheduleStatus.COMPLETED, MissionScheduleStatus.ARCHIVED})


def _recurrence() -> RecurrenceSchema:
    return get_app_config().missions.recurrence


class MissionScheduleService(BaseService):
    """Create, change and mirror mission schedules; claim their occurrences."""

    def __init__(
        self,
        session: AsyncSession,
        gateway: TemporalScheduleGateway,
        event_bus: EventBusProtocol,
    ) -> None:
        super().__init__(session)
        self._gateway = gateway
        self._event_bus = event_bus
        self._schedule_repo = MissionScheduleRepository(session)
        self._mission_repo = MissionRepository(session)
        self._definition_repo = WorkflowDefinitionRepository(session)

    # ── Reads ────────────────────────────────────────────────────────────

    async def get_schedule(self, mission_id: str, schedule_id: str) -> MissionSchedule:
        """The schedule, loaded by both ids; NotFoundError otherwise."""
        schedule = await self._schedule_repo.get_for_mission(mission_id, schedule_id)
        if schedule is None:
            raise NotFoundError(f"Schedule {schedule_id} not found in mission {mission_id}")
        return schedule

    async def list_schedules(
        self, mission_id: str, *, include_archived: bool
    ) -> list[MissionSchedule]:
        return await self._schedule_repo.list_by_mission(mission_id, include_archived)

    async def next_fire_times(self, schedule: MissionSchedule, count: int) -> list[datetime]:
        """The next action times from Temporal; [] when the schedule is absent."""
        description = await self._gateway.describe(schedule.temporal_schedule_id)
        if description is None:
            return []
        return list(description.info.next_action_times[:count])

    # ── Create and change ────────────────────────────────────────────────

    async def create_schedule(
        self, mission_id: str, data: MissionScheduleCreate, user_id: str
    ) -> MissionSchedule:
        recurrence = _recurrence()
        if not recurrence.enabled:
            raise ValidationError("recurrence disabled")
        await probe_spec(
            self._gateway,
            build_spec(data.cron_expression, data.time_zone_name, data.starts_at, data.ends_at),
            recurrence,
        )

        mission = await self._mission_repo.get_by_id(mission_id)
        if mission.status == MissionStatus.ARCHIVED:
            raise ValidationError("an archived mission cannot have schedules")
        await self._check_gate_mode(mission_id)
        if await self._schedule_repo.count_non_archived(mission_id) >= (
            recurrence.max_schedules_per_mission
        ):
            raise ValidationError(
                f"a mission may have at most {recurrence.max_schedules_per_mission} schedules"
            )
        if data.kind == MissionScheduleKind.OBJECTIVE:
            check_template(data.objective_template, recurrence)
        else:
            await check_definition(
                self._definition_repo,
                mission_id,
                data.workflow_definition_id,
                data.workflow_parameters,
            )
        catch_up = resolve_catch_up(data.catch_up_window_seconds, recurrence)

        schedule = await self._schedule_repo.create(
            mission_id=mission_id,
            name=data.name,
            kind=data.kind,
            objective_template=data.objective_template,
            workflow_definition_id=data.workflow_definition_id,
            workflow_parameters=data.workflow_parameters,
            cron_expression=data.cron_expression,
            time_zone_name=data.time_zone_name,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            max_runs=data.max_runs,
            catch_up_window_seconds=catch_up,
            status=MissionScheduleStatus.ACTIVE,
            temporal_sync_state=TemporalSyncState.PENDING,
            created_by_user_id=user_id,
            last_claimed_scheduled_for=utc_now(),
        )
        schedule_id = schedule.id
        await self._session.commit()
        self._log_operation(
            "Mission schedule created", mission_id=mission_id, schedule_id=schedule_id
        )

        await self.sync_to_temporal(schedule_id)
        await self._emit_changed(mission_id, schedule_id, None, MissionScheduleStatus.ACTIVE)
        return schedule

    async def update_schedule(
        self, mission_id: str, schedule_id: str, data: MissionScheduleUpdate, user_id: str
    ) -> MissionSchedule:
        present = data.model_fields_set
        schedule = await self.get_schedule(mission_id, schedule_id)
        effective = {
            name: getattr(data, name) if name in present else getattr(schedule, name)
            for name in _SPEC_FIELDS
        }
        await self._session.commit()
        for name in ("name", "cron_expression", "time_zone_name", "workflow_parameters"):
            if name in present and getattr(data, name) is None:
                raise ValidationError(f"{name} cannot be cleared")

        recurrence = _recurrence()
        if present & set(_SPEC_FIELDS):
            await probe_spec(self._gateway, build_spec(**effective), recurrence)

        schedule = await self._lock(mission_id, schedule_id)
        if schedule.status == MissionScheduleStatus.ARCHIVED:
            raise ConflictError("an archived schedule cannot be changed")
        starts_at, ends_at = effective["starts_at"], effective["ends_at"]
        if starts_at is not None and ends_at is not None and ends_at <= starts_at:
            raise ValidationError("ends_at must be after starts_at")
        await check_update_target(
            self._definition_repo, mission_id, schedule, data, present, recurrence
        )

        changes = {name: getattr(data, name) for name in present}
        if "catch_up_window_seconds" in changes:
            changes["catch_up_window_seconds"] = resolve_catch_up(
                changes["catch_up_window_seconds"], recurrence
            )
        if any(
            name in changes and changes[name] != getattr(schedule, name)
            for name in _WATERMARK_FIELDS
        ):
            schedule.last_claimed_scheduled_for = utc_now()
        for name, value in changes.items():
            setattr(schedule, name, value)

        from_status = schedule.status
        if from_status == MissionScheduleStatus.COMPLETED and present & {"max_runs", "ends_at"}:
            runs_left = schedule.max_runs is None or schedule.max_runs > schedule.executed_run_count
            in_window = schedule.ends_at is None or schedule.ends_at > utc_now()
            if runs_left and in_window:
                schedule.status = MissionScheduleStatus.ACTIVE
                schedule.completed_reason = None
        to_status = schedule.status
        await self._session.commit()
        self._log_operation(
            "Mission schedule updated",
            mission_id=mission_id,
            schedule_id=schedule_id,
            user_id=user_id,
            fields=sorted(present),
        )

        await self.sync_to_temporal(schedule_id)
        if to_status != from_status:
            await self._emit_changed(mission_id, schedule_id, from_status, to_status)
        return schedule

    async def pause_schedule(
        self, mission_id: str, schedule_id: str, user_id: str
    ) -> MissionSchedule:
        return await self._transition(
            mission_id,
            schedule_id,
            user_id,
            {MissionScheduleStatus.ACTIVE},
            MissionScheduleStatus.PAUSED,
        )

    async def resume_schedule(
        self, mission_id: str, schedule_id: str, user_id: str
    ) -> MissionSchedule:
        """PAUSED to ACTIVE; resets the watermark so the pause is never backfilled."""
        await self._check_gate_mode(mission_id)
        return await self._transition(
            mission_id,
            schedule_id,
            user_id,
            {MissionScheduleStatus.PAUSED},
            MissionScheduleStatus.ACTIVE,
        )

    async def archive_schedule(
        self, mission_id: str, schedule_id: str, user_id: str
    ) -> MissionSchedule:
        return await self._transition(
            mission_id,
            schedule_id,
            user_id,
            {
                MissionScheduleStatus.ACTIVE,
                MissionScheduleStatus.PAUSED,
                MissionScheduleStatus.COMPLETED,
            },
            MissionScheduleStatus.ARCHIVED,
        )

    # ── Temporal mirror ──────────────────────────────────────────────────

    async def sync_to_temporal(self, schedule_id: str) -> TemporalSyncState:
        """Make the Temporal Schedule match the row; record and return the outcome."""
        # refresh: the identity map may hold rows loaded before another transaction changed them.
        schedule = await self._schedule_repo.get_by_id(schedule_id)
        await self._session.refresh(schedule)
        mission = await self._mission_repo.get_by_id(schedule.mission_id)
        await self._session.refresh(mission)
        mission_id = schedule.mission_id
        temporal_id = schedule.temporal_schedule_id
        status = schedule.status
        mission_status = MissionStatus(mission.status)
        spec = build_spec(
            schedule.cron_expression, schedule.time_zone_name, schedule.starts_at, schedule.ends_at
        )
        catch_up = schedule.catch_up_window_seconds
        await self._session.commit()

        tick_config_hash: str | None = None
        try:
            if status in _ABSENT_STATUSES or not _recurrence().enabled:
                await self._gateway.delete(temporal_id)
            else:
                snapshot = build_tick_config_snapshot()
                paused = not (
                    status == MissionScheduleStatus.ACTIVE
                    and mission_status == MissionStatus.ACTIVE
                )
                note = (
                    f"mission_{mission_status.value}"
                    if mission_status != MissionStatus.ACTIVE
                    else status.value
                )
                await self._gateway.upsert(
                    temporal_id,
                    build_tick_schedule(schedule_id, snapshot, spec, catch_up, paused, note),
                )
                tick_config_hash = snapshot.config_hash
        except (RPCError, ExternalServiceError) as err:
            error = redact_secrets(str(err))
            schedule.temporal_sync_state = TemporalSyncState.FAILED
            schedule.temporal_sync_error = error
            await self._session.commit()
            self._logger.error(
                "Mission schedule sync to Temporal failed",
                extra={"mission_id": mission_id, "schedule_id": schedule_id, "error": error},
            )
            await self._emit(
                mission_id,
                MissionScheduleSyncFailedEvent(
                    session_id=uuid.UUID(mission_id),
                    source=_SOURCE,
                    mission_id=mission_id,
                    mission_run_id=None,
                    schedule_id=schedule_id,
                    error=error,
                ),
            )
            return TemporalSyncState.FAILED

        schedule.temporal_sync_state = TemporalSyncState.SYNCED
        schedule.temporal_synced_at = utc_now()
        schedule.temporal_sync_error = None
        schedule.tick_config_hash = tick_config_hash
        await self._session.commit()
        return TemporalSyncState.SYNCED

    async def sync_mission(self, mission_id: str) -> ScheduleSyncStats:
        """Sync every non-archived schedule of the mission."""
        schedules = await self._schedule_repo.list_by_mission(mission_id, False)
        ids = [s.id for s in schedules]
        stats = ScheduleSyncStats(synced=0, failed=0, deleted_orphans=0, completed=0)
        for schedule_id in ids:
            self._count(stats, await self.sync_to_temporal(schedule_id))
        return stats

    async def sync_all(self) -> ScheduleSyncStats:
        """Complete expired schedules, sync every syncable row, delete orphan schedules."""
        stats = ScheduleSyncStats(synced=0, failed=0, deleted_orphans=0, completed=0)
        now = utc_now()
        rows = await self._schedule_repo.list_syncable()
        for schedule in rows:
            await self._session.refresh(schedule)
            if (
                schedule.ends_at is not None
                and schedule.ends_at < now
                and schedule.status in (MissionScheduleStatus.ACTIVE, MissionScheduleStatus.PAUSED)
            ):
                schedule.status = MissionScheduleStatus.COMPLETED
                schedule.completed_reason = MissionScheduleCompletedReason.END_DATE_REACHED
                stats.completed += 1
        ids = [s.id for s in rows]
        await self._session.commit()

        for schedule_id in ids:
            self._count(stats, await self.sync_to_temporal(schedule_id))

        known = await self._schedule_repo.list_temporal_schedule_ids()
        await self._session.commit()
        for temporal_id in await self._gateway.list_ids(TEMPORAL_SCHEDULE_ID_PREFIX):
            if temporal_id not in known:
                await self._gateway.delete(temporal_id)
                stats.deleted_orphans += 1
                self._logger.info(
                    "Deleted orphan mission schedule", extra={"temporal_schedule_id": temporal_id}
                )
        return stats

    # ── Claim ────────────────────────────────────────────────────────────

    async def claim_occurrence(self, schedule_id: str, scheduled_for: datetime) -> OccurrenceClaim:
        """Decide and record one scheduled occurrence (contract 3.3.2); commits."""
        return await claim_occurrence(
            self._session, self._gateway, self._emit, schedule_id, scheduled_for
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _check_gate_mode(self, mission_id: str) -> None:
        plan = await MissionPlanService(self._session).get_or_create_plan(mission_id)
        if plan.gate_mode == GateMode.INTERACTIVE:
            raise ValidationError("an interactive mission cannot be scheduled")

    async def _lock(self, mission_id: str, schedule_id: str) -> MissionSchedule:
        schedule = await self._schedule_repo.lock(schedule_id)
        if schedule is None or schedule.mission_id != mission_id:
            raise NotFoundError(f"Schedule {schedule_id} not found in mission {mission_id}")
        return schedule

    async def _transition(
        self,
        mission_id: str,
        schedule_id: str,
        user_id: str,
        allowed_from: set[MissionScheduleStatus],
        to_status: MissionScheduleStatus,
    ) -> MissionSchedule:
        schedule = await self.get_schedule(mission_id, schedule_id)
        from_status = schedule.status
        if from_status not in allowed_from:
            raise ConflictError(
                f"schedule is {from_status.value}; cannot move to {to_status.value}"
            )
        schedule.status = to_status
        schedule.completed_reason = None
        if to_status == MissionScheduleStatus.ACTIVE:
            schedule.last_claimed_scheduled_for = utc_now()
        await self._session.commit()
        self._log_operation(
            "Mission schedule status changed",
            mission_id=mission_id,
            schedule_id=schedule_id,
            user_id=user_id,
            to_status=to_status.value,
        )
        await self.sync_to_temporal(schedule_id)
        await self._emit_changed(mission_id, schedule_id, from_status, to_status)
        return schedule

    @staticmethod
    def _count(stats: ScheduleSyncStats, state: TemporalSyncState) -> None:
        if state == TemporalSyncState.SYNCED:
            stats.synced += 1
        else:
            stats.failed += 1

    async def _emit_changed(
        self,
        mission_id: str,
        schedule_id: str,
        from_status: MissionScheduleStatus | None,
        to_status: MissionScheduleStatus,
    ) -> None:
        await self._emit(
            mission_id,
            MissionScheduleChangedEvent(
                session_id=uuid.UUID(mission_id),
                source=_SOURCE,
                mission_id=mission_id,
                mission_run_id=None,
                schedule_id=schedule_id,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value,
                completed_reason=None,
            ),
        )

    async def _emit(self, mission_id: str, event: SessionEvent) -> None:
        """Publish an event; emission is best-effort and never fails the caller."""
        try:
            await self._event_bus.publish_to_mission(mission_id, event)
        except Exception as err:  # noqa: BLE001
            # best-effort — this IS the event-emission path; nowhere further to report.
            self._logger.warning(
                "Failed to publish mission schedule event",
                extra={"mission_id": mission_id, "event_type": event.event_type, "error": str(err)},
            )
