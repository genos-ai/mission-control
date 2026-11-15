"""MissionLifecycleService (Plan 88 step 88.4.5, contracts 3.2.2 and 3.5.1).

The only owner of mission status changes: pause, resume, archive, unarchive
and the emergency stop. Each change commits in Postgres first, then reaches
Temporal: the mission's schedules are synced through MissionScheduleService and
the active run is signalled or cancelled through TemporalWorkflowGateway. An
ExternalServiceError from Temporal propagates after the commit; the DB state
stands and the run or the reconciler picks it up.

resume_mission is the one method that calls Temporal inside its transaction:
it lists each ACTIVE schedule's matching times with the schedule row locked,
the same deliberate exception as claim_occurrence (contract 3.5 layering).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, ExternalServiceError
from modules.backend.core.protocols import EventBusProtocol
from modules.backend.core.utils import utc_now
from modules.backend.events.mission_run_types import (
    MissionLifecycleChangedEvent,
    MissionRunOccurrenceRecordedEvent,
)
from modules.backend.models.mission import Mission, MissionPauseReason, MissionStatus
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.mission_run import MissionRunStatus, MissionRunStatusReason
from modules.backend.models.mission_schedule import MissionScheduleStatus
from modules.backend.repositories.gate_request import GateRequestRepository
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.mission_schedule import MissionScheduleRepository
from modules.backend.services.base import BaseService
from modules.backend.services.budget import BudgetService
from modules.backend.services.mission_run import MissionRunService
from modules.backend.services.mission_schedule import MissionScheduleService
from modules.backend.temporal.mission_run_models import PauseRequest, ResumeRequest
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway
from modules.backend.temporal.workflow_gateway import (
    TemporalWorkflowGateway,
    WorkflowState,
)
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

_SOURCE = "mission_lifecycle_service"
# Runs that take a request_pause signal on a USER pause (contract 3.2.2 row 1).
_PAUSABLE_RUN_STATUSES = frozenset({MissionRunStatus.RUNNING, MissionRunStatus.AWAITING_GATE})
_ARCHIVABLE = frozenset({MissionStatus.ACTIVE, MissionStatus.PAUSED})


class MissionLifecycleService(BaseService):
    """Pause, resume, archive and unarchive missions, in Postgres and in Temporal."""

    def __init__(self, session: AsyncSession, event_bus: EventBusProtocol) -> None:
        super().__init__(session)
        self._event_bus = event_bus
        self._missions = MissionRepository(session)
        self._plans = MissionPlanRepository(session)
        self._runs = MissionRunRepository(session)
        self._schedules = MissionScheduleRepository(session)
        self._gates = GateRequestRepository(session)
        self._schedule_gateway: TemporalScheduleGateway | None = None

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncIterator["MissionLifecycleService"]:
        """A MissionLifecycleService on its own DB session and event bus (in-process callers)."""
        from redis.asyncio import Redis as AsyncRedis

        from modules.backend.core.config import get_redis_url
        from modules.backend.core.database import get_async_session
        from modules.backend.events.bus import SessionEventBus

        redis = AsyncRedis.from_url(get_redis_url())
        try:
            async with get_async_session() as db:
                yield MissionLifecycleService(db, SessionEventBus(redis))
        finally:
            await redis.aclose()

    # ── Pause ────────────────────────────────────────────────────────────

    async def pause_mission(
        self, mission_id: str, *, reason: MissionPauseReason, user_id: str | None
    ) -> Mission:
        """ACTIVE to PAUSED; a USER pause also asks the RUNNING or AWAITING_GATE run to pause.

        Sends no notification: the callers send BUDGET_PAUSED and GATE_TIMEOUT_PAUSED.

        Raises:
            ConflictError: the mission is not ACTIVE.
        """
        mission = await self._missions.lock(mission_id)
        from_status = MissionStatus(mission.status)
        if from_status != MissionStatus.ACTIVE:
            raise ConflictError(f"Mission {mission_id} is {from_status.value}, not active")
        await self._apply_pause(mission, reason, user_id)
        await self._session.commit()

        await self._sync_schedules(mission_id)
        active = await self._runs.get_active_for_mission(mission_id)
        active_id = active.id if active is not None else None
        if (
            reason == MissionPauseReason.USER
            and active is not None
            and MissionRunStatus(active.status) in _PAUSABLE_RUN_STATUSES
        ):
            await self._signal(
                active_id,
                "request_pause",
                PauseRequest(requested_by_user_id=user_id, reason=reason.value),
            )
        await self._emit_changed(
            mission_id, active_id, from_status, MissionStatus.PAUSED, reason, user_id
        )
        self._log_operation(
            "Mission paused",
            mission_id=mission_id,
            reason=reason.value,
            user_id=user_id,
        )
        return await self._missions.get_by_id(mission_id)

    async def _apply_pause(
        self, mission: Mission, reason: MissionPauseReason, user_id: str | None
    ) -> None:
        """Set PAUSED and the paused_* columns and flush; no commit, no Temporal call."""
        mission.status = MissionStatus.PAUSED
        mission.paused_reason = reason
        mission.paused_at = utc_now()
        mission.paused_by_user_id = user_id
        await self._session.flush()

    async def pause_for_run(self, run_id: str, reason: MissionPauseReason) -> bool:
        """System pause of the run's mission; False when it is already PAUSED or ARCHIVED."""
        run = await self._runs.get_by_id(run_id)
        mission_id = run.mission_id
        mission = await self._missions.get_by_id(mission_id)
        if MissionStatus(mission.status) != MissionStatus.ACTIVE:
            return False
        await self.pause_mission(mission_id, reason=reason, user_id=None)
        return True

    async def pause_all_active(self, user_id: str) -> int:
        """Emergency stop: USER-pause every ACTIVE mission whose plan is AUTONOMOUS.

        Each mission is paused in its own transaction; its running run pauses
        at its next layer boundary, after the in-flight tasks finish. A
        mission that changed status meanwhile is skipped. A Temporal failure
        is logged and the stop continues: the mission is already PAUSED in
        Postgres. Returns the number of missions paused.
        """
        ids = await self._missions.list_ids_by_status_and_gate_mode(
            MissionStatus.ACTIVE, GateMode.AUTONOMOUS
        )
        paused = 0
        for mission_id in ids:
            try:
                await self.pause_mission(
                    mission_id, reason=MissionPauseReason.USER, user_id=user_id
                )
            except ConflictError:
                continue  # its status changed since the listing
            except ExternalServiceError as err:
                # non-fatal — the mission is PAUSED in Postgres; schedule sync
                # failures are recorded per row for the reconciler.
                self._logger.error(
                    "Emergency stop: mission paused but Temporal not reached",
                    extra={"mission_id": mission_id, "error": str(err)},
                )
            paused += 1
        self._log_operation("Emergency stop: autonomous missions paused", paused_count=paused)
        return paused

    # ── Resume ───────────────────────────────────────────────────────────

    async def resume_mission(self, mission_id: str, user_id: str | None) -> Mission:
        """PAUSED to ACTIVE; records every schedule slot of the pause as MISSED/NOT_FIRED.

        user_id is None only from resume_mission_for_run (88.4.8).

        Raises:
            ConflictError: the mission is not PAUSED, a gate that timed out is
                still undecided, or a monthly or lifetime cap is breached.
        """
        mission = await self._missions.lock(mission_id)
        from_status = MissionStatus(mission.status)
        if from_status != MissionStatus.PAUSED:
            raise ConflictError(f"Mission {mission_id} is {from_status.value}, not paused")
        if mission.paused_reason == MissionPauseReason.GATE_TIMEOUT and (
            await self._gates.has_undecided(mission_id)
        ):
            raise ConflictError(f"Mission {mission_id} has an undecided gate request")
        breach = BudgetService.mission_cap_breach(
            await BudgetService(self._session).get_status(mission_id)
        )
        if breach is not None:
            raise ConflictError(f"Mission {mission_id} is over its {breach.value}")

        paused_at = mission.paused_at
        now = utc_now()
        recorded = await self._record_pause_slots(mission_id, paused_at, now)
        mission.status = MissionStatus.ACTIVE
        mission.paused_reason = None
        mission.paused_at = None
        mission.paused_by_user_id = None
        await self._session.commit()

        for schedule_id, count in recorded:
            await self._emit(
                mission_id,
                MissionRunOccurrenceRecordedEvent(
                    session_id=uuid.UUID(mission_id),
                    source=_SOURCE,
                    mission_id=mission_id,
                    mission_run_id=None,
                    status=MissionRunStatus.MISSED.value,
                    reason=MissionRunStatusReason.NOT_FIRED.value,
                    scheduled_for=now,
                    count=count,
                ),
            )
            self._logger.info(
                "Mission pause slots recorded as missed",
                extra={
                    "mission_id": mission_id,
                    "schedule_id": schedule_id,
                    "count": count,
                },
            )
        await self._sync_schedules(mission_id)
        active = await self._runs.get_active_for_mission(mission_id)
        active_id = active.id if active is not None else None
        if active_id is not None:
            await self._signal(active_id, "resume", ResumeRequest(requested_by_user_id=user_id))
        await self._emit_changed(
            mission_id, active_id, from_status, MissionStatus.ACTIVE, None, user_id
        )
        self._log_operation("Mission resumed", mission_id=mission_id, user_id=user_id)
        return await self._missions.get_by_id(mission_id)

    async def _record_pause_slots(
        self, mission_id: str, paused_at: datetime | None, now: datetime
    ) -> list[tuple[str, int]]:
        """Insert MISSED/NOT_FIRED for each ACTIVE schedule's slots in (paused_at, now].

        Each schedule row is locked before its matching times are listed, and
        its watermark moves to now. Returns (schedule id, rows inserted) for
        each schedule with at least one row. No commit.
        """
        schedules = await self._schedules.list_by_mission(mission_id, include_archived=False)
        ids = [s.id for s in schedules if s.status == MissionScheduleStatus.ACTIVE]
        if not ids:
            return []
        plan = await self._plans.get_by_mission_id_required(mission_id)
        plan_id = plan.id
        recorded: list[tuple[str, int]] = []
        for schedule_id in ids:
            schedule = await self._schedules.lock(schedule_id)
            if schedule is None or schedule.status != MissionScheduleStatus.ACTIVE:
                continue
            count = 0
            if paused_at is not None:
                gateway = await self._gateway()
                times = await gateway.list_matching_times(
                    schedule.temporal_schedule_id, paused_at, now
                )
                for t in times:
                    if not paused_at < t <= now:
                        continue
                    if await self._runs.get_by_slot(schedule_id, t) is not None:
                        continue
                    await self._runs.insert_occurrence(
                        id=str(uuid.uuid4()),
                        mission_id=mission_id,
                        plan_id=plan_id,
                        schedule_id=schedule_id,
                        sequence=await self._missions.increment_run_sequence(mission_id),
                        scheduled_for=t,
                        status=MissionRunStatus.MISSED,
                        status_reason=MissionRunStatusReason.NOT_FIRED,
                        status_detail=None,
                        objective=None,
                        workflow_definition_id=None,
                        workflow_parameters={},
                        temporal_workflow_id=None,
                        config_snapshot={},
                    )
                    count += 1
            schedule.last_claimed_scheduled_for = now
            if count:
                recorded.append((schedule_id, count))
        await self._session.flush()
        return recorded

    # ── Archive ──────────────────────────────────────────────────────────

    async def archive_mission(self, mission_id: str, user_id: str) -> Mission:
        """ACTIVE or PAUSED to ARCHIVED (contract 3.2.2 row 4).

        Archives every schedule, commits, deletes the Temporal schedules,
        cancels the active run and cancels the undecided gate requests.

        Raises:
            ConflictError: the mission is already ARCHIVED.
        """
        mission = await self._missions.lock(mission_id)
        from_status = MissionStatus(mission.status)
        if from_status not in _ARCHIVABLE:
            raise ConflictError(f"Mission {mission_id} is {from_status.value}")
        schedules = await self._schedules.list_by_mission(mission_id, include_archived=False)
        schedule_ids = [s.id for s in schedules]
        for schedule in schedules:
            schedule.status = MissionScheduleStatus.ARCHIVED
        mission.status = MissionStatus.ARCHIVED
        mission.paused_reason = None
        mission.paused_at = None
        mission.paused_by_user_id = None
        await self._session.commit()

        if schedule_ids:
            service = await self._schedule_service()
            for schedule_id in schedule_ids:
                await service.sync_to_temporal(schedule_id)
        active = await self._runs.get_active_for_mission(mission_id)
        active_id = active.id if active is not None else None
        if active_id is not None:
            await MissionRunService(self._session, self._event_bus).cancel_run(
                mission_id, active_id, user_id, MissionRunStatusReason.MISSION_ARCHIVED
            )
        cancelled_gates = await self._gates.cancel_undecided(mission_id)
        await self._session.commit()
        await self._emit_changed(
            mission_id, active_id, from_status, MissionStatus.ARCHIVED, None, user_id
        )
        self._log_operation(
            "Mission archived",
            mission_id=mission_id,
            user_id=user_id,
            schedules=len(schedule_ids),
            cancelled_gates=cancelled_gates,
        )
        return await self._missions.get_by_id(mission_id)

    async def unarchive_mission(self, mission_id: str, user_id: str) -> Mission:
        """ARCHIVED to PAUSED (USER). Schedules stay ARCHIVED; the owner creates new ones.

        Raises:
            ConflictError: the mission is not ARCHIVED.
        """
        mission = await self._missions.lock(mission_id)
        from_status = MissionStatus(mission.status)
        if from_status != MissionStatus.ARCHIVED:
            raise ConflictError(f"Mission {mission_id} is {from_status.value}, not archived")
        await self._apply_pause(mission, MissionPauseReason.USER, user_id)
        await self._session.commit()
        await self._emit_changed(
            mission_id,
            None,
            from_status,
            MissionStatus.PAUSED,
            MissionPauseReason.USER,
            user_id,
        )
        self._log_operation("Mission unarchived", mission_id=mission_id, user_id=user_id)
        return await self._missions.get_by_id(mission_id)

    # ── Temporal ─────────────────────────────────────────────────────────

    async def _gateway(self) -> TemporalScheduleGateway:
        if self._schedule_gateway is None:
            try:
                self._schedule_gateway = await TemporalScheduleGateway.create()
            except RuntimeError as exc:
                raise ExternalServiceError(f"Temporal unavailable: {exc}") from exc
        return self._schedule_gateway

    async def _schedule_service(self) -> MissionScheduleService:
        return MissionScheduleService(self._session, await self._gateway(), self._event_bus)

    async def _sync_schedules(self, mission_id: str) -> None:
        """Mirror the mission's schedules; a failed row is recorded for the reconciler."""
        service = await self._schedule_service()
        await service.sync_mission(mission_id)

    async def _signal(self, run_id: str, signal: str, arg: object) -> None:
        """Signal the run's workflow; NOT_FOUND is logged and left to the reconciler."""
        gateway = await TemporalWorkflowGateway.connect()
        state = await gateway.signal(mission_run_workflow_id(run_id), signal, arg)
        if state == WorkflowState.NOT_FOUND:
            self._logger.warning(
                "Run workflow not found for signal",
                extra={"mission_run_id": run_id, "signal": signal},
            )

    # ── Events ───────────────────────────────────────────────────────────

    async def _emit_changed(
        self,
        mission_id: str,
        run_id: str | None,
        from_status: MissionStatus,
        to_status: MissionStatus,
        reason: MissionPauseReason | None,
        user_id: str | None,
    ) -> None:
        await self._emit(
            mission_id,
            MissionLifecycleChangedEvent(
                session_id=uuid.UUID(mission_id),
                source=_SOURCE,
                mission_id=mission_id,
                mission_run_id=run_id,
                from_status=from_status.value,
                to_status=to_status.value,
                paused_reason=reason.value if reason is not None else None,
                actor_user_id=user_id,
            ),
        )

    async def _emit(
        self,
        mission_id: str,
        event: MissionLifecycleChangedEvent | MissionRunOccurrenceRecordedEvent,
    ) -> None:
        """Publish an event; emission is best-effort and never fails the caller."""
        try:
            await self._event_bus.publish_to_mission(mission_id, event)
        except Exception as err:  # noqa: BLE001
            # best-effort — this IS the event-emission path; nowhere further to report.
            self._logger.warning(
                "Failed to publish mission lifecycle event",
                extra={
                    "mission_id": mission_id,
                    "event_type": event.event_type,
                    "error": str(err),
                },
            )
