"""MissionRunService (Plan 88 step 88.1.7, contract 3.5.1).

Owns the mission run lifecycle: start (insert PENDING, then start the
workflow), begin (session, ExecutionRecord, backlog adoption), plan, task
graph, transitions and finalise. Snapshots come from temporal/config_snapshots;
workflows are started only through TemporalWorkflowGateway. Every stored
exception text goes through redact_secrets.
"""

import dataclasses
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import (
    ConflictError,
    ExternalServiceError,
    MissionRunStateError,
    NotFoundError,
    RunStartRejectedError,
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
from modules.backend.models.execution_record import ExecutionRecordStatus
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
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.execution_record import ExecutionRecordRepository
from modules.backend.repositories.llm_ledger import LlmLedgerRepository
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_context import MissionContextRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.repositories.user import UserRepository
from modules.backend.repositories.workflow_definition import WorkflowDefinitionRepository
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.schemas.session import SessionCreate
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services.base import BaseService
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator
from modules.backend.services.session import SessionService
from modules.backend.services.workflow_run import WorkflowRunService
from modules.backend.services.workflow_task_mapping import steps_to_task_definitions
from modules.backend.temporal.config_snapshots import build_run_config_snapshot
from modules.backend.temporal.mission_run_models import (
    BeginRunResult,
    FinaliseRunResult,
    MissionRunWorkflowInput,
    NotificationRequest,
    PlanRunResult,
    RunTaskGraph,
)
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

_SOURCE = "mission_run_service"
_ONE_ACTIVE_CONSTRAINT = "uq_mission_runs_one_active"
_RUNNABLE_GATE_MODES = frozenset({GateMode.MANUAL, GateMode.AI_ASSISTED, GateMode.AUTONOMOUS})
_OWNER_NOT_USER = "owner not a platform user"
# NotificationKind values (contract 3.6.2); the enum arrives in 88.4.3.
RUN_SUCCEEDED = "run_succeeded"
RUN_FAILED = "run_failed"
BUDGET_PAUSED = "budget_paused"

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


def _notification_kind(
    status: MissionRunStatus, reason: MissionRunStatusReason | None
) -> str | None:
    """Run-end notification kind (contract 3.6.2); None when nothing is sent."""
    if status == MissionRunStatus.SUCCEEDED:
        return RUN_SUCCEEDED
    if status == MissionRunStatus.BUDGET_STOPPED:
        return BUDGET_PAUSED
    if status == MissionRunStatus.FAILED:
        return RUN_FAILED
    if status == MissionRunStatus.CANCELLED and reason != MissionRunStatusReason.CANCELLED_BY_USER:
        return RUN_FAILED
    return None


class MissionRunService(BaseService):
    """Start, drive and end mission runs."""

    def __init__(self, session: AsyncSession, event_bus: EventBusProtocol) -> None:
        super().__init__(session)
        self._event_bus = event_bus
        self._runs = MissionRunRepository(session)
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

    # ── Workflow activities ──────────────────────────────────────────────

    async def begin(self, run_id: str) -> BeginRunResult:
        """PENDING to RUNNING with a session, one ExecutionRecord and adopted backlog.

        Idempotent: a RUNNING run returns its stored values.
        """
        run = await self._runs.get_by_id(run_id)
        if run.status == MissionRunStatus.RUNNING:
            record = await self._records.get_by_mission_run(run_id)
            return BeginRunResult(
                session_id=run.session_id,
                execution_record_id=record.id,
                context_version_start=run.context_version_start,
                gate_mode=GateMode(run.gate_mode).value,
                previous_run_id=run.previous_run_id,
            )
        if run.status != MissionRunStatus.PENDING:
            raise MissionRunStateError(
                f"run {run_id} is {MissionRunStatus(run.status).value}, not pending"
            )
        mission_id = run.mission_id
        mission = await self._missions.get_by_id(mission_id)
        plan = await self._plans.get_by_id(run.plan_id)
        owner_id = mission.owner_id

        if not await self._is_platform_user(owner_id):
            await self.transition(
                run_id,
                MissionRunStatus.FAILED,
                MissionRunStatusReason.START_FAILED,
                _OWNER_NOT_USER,
            )
            raise RunStartRejectedError(f"run {run_id}: {_OWNER_NOT_USER}")
        gate_mode = GateMode(plan.gate_mode)
        if gate_mode not in _RUNNABLE_GATE_MODES:
            detail = f"gate mode {gate_mode.value} cannot run"
            await self.transition(
                run_id, MissionRunStatus.FAILED, MissionRunStatusReason.INVALID_GATE_MODE, detail
            )
            raise RunStartRejectedError(f"run {run_id}: {detail}")

        if run.session_id is None:
            session = await SessionService(self._session).create_session(
                SessionCreate(
                    mission_id=mission_id,
                    agent_id="mission.supervisor.agent",
                    goal=f"Mission run #{run.sequence}",
                ),
                user_id=owner_id,
            )
            run.session_id = session.id
        session_id = run.session_id

        record = await self._records.create(
            session_id=session_id,
            mission_id=mission_id,
            mission_run_id=run_id,
            status=ExecutionRecordStatus.RUNNING,
            temporal_workflow_id=mission_run_workflow_id(run_id),
            objective_statement=run.objective or "Approved backlog",
            task_params={"mission_run_id": run_id},
            started_at=utc_now(),
        )
        record_id = record.id

        if await self._workflow_runs.list_active_for_mission(mission_id):
            self._logger.info(
                "Backlog not adopted: a workflow run is active",
                extra={"mission_id": mission_id, "mission_run_id": run_id},
            )
        else:
            await self._tasks.adopt_backlog(run.plan_id, run_id, [TaskStatus.APPROVED])

        previous = await self._runs.get_latest_with_digest(mission_id)
        previous_run_id = previous.id if previous is not None else None
        context_version_start = await self._context_version(mission_id)

        run.gate_mode = gate_mode
        run.previous_run_id = previous_run_id
        run.context_version_start = context_version_start
        await self.transition(run_id, MissionRunStatus.RUNNING, None, None)
        return BeginRunResult(
            session_id=session_id,
            execution_record_id=record_id,
            context_version_start=context_version_start,
            gate_mode=gate_mode.value,
            previous_run_id=previous_run_id,
        )

    async def plan(self, run_id: str, session_id: str) -> PlanRunResult:
        """Plan the run's tasks: backlog dispatch, objective refine or workflow definition.

        ValidationError returns "failed"; any other exception propagates.
        """
        run = await self._runs.get_by_id(run_id)
        mission = await self._missions.get_by_id(run.mission_id)
        plan = await self._plans.get_by_id(run.plan_id)
        mission_id = run.mission_id
        plan_id = plan.id
        owner_id = mission.owner_id
        objective = run.objective
        definition_id = run.workflow_definition_id
        parameters = dict(run.workflow_parameters or {})
        gate_mode = GateMode(run.gate_mode)
        orchestrator = MissionPlanOrchestrator(self._session, event_bus=self._event_bus)

        try:
            if objective is None and definition_id is None:
                waiting = await self._tasks.list_by_run(run_id)
                ready = any(t.status in (TaskStatus.APPROVED, TaskStatus.PROPOSED) for t in waiting)
                status = "planned" if ready else "empty"
            elif objective is not None:
                await orchestrator.refine(plan_id, objective, owner_id, mission_run_id=run_id)
                status = "planned"
            else:
                definition = await WorkflowDefinitionRepository(self._session).get_by_id(
                    definition_id
                )
                workflow = WorkflowRunService._definition_to_schema(definition)
                task_plan = TaskPlan(
                    version="1.0.0",
                    mission_id=mission_id,
                    summary=workflow.description,
                    estimated_cost_usd=workflow.budget.max_cost_usd,
                    estimated_duration_seconds=0,
                    tasks=steps_to_task_definitions(workflow, parameters),
                )
                await orchestrator._persist_plan(
                    plan, task_plan, source="mission_schedule", mission_run_id=run_id
                )
                status = "planned"

            if gate_mode == GateMode.AUTONOMOUS:
                for task in await self._tasks.list_by_run(run_id, status=TaskStatus.PROPOSED):
                    await self._plan_svc.approve_task(plan_id, task.id, owner_id)
            task_ids = [t.id for t in await self._tasks.list_by_run(run_id)]
            await self._session.commit()
        except ValidationError as err:
            await self._session.rollback()
            detail = redact_secrets(str(err))
            self._logger.info(
                "Mission run planning failed",
                extra={"mission_run_id": run_id, "session_id": session_id, "detail": detail},
            )
            return PlanRunResult(task_ids=[], status="failed", detail=detail)
        return PlanRunResult(task_ids=task_ids, status=status, detail=None)

    async def task_graph(self, run_id: str) -> RunTaskGraph:
        """Kahn layers over the run's APPROVED tasks, ignoring COMPLETED dependencies."""
        run = await self._runs.get_by_id(run_id)
        tasks = await self._tasks.list_by_run(run_id)
        status_by_id = {t.id: t.status for t in await self._tasks.get_by_plan_id(run.plan_id)}
        approved = [t for t in tasks if t.status == TaskStatus.APPROVED]
        approved_ids = {t.id for t in approved}

        pending: dict[str, set[str]] = {}
        for task in approved:
            deps = {d.depends_on_id for d in task.dependencies}
            blocked = any(
                d not in approved_ids and status_by_id.get(d) != TaskStatus.COMPLETED for d in deps
            )
            if not blocked:
                pending[task.id] = deps & approved_ids
        layers: list[list[str]] = []
        while True:
            layer = [tid for tid, deps in pending.items() if not deps]
            if not layer:
                break
            layers.append(layer)
            for tid in layer:
                del pending[tid]
            for deps in pending.values():
                deps.difference_update(layer)

        return RunTaskGraph(
            layers=layers,
            proposed=sum(1 for t in tasks if t.status == TaskStatus.PROPOSED),
            approved=len(approved),
            running=sum(1 for t in tasks if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)),
        )

    async def finalise(
        self,
        run_id: str,
        status: MissionRunStatus,
        reason: MissionRunStatusReason | None,
        detail: str | None,
    ) -> FinaliseRunResult:
        """End the run: fail in-flight tasks, release the rest, record counts and cost.

        After commit, a raced approval on an AUTONOMOUS plan starts the next run.
        """
        run = await self._runs.get_by_id(run_id)
        mission = await self._missions.get_by_id(run.mission_id)
        plan = await self._plans.get_by_id(run.plan_id)
        owner_id = mission.owner_id
        mission_id = run.mission_id
        plan_id = plan.id
        gate_mode = GateMode(plan.gate_mode)
        sequence = run.sequence

        if status == MissionRunStatus.CANCELLED and run.cancel_reason is not None:
            reason = MissionRunStatusReason(run.cancel_reason)

        failure_reason = reason.value if reason is not None else status.value
        for task in await self._tasks.list_by_run(run_id):
            if task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                task.transition_status(TaskStatus.FAILED)
                task.failure_reason = failure_reason
        await self._session.flush()
        await self._tasks.release_to_backlog(run_id, [TaskStatus.PROPOSED, TaskStatus.APPROVED])

        tasks = await self._tasks.list_by_run(run_id)
        run.task_count = len(tasks)
        run.completed_task_count = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        run.failed_task_count = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        if run.context_version_end is None:
            run.context_version_end = await self._context_version(mission_id)
        cost = await LlmLedgerRepository(self._session).sum_cost(
            mission_id, since=None, until=None, mission_run_id=run_id
        )
        run.cost_usd = cost
        await self.transition(run_id, status, reason, detail)

        await self._start_for_raced_approvals(mission_id, plan_id, gate_mode, owner_id)

        kind = _notification_kind(status, reason)
        notification = None
        if kind is not None:
            notification = NotificationRequest(
                kind=kind,
                mission_id=mission_id,
                mission_run_id=run_id,
                gate_request_id=None,
                subject_id=run_id,
                payload={
                    "sequence": sequence,
                    "status": status.value,
                    "reason": reason.value if reason is not None else None,
                    "detail": detail,
                    "cost_usd": cost,
                },
            )
        return FinaliseRunResult(cost_usd=cost, notification=notification)

    async def _start_for_raced_approvals(
        self, mission_id: str, plan_id: str, gate_mode: GateMode, owner_id: str
    ) -> None:
        """Start the next run when APPROVED backlog arrived while this run was ending."""
        approved = await self._tasks.get_by_plan_id(plan_id, status=TaskStatus.APPROVED)
        if not any(t.mission_run_id is None for t in approved):
            return
        if gate_mode != GateMode.AUTONOMOUS:
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
                user_id=owner_id,
                session_id=None,
            )
        except ConflictError as err:
            self._logger.info(
                "Next run not started after finalise",
                extra={"mission_id": mission_id, "reason": str(err)},
            )
