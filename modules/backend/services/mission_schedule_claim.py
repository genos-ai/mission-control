"""claim_occurrence (Plan 88 step 88.1.6, contract 3.3.2).

Decides and records one scheduled occurrence in a single transaction with the
schedule row locked FOR UPDATE, then commits and emits events. The
list_matching_times calls run with the lock held: the one deliberate external
call inside a transaction, bounded by the claim activity's timeout. Every row,
whatever its outcome, consumes exactly one gap-free sequence number.
"""

import dataclasses
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.events.base import SessionEvent
from modules.backend.events.mission_run_types import (
    MissionRunCreatedEvent,
    MissionRunOccurrenceRecordedEvent,
)
from modules.backend.models.mission import MissionStatus
from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_schedule import (
    MissionScheduleCompletedReason,
    MissionScheduleKind,
    MissionScheduleStatus,
)
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.mission_schedule import MissionScheduleRepository
from modules.backend.schemas.mission_schedule import OccurrenceClaim
from modules.backend.temporal.config_snapshots import build_run_config_snapshot
from modules.backend.temporal.mission_run_models import (
    MissionRunWorkflowInput,
    NotificationRequest,
)
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

logger = get_logger(__name__)

_SOURCE = "mission_schedule_claim"
_ONE_ACTIVE_CONSTRAINT = "uq_mission_runs_one_active"
# NotificationKind values (contract 3.6.2); the enum arrives in 88.4.3.
RUN_MISSED = "run_missed"
RUN_SKIPPED = "run_skipped"

Emit = Callable[[str, SessionEvent], Awaitable[None]]


def _in_zone(moment: datetime, time_zone_name: str) -> str:
    """ISO 8601 text of moment in the schedule's IANA zone (contract 3.1.5)."""
    zone = ZoneInfo(time_zone_name)
    return moment.astimezone(zone).isoformat()  # display only; stored values stay UTC


def _violates(err: IntegrityError, constraint: str) -> bool:
    """Whether the IntegrityError came from the named constraint (asyncpg cause)."""
    return getattr(err.orig.__cause__, "constraint_name", None) == constraint


@dataclasses.dataclass
class _Recorded:
    """Plain values of an inserted SKIPPED or MISSED row, safe after commit."""

    row: MissionRun
    run_id: str
    status: MissionRunStatus
    reason: MissionRunStatusReason


