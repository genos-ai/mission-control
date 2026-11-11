"""MissionRunService (Plan 88 step 88.1.7, contract 3.5.1).

Owns the mission run lifecycle: start (insert PENDING, then start the
workflow), begin (session, ExecutionRecord, backlog adoption), plan, task
graph, transitions and finalise. Snapshots come from temporal/config_snapshots;
workflows are started only through TemporalWorkflowGateway. Every stored
exception text goes through redact_secrets. The workflow-activity methods
(begin, plan, approve_proposed, task_graph, finalise) live in
mission_run_lifecycle.py and are mixed in via MissionRunLifecycleMixin.
"""

import dataclasses
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.decision_reasoning import encode_decision_reasoning
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
    MissionRunCreatedEvent,
    MissionRunStatusChangedEvent,
)
from modules.backend.models.execution_record import DecisionType, ExecutionRecordStatus
from modules.backend.models.mission import MissionStatus
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.mission_run import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.repositories.execution_record import ExecutionRecordRepository
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_context import MissionContextRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.mission_run_digest import MissionRunDigestRepository
from modules.backend.repositories.task import TaskRepository, WaveTaskRow
from modules.backend.repositories.user import UserRepository
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.schemas.mission_run import (
    MissionRunDetailResponse,
    MissionRunDigestResponse,
    MissionRunResponse,
    TaskSummary,
)
from modules.backend.services.base import BaseService
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_run_lifecycle import MissionRunLifecycleMixin
from modules.backend.temporal.config_snapshots import build_run_config_snapshot
from modules.backend.temporal.mission_run_models import (
    MissionRunWorkflowInput,
    TaskFailureDigest,
    TasksApprovedSignal,
    digest_failures,
)
from modules.backend.temporal.workflow_gateway import (
    TemporalWorkflowGateway,
    WorkflowState,
)
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

_SOURCE = "mission_run_service"
# Page size of list_runs when the caller sends no limit; replaced by cli.yaml in 88.1.13.
DEFAULT_RUN_LIST_LIMIT = 50
# The decider on a run's Director objective-met decision (declare_objective_met).
DIRECTOR_DECIDER = "mission.director.agent"
_ONE_ACTIVE_CONSTRAINT = "uq_mission_runs_one_active"

_RECORD_STATUS: dict[MissionRunStatus, ExecutionRecordStatus] = {
    MissionRunStatus.SUCCEEDED: ExecutionRecordStatus.COMPLETED,
    MissionRunStatus.FAILED: ExecutionRecordStatus.FAILED,
    MissionRunStatus.BUDGET_STOPPED: ExecutionRecordStatus.FAILED,
    MissionRunStatus.CANCELLED: ExecutionRecordStatus.CANCELLED,
}


def _violates(err: IntegrityError, constraint: str) -> bool:
    """Whether the IntegrityError came from the named constraint (asyncpg cause)."""
    return getattr(err.orig.__cause__, "constraint_name", None) == constraint


def _is_uuid(value: str | None) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


class MissionRunService(MissionRunLifecycleMixin, BaseService):
    """Start, drive and end mission runs."""

    def __init__(self, session: AsyncSession, event_bus: EventBusProtocol) -> None:
        super().__init__(session)
        self._event_bus = event_bus
        self._runs = MissionRunRepository(session)
        self._digests = MissionRunDigestRepository(session)
        self._missions = MissionRepository(session)
        self._plans = MissionPlanRepository(session)
        self._tasks = TaskRepository(session)
        self._users = UserRepository(session)
        self._records = ExecutionRecordRepository(session)
        self._contexts = MissionContextRepository(session)
        self._workflow_runs = WorkflowRunRepository(session)
        self._plan_svc = MissionPlanService(session, event_bus=event_bus)

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _emit(self, mission_id: str, event: SessionEvent) -> None:
        """Publish an event; emission is best-effort and never fails the caller."""
        try:
            await self._event_bus.publish_to_mission(mission_id, event)
        except Exception as err:  # noqa: BLE001
            # best-effort — this IS the event-emission path; nowhere further to report.
            self._logger.warning(
                "Failed to publish mission run event",
                extra={"mission_id": mission_id, "event_type": event.event_type, "error": str(err)},
            )

    async def _is_platform_user(self, user_id: str | None) -> bool:
        """user_id parses as a UUID and names an existing user."""
        if not _is_uuid(user_id):
            return False
        return await self._users.get_by_id_or_none(str(user_id)) is not None

    async def _context_version(self, mission_id: str) -> int:
        """The mission's MCD version; 0 when no MCD exists."""
        context = await self._contexts.get_by_mission_id(mission_id)
        return context.version if context is not None else 0

    # ── Reads ────────────────────────────────────────────────────────────

    async def get_active_run(self, mission_id: str) -> MissionRun | None:
        """The mission's non-terminal run, or None when it has none."""
        return await self._runs.get_active_for_mission(mission_id)

    async def get_run(self, mission_id: str, run_id_or_sequence: str) -> MissionRun:
        """The run by sequence (all digits) or id, within the mission; NotFoundError otherwise."""
        run: MissionRun | None = None
        if run_id_or_sequence.isdigit():
            run = await self._runs.get_by_sequence(mission_id, int(run_id_or_sequence))
        elif _is_uuid(run_id_or_sequence):
            run = await self._runs.get_for_mission(mission_id, run_id_or_sequence)
        if run is None:
            raise NotFoundError(f"Run {run_id_or_sequence} not found in mission {mission_id}")
        return run

    async def get_run_detail(
        self, mission_id: str, run_id_or_sequence: str
    ) -> MissionRunDetailResponse:
        """The run with its ExecutionRecord id, digest and owned tasks (88.4.8 adds gates)."""
        run = await self.get_run(mission_id, run_id_or_sequence)
        record = await self._records.get_by_mission_run(run.id)
        digest = await self._digests.get_by_run(run.id)
        tasks = await self._tasks.list_by_run(run.id)
        return MissionRunDetailResponse(
            run=MissionRunResponse.model_validate(run),
            execution_record_id=record.id if record else None,
            digest=MissionRunDigestResponse.model_validate(digest) if digest else None,
            tasks=[TaskSummary.model_validate(task) for task in tasks],
        )

    async def list_runs(
        self,
        mission_id: str,
        *,
        statuses: list[MissionRunStatus] | None,
        limit: int,
        before_sequence: int | None,
    ) -> list[MissionRun]:
        """The mission's runs, newest sequence first."""
        return await self._runs.list_for_mission(
            mission_id, statuses=statuses, limit=limit, before_sequence=before_sequence
        )

    # ── Start and cancel ─────────────────────────────────────────────────

    async def start_run(
        self,
        mission_id: str,
        *,
        trigger: MissionRunTrigger,
        objective: str | None,
        user_id: str,
        session_id: str | None,
    ) -> MissionRun:
        """Insert a PENDING run, commit, then start its workflow.

        ConflictError when another run is active (the sequence increment rolls
        back with the insert). A failed workflow start ends the run
        FAILED/START_FAILED and raises ExternalServiceError.
        """
        mission = await self._missions.get_by_id(mission_id)
        if MissionStatus(mission.status) != MissionStatus.ACTIVE:
            raise ConflictError(f"Mission {mission_id} is {MissionStatus(mission.status).value}")
        if not await self._is_platform_user(user_id):
            raise ValidationError("user is not a platform user")
        plan = await self._plan_svc.get_or_create_plan(mission_id)
        plan_id = plan.id

        snapshot = build_run_config_snapshot()
        sequence = await self._missions.increment_run_sequence(mission_id)
        run_id = str(uuid.uuid4())
        run = MissionRun(
            id=run_id,
            mission_id=mission_id,
            plan_id=plan_id,
            sequence=sequence,
            trigger=trigger,
            triggered_by_user_id=user_id,
            objective=objective,
            session_id=session_id,
            status=MissionRunStatus.PENDING,
            temporal_workflow_id=mission_run_workflow_id(run_id),
            config_snapshot=dataclasses.asdict(snapshot),
        )
        self._session.add(run)
        try:
            await self._session.flush()
        except IntegrityError as err:
            if not _violates(err, _ONE_ACTIVE_CONSTRAINT):
                raise
            await self._session.rollback()
            active = await self._runs.get_active_for_mission(mission_id)
            if active is None:
                raise ConflictError("another run of this mission is active") from err
            raise ConflictError(f"run #{active.sequence} is {active.status.value}") from err
        await self._session.commit()

        await self._emit(
            mission_id,
            MissionRunCreatedEvent(
                session_id=uuid.UUID(session_id or mission_id),
                source=_SOURCE,
                mission_id=mission_id,
                mission_run_id=run_id,
                sequence=sequence,
                trigger=trigger.value,
                schedule_id=None,
                scheduled_for=None,
            ),
        )

        try:
            gateway = await TemporalWorkflowGateway.connect()
            await gateway.start_mission_run(
                MissionRunWorkflowInput(
                    mission_run_id=run_id, mission_id=mission_id, plan_id=plan_id, config=snapshot
                )
            )
        except Exception as err:  # noqa: BLE001
            # Catch-all justified: any start failure must end the committed PENDING
            # run FAILED/START_FAILED rather than leave it blocking the mission.
            detail = redact_secrets(str(err))
            await self.transition(
                run_id, MissionRunStatus.FAILED, MissionRunStatusReason.START_FAILED, detail
            )
            raise ExternalServiceError(f"Run #{sequence} could not start: {detail}") from err

        self._log_operation(
            "Mission run started", mission_id=mission_id, run_id=run_id, sequence=sequence
        )
        return await self._runs.get_by_id(run_id)

    async def cancel_run(
        self,
        mission_id: str,
        run_id: str,
        user_id: str,
        reason: MissionRunStatusReason,
    ) -> MissionRun:
        """Record a cancel request; cancel an unstarted run at once, else cancel its workflow."""
        run = await self._runs.lock_for_mission(mission_id, run_id)
        if run is None:
            raise NotFoundError(f"Run {run_id} not found in mission {mission_id}")
        if run.status not in ACTIVE_RUN_STATUSES:
            raise ConflictError(f"run #{run.sequence} is {MissionRunStatus(run.status).value}")
        run.cancel_requested_at = utc_now()
        run.cancel_requested_by_user_id = user_id
        run.cancel_reason = reason
        if run.status == MissionRunStatus.PENDING and run.started_at is None:
            return await self.transition(
                run_id, MissionRunStatus.CANCELLED, MissionRunStatusReason.CANCELLED_BY_USER, None
            )
        workflow_id = run.temporal_workflow_id
        await self._session.commit()
        gateway = await TemporalWorkflowGateway.connect()
        await gateway.cancel(workflow_id)
        return await self._runs.get_by_id(run_id)

    async def on_tasks_approved(self, mission_id: str, task_ids: list[str], user_id: str) -> None:
        """Commit the approval, then wake the active run or start one for an idle mission.

        A run starts only when the plan is AUTONOMOUS and the mission ACTIVE.

        A run whose workflow is gone (NOT_FOUND) is left to finalise or the
        reconciler. A workflow run owns its own materialised tasks, so no run
        starts while one is active.
        """
        await self._session.commit()
        if not task_ids:
            return
        active = await self._runs.get_active_for_mission(mission_id)
        if active is not None:
            workflow_id = active.temporal_workflow_id
            gateway = await TemporalWorkflowGateway.connect()
            state = await gateway.signal(
                workflow_id, "tasks_approved", TasksApprovedSignal(task_ids=list(task_ids))
            )
            if state == WorkflowState.NOT_FOUND:
                self._logger.warning(
                    "Approved tasks not signalled: run workflow not found",
                    extra={
                        "mission_id": mission_id,
                        "run_id": active.id,
                        "workflow_id": workflow_id,
                    },
                )
            return
        plan = await self._plan_svc.get_or_create_plan(mission_id)
        if plan.gate_mode != GateMode.AUTONOMOUS:
            return
        mission = await self._missions.get_by_id(mission_id)
        if MissionStatus(mission.status) != MissionStatus.ACTIVE:
            return
        if await self._workflow_runs.list_active_for_mission(mission_id):
            return
        try:
            await self.start_run(
                mission_id,
                trigger=MissionRunTrigger.MANUAL,
                objective=None,
                user_id=user_id,
                session_id=None,
            )
        except ConflictError as err:
            self._logger.info(
                "Run not started for approved tasks",
                extra={"mission_id": mission_id, "reason": str(err)},
            )

    # ── Supervisor inputs (88.2.6) ───────────────────────────────────────

    async def failure_digests(
        self, run_id: str, task_ids: list[str], cap: int
    ) -> tuple[list[TaskFailureDigest], int]:
        """The FAILED tasks among ``task_ids`` in the run as at most ``cap`` digests.

        Returns the digests and the number dropped. The post-run reviewer
        passes the wave's task ids: a failure an earlier wave left behind is
        not a failure of the wave under review.
        """
        rows = await self._tasks.failed_tasks_for_run(run_id, task_ids)
        return digest_failures(rows, cap)

    async def wave_tasks(self, run_id: str, task_ids: list[str]) -> list[WaveTaskRow]:
        """The run's tasks among ``task_ids`` with their current status and description."""
        return await self._tasks.wave_tasks_for_run(run_id, task_ids)

    async def require_active_run(self, mission_id: str, run_id: str) -> None:
        """Raise unless run_id is the mission's active run.

        Raises:
            ConflictError: run_id is not the mission's active run.
        """
        active = await self.get_active_run(mission_id)
        if active is None or active.id != run_id:
            raise ConflictError(
                f"Mission run {run_id} is not the active run of mission {mission_id}"
            )

    async def _record_director_objective_met(
        self, run: MissionRun, record_id: str, reason: str
    ) -> None:
        """Record the Director's objective-met decision as the run ends on it.

        Written in the post-run reviewer's format (execution_decisions,
        reasoning with a metadata tail) on the run's ExecutionRecord, with the
        Director as the decider. Only finalise calls it, for a run ending
        SUCCEEDED (OBJECTIVE_MET) on the Director's declaration, so the
        decision row and the run's outcome commit together. The caller commits.
        """
        reasoning = encode_decision_reasoning(
            reason,
            {
                "action": DecisionType.OBJECTIVE_MET.value,
                "reviewer": DIRECTOR_DECIDER,
                "mission_run_id": run.id,
                "iteration": run.iteration_count,
            },
        )
        await ExecutionPersistenceService(self._session).save_decision(
            record_id, DecisionType.OBJECTIVE_MET.value, reasoning
        )

    async def record_iteration(self, run_id: str, iteration_count: int) -> None:
        """Set mission_runs.iteration_count; the caller commits."""
        run = await self._runs.get_by_id(run_id)
        run.iteration_count = iteration_count
        await self._session.flush()

    # ── Transitions ──────────────────────────────────────────────────────

    async def transition(
        self,
        run_id: str,
        target: MissionRunStatus,
        reason: MissionRunStatusReason | None,
        detail: str | None,
    ) -> MissionRun:
        """Move the locked run to target; a terminal target also closes its ExecutionRecord.

        Emits MissionRunStatusChangedEvent, then commits.
        """
        found = await self._runs.get_by_id(run_id)
        run = await self._runs.lock_for_mission(found.mission_id, run_id)
        from_status = MissionRunStatus(run.status)
        run.transition_status(target, reason, detail)
        if target in TERMINAL_RUN_STATUSES:
            record = await self._records.get_by_mission_run(run_id)
            if record is not None:
                record.status = _RECORD_STATUS[target]
                record.completed_at = utc_now()
        mission_id = run.mission_id
        await self._emit(
            mission_id,
            MissionRunStatusChangedEvent(
                session_id=uuid.UUID(run.session_id or mission_id),
                source=_SOURCE,
                mission_id=mission_id,
                mission_run_id=run_id,
                from_status=from_status.value,
                to_status=target.value,
                reason=reason.value if reason is not None else None,
                detail=detail,
            ),
        )
        await self._session.commit()
        await self._session.refresh(run)
        return run