class _Claim:
    """One claim transaction. Not reused across claims."""

    def __init__(self, session: AsyncSession, gateway: TemporalScheduleGateway) -> None:
        self._session = session
        self._gateway = gateway
        self._schedules = MissionScheduleRepository(session)
        self._missions = MissionRepository(session)
        self._plans = MissionPlanRepository(session)
        self._runs = MissionRunRepository(session)

    async def _insert(
        self,
        *,
        mission_id: str,
        plan_id: str,
        schedule_id: str,
        scheduled_for: datetime,
        status: MissionRunStatus,
        reason: MissionRunStatusReason,
    ) -> _Recorded:
        sequence = await self._missions.increment_run_sequence(mission_id)
        run_id = str(uuid.uuid4())
        row = await self._runs.insert_occurrence(
            id=run_id,
            mission_id=mission_id,
            plan_id=plan_id,
            schedule_id=schedule_id,
            sequence=sequence,
            scheduled_for=scheduled_for,
            status=status,
            status_reason=reason,
            status_detail=None,
            objective=None,
            workflow_definition_id=None,
            workflow_parameters={},
            temporal_workflow_id=None,
            config_snapshot={},
        )
        if row is None:
            # The schedule row lock serialises claims and each slot is checked first.
            raise ConflictError(f"slot {schedule_id}@{scheduled_for.isoformat()} already claimed")
        return _Recorded(row=row, run_id=run_id, status=status, reason=reason)

    async def run(
        self, schedule_id: str, scheduled_for: datetime
    ) -> tuple[OccurrenceClaim, list[SessionEvent]]:
        schedule = await self._schedules.lock(schedule_id)
        if schedule is None:
            raise NotFoundError(f"Mission schedule {schedule_id} not found")
        mission_id = schedule.mission_id

        existing = await self._runs.get_by_slot(schedule_id, scheduled_for)
        if existing is not None:
            run_input = None
            if existing.status == MissionRunStatus.PENDING:
                run_input = MissionRunWorkflowInput(
                    mission_run_id=existing.id,
                    mission_id=mission_id,
                    plan_id=existing.plan_id,
                    config=build_run_config_snapshot(),
                )
            return OccurrenceClaim("duplicate", existing, run_input), []

        mission = await self._missions.get_by_id(mission_id)
        plan = await self._plans.get_by_mission_id_required(mission_id)
        plan_id = plan.id
        mission_name = mission.name
        mission_status = MissionStatus(mission.status)
        status = schedule.status
        kind = schedule.kind
        template = schedule.objective_template
        time_zone_name = schedule.time_zone_name
        definition_id = schedule.workflow_definition_id
        parameters = dict(schedule.workflow_parameters)
        temporal_id = schedule.temporal_schedule_id
        catch_up = schedule.catch_up_window_seconds
        max_runs = schedule.max_runs
        executed = schedule.executed_run_count
        watermark = schedule.last_claimed_scheduled_for
        lower = watermark or schedule.created_at
        slot = {"mission_id": mission_id, "plan_id": plan_id, "schedule_id": schedule_id}

        recorded: list[_Recorded] = []
        run: MissionRun | None = None
        run_input: MissionRunWorkflowInput | None = None
        events: list[SessionEvent] = []
        now = utc_now()

        if not get_app_config().missions.recurrence.enabled:
            logger.warning(
                "Schedule tick refused: recurrence disabled",
                extra={"mission_id": mission_id, "schedule_id": schedule_id},
            )
            this = await self._insert(
                **slot,
                scheduled_for=scheduled_for,
                status=MissionRunStatus.SKIPPED,
                reason=MissionRunStatusReason.SCHEDULE_NOT_ACTIVE,
            )
            recorded.append(this)
        else:
            upper = min(scheduled_for, now - timedelta(seconds=catch_up))
            if lower < upper:
                for t in await self._gateway.list_matching_times(temporal_id, lower, upper):
                    if lower < t < upper and await self._runs.get_by_slot(schedule_id, t) is None:
                        recorded.append(
                            await self._insert(
                                **slot,
                                scheduled_for=t,
                                status=MissionRunStatus.MISSED,
                                reason=MissionRunStatusReason.NOT_FIRED,
                            )
                        )
            backfilled = len(recorded)

            outcome = await self._decide(
                status,
                mission_status,
                now,
                scheduled_for,
                catch_up,
                temporal_id,
                mission_id,
                max_runs,
                executed,
            )
            if outcome is None:
                snapshot = build_run_config_snapshot()
                run_id = str(uuid.uuid4())
                try:
                    async with self._session.begin_nested():
                        sequence = await self._missions.increment_run_sequence(mission_id)
                        objective = None
                        if kind == MissionScheduleKind.OBJECTIVE:
                            objective = template.format(
                                scheduled_for=_in_zone(scheduled_for, time_zone_name),
                                sequence=sequence,
                                mission_name=mission_name,
                            )
                        run = await self._runs.insert_occurrence(
                            id=run_id,
                            **slot,
                            sequence=sequence,
                            scheduled_for=scheduled_for,
                            status=MissionRunStatus.PENDING,
                            status_reason=None,
                            status_detail=None,
                            objective=objective,
                            workflow_definition_id=definition_id,
                            workflow_parameters=parameters,
                            temporal_workflow_id=mission_run_workflow_id(run_id),
                            config_snapshot=dataclasses.asdict(snapshot),
                        )
                        if run is None:
                            raise ConflictError(
                                f"slot {schedule_id}@{scheduled_for.isoformat()} already claimed"
                            )
                except IntegrityError as err:
                    if not _violates(err, _ONE_ACTIVE_CONSTRAINT):
                        raise
                    logger.info(
                        "Schedule claim lost the active-run race",
                        extra={"mission_id": mission_id, "schedule_id": schedule_id},
                    )
                    run = None
                    recorded.append(
                        await self._insert(
                            **slot,
                            scheduled_for=scheduled_for,
                            status=MissionRunStatus.SKIPPED,
                            reason=MissionRunStatusReason.OVERLAP,
                        )
                    )
                if run is not None:
                    executed += 1
                    schedule.executed_run_count = executed
                    if max_runs is not None and executed == max_runs:
                        schedule.status = MissionScheduleStatus.COMPLETED
                        schedule.completed_reason = MissionScheduleCompletedReason.MAX_RUNS_REACHED
                    run_input = MissionRunWorkflowInput(
                        mission_run_id=run_id,
                        mission_id=mission_id,
                        plan_id=plan_id,
                        config=snapshot,
                    )
                    events.append(
                        MissionRunCreatedEvent(
                            session_id=uuid.UUID(mission_id),
                            source=_SOURCE,
                            mission_id=mission_id,
                            mission_run_id=run_id,
                            sequence=sequence,
                            trigger=MissionRunTrigger.SCHEDULE.value,
                            schedule_id=schedule_id,
                            scheduled_for=scheduled_for,
                        )
                    )
            else:
                tick_status, tick_reason = outcome
                recorded.append(
                    await self._insert(
                        **slot, scheduled_for=scheduled_for, status=tick_status, reason=tick_reason
                    )
                )
            if backfilled:
                events.append(
                    MissionRunOccurrenceRecordedEvent(
                        session_id=uuid.UUID(mission_id),
                        source=_SOURCE,
                        mission_id=mission_id,
                        mission_run_id=None,
                        status=MissionRunStatus.MISSED.value,
                        reason=MissionRunStatusReason.NOT_FIRED.value,
                        scheduled_for=scheduled_for,
                        count=backfilled,
                    )
                )

        schedule.last_claimed_scheduled_for = (
            max(watermark, scheduled_for) if watermark is not None else scheduled_for
        )

        this_tick = recorded[-1] if run is None else None
        if this_tick is not None:
            events.append(
                MissionRunOccurrenceRecordedEvent(
                    session_id=uuid.UUID(mission_id),
                    source=_SOURCE,
                    mission_id=mission_id,
                    mission_run_id=this_tick.run_id,
                    status=this_tick.status.value,
                    reason=this_tick.reason.value,
                    scheduled_for=scheduled_for,
                    count=1,
                )
            )

        subject_id = f"{schedule_id}:{scheduled_for.isoformat()}"
        notifications: list[NotificationRequest] = []
        missed_count = sum(1 for r in recorded if r.status == MissionRunStatus.MISSED)
        if missed_count:
            notifications.append(
                NotificationRequest(
                    kind=RUN_MISSED,
                    mission_id=mission_id,
                    mission_run_id=None,
                    gate_request_id=None,
                    subject_id=subject_id,
                    payload={"count": missed_count},
                )
            )
        if this_tick is not None and this_tick.status == MissionRunStatus.SKIPPED:
            notifications.append(
                NotificationRequest(
                    kind=RUN_SKIPPED,
                    mission_id=mission_id,
                    mission_run_id=this_tick.run_id,
                    gate_request_id=None,
                    subject_id=subject_id,
                    payload={"reason": this_tick.reason.value},
                )
            )

        claim = OccurrenceClaim(
            outcome="run" if this_tick is None else this_tick.status.value,
            run=run if this_tick is None else this_tick.row,
            run_input=run_input,
            notifications=notifications,
            recorded=[r.row for r in recorded],
        )
        return claim, events

    async def _decide(
        self,
        status: MissionScheduleStatus,
        mission_status: MissionStatus,
        now: datetime,
        scheduled_for: datetime,
        catch_up: int,
        temporal_id: str,
        mission_id: str,
        max_runs: int | None,
        executed: int,
    ) -> tuple[MissionRunStatus, MissionRunStatusReason] | None:
        """This tick's non-run outcome, first match wins; None means RUN."""
        if status != MissionScheduleStatus.ACTIVE:
            return MissionRunStatus.SKIPPED, MissionRunStatusReason.SCHEDULE_NOT_ACTIVE
        if mission_status != MissionStatus.ACTIVE:
            return MissionRunStatus.SKIPPED, MissionRunStatusReason.MISSION_NOT_ACTIVE
        if (now - scheduled_for).total_seconds() > catch_up:
            return MissionRunStatus.MISSED, MissionRunStatusReason.OUTSIDE_CATCHUP_WINDOW
        later_start = scheduled_for + timedelta(microseconds=1)
        if later_start <= now and any(
            scheduled_for < t <= now
            for t in await self._gateway.list_matching_times(temporal_id, later_start, now)
        ):
            return MissionRunStatus.MISSED, MissionRunStatusReason.SUPERSEDED
        if await self._runs.get_active_for_mission(mission_id) is not None:
            return MissionRunStatus.SKIPPED, MissionRunStatusReason.OVERLAP
        if max_runs is not None and executed >= max_runs:
            return MissionRunStatus.SKIPPED, MissionRunStatusReason.MAX_RUNS_REACHED
        return None


async def claim_occurrence(
    session: AsyncSession,
    gateway: TemporalScheduleGateway,
    emit: Emit,
    schedule_id: str,
    scheduled_for: datetime,
) -> OccurrenceClaim:
    """Claim one occurrence of a schedule (contract 3.3.2); commits, then emits."""
    claim, events = await _Claim(session, gateway).run(schedule_id, scheduled_for)
    await session.commit()
    for event in events:
        await emit(event.mission_id, event)
    if claim.notifications:
        logger.info(
            "Schedule claim notifications built (not sent before 88.4.5)",
            extra={
                "schedule_id": schedule_id,
                "kinds": [n.kind for n in claim.notifications],
            },
        )
    return claim
