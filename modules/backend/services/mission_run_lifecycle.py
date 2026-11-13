"""MissionRunService workflow-activity methods (Plan 88, 88.1.7; digest payload 88.3.8).

begin, plan, approve_proposed, task_graph and finalise, extracted from
mission_run.py to keep it under 500 lines. Every stored exception text goes
through redact_secrets.

Mixed into MissionRunService; do not instantiate directly. Methods use the
repositories, _plan_svc, _event_bus, transition, start_run, _is_platform_user
and _contexts that MissionRunService defines.
"""

from modules.backend.core.exceptions import (
    ConflictError,
    MissionRunStateError,
    NotFoundError,
    RunStartRejectedError,
    ValidationError,
)
from modules.backend.core.failure_classification import get_failure_classifier
from modules.backend.core.redaction import redact_secrets
from modules.backend.core.utils import utc_now
from modules.backend.models.execution_record import ExecutionRecordStatus
from modules.backend.models.mission import MissionStatus
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.mission_run import (
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_run_digest import DigestGenerator
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.llm_ledger import LlmLedgerRepository
from modules.backend.repositories.workflow_definition import (
    WorkflowDefinitionRepository,
)
from modules.backend.schemas.session import SessionCreate
from modules.backend.schemas.task_failure import FailureClass
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator
from modules.backend.services.mission_plan_taskio import assert_run_local_dependencies
from modules.backend.services.run_memory import RunMemoryService
from modules.backend.services.session import SessionService
from modules.backend.services.workflow_run import WorkflowRunService
from modules.backend.services.workflow_task_mapping import steps_to_task_definitions
from modules.backend.temporal.mission_run_models import (
    BeginRunResult,
    FinaliseRunResult,
    NotificationRequest,
    PlanRunResult,
    RunTaskGraph,
)
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

_RUNNABLE_GATE_MODES = frozenset({GateMode.MANUAL, GateMode.AI_ASSISTED, GateMode.AUTONOMOUS})
_OWNER_NOT_USER = "owner not a platform user"
_ORPHAN_REASONS = frozenset(
    {
        MissionRunStatusReason.ORPHANED_WORKFLOW_CLOSED,
        MissionRunStatusReason.ORPHANED_WORKFLOW_NOT_FOUND,
    }
)
# NotificationKind values (contract 3.6.2); the enum arrives in 88.4.3.
RUN_SUCCEEDED = "run_succeeded"
RUN_FAILED = "run_failed"
BUDGET_PAUSED = "budget_paused"


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


class MissionRunLifecycleMixin:
    """Workflow-activity methods of MissionRunService."""

    async def begin(self, run_id: str) -> BeginRunResult:
        """PENDING to RUNNING with a session, one ExecutionRecord and adopted backlog.

        Idempotent: a RUNNING run returns its stored values. The run row is
        locked before the backlog is adopted, in the order finalise and a
        refine's reconcile use.
        """
        found = await self._runs.get_by_id(run_id)
        run = await self._runs.lock_current(found.mission_id, run_id)
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
        context_version_start = await self._contexts.get_version(mission_id)

        run.gate_mode = gate_mode
        run.budget_cap_usd = plan.budget_per_run_usd
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
                prompt = await self._planning_prompt(run_id, objective)
                await orchestrator.refine(plan_id, prompt, owner_id, mission_run_id=run_id)
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

            await assert_run_local_dependencies(self._tasks, run_id)
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

    async def _planning_prompt(self, run_id: str, objective: str) -> str:
        """The objective, preceded by the run memory brief when an earlier run exists (88.3.5)."""
        run_memory = RunMemoryService(self._session)
        brief = run_memory.render_planning_brief(await run_memory.build_context_packet(run_id))
        return brief + "\n\n## Objective\n" + objective if brief else objective

    async def approve_proposed(self, run_id: str) -> int:
        """Approve the run's PROPOSED tasks as the mission owner when the run is AUTONOMOUS.

        Returns the number of tasks approved; 0 in any other gate mode. Commits.
        """
        run = await self._runs.get_by_id(run_id)
        if run.gate_mode is None or GateMode(run.gate_mode) != GateMode.AUTONOMOUS:
            return 0
        mission = await self._missions.get_by_id(run.mission_id)
        owner_id = mission.owner_id
        plan_id = run.plan_id
        approved: set[str] = set()
        for task in await self._tasks.list_by_run(run_id, status=TaskStatus.PROPOSED):
            transitioned = await self._plan_svc.approve_task(plan_id, task.id, owner_id)
            approved.update(t.id for t in transitioned)
        await self._session.commit()
        return len(approved)

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
        director_objective_met: str | None = None,
    ) -> FinaliseRunResult:
        """End the run: fail in-flight tasks, release the rest, record counts and cost.

        After commit, a raced approval on an AUTONOMOUS plan starts the next run.
        The run row is locked first, so a concurrent refine either commits its
        new tasks before they are released or sees the run ended.

        ``director_objective_met`` is the Director's reason when the run ends
        SUCCEEDED (OBJECTIVE_MET) on its declaration; the decision is recorded
        in the same commit as the run's end.

        Raises:
            ValidationError: director_objective_met with any other outcome.
            NotFoundError: director_objective_met and the run has no ExecutionRecord.
        """
        if director_objective_met is not None and (
            status != MissionRunStatus.SUCCEEDED or reason != MissionRunStatusReason.OBJECTIVE_MET
        ):
            raise ValidationError(
                "A Director objective-met decision needs a SUCCEEDED (OBJECTIVE_MET) end, "
                f"not {status.value} ({reason.value if reason is not None else None})"
            )
        found = await self._runs.get_by_id(run_id)
        run = await self._runs.lock_current(found.mission_id, run_id)
        mission = await self._missions.get_by_id(run.mission_id)
        plan = await self._plans.get_by_id(run.plan_id)
        owner_id = mission.owner_id
        mission_id = run.mission_id
        plan_id = plan.id
        gate_mode = GateMode(plan.gate_mode)
        sequence = run.sequence

        reason = run.end_reason(status, reason)

        failure_reason = reason.value if reason is not None else status.value
        classifier = get_failure_classifier()
        if reason in _ORPHAN_REASONS:
            failure = classifier.orphaned(detail or failure_reason)
        else:
            failure = classifier.control(FailureClass.RUN_ABORTED, failure_reason)
        for task in await self._tasks.list_by_run(run_id):
            if task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                task.transition_status(TaskStatus.FAILED)
                self._tasks.set_failure(task, failure)
        await self._session.flush()
        await self._tasks.release_to_backlog(run_id, [TaskStatus.PROPOSED, TaskStatus.APPROVED])

        tasks = await self._tasks.list_by_run(run_id)
        run.task_count = len(tasks)
        run.completed_task_count = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        run.failed_task_count = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        if run.context_version_end is None:
            run.context_version_end = await self._contexts.get_version(mission_id)
        cost = await LlmLedgerRepository(self._session).sum_cost(
            mission_id, since=None, until=None, mission_run_id=run_id
        )
        run.cost_usd = cost
        # Per-task execution (88.2.6) never completes the record through
        # persist_mission_results, so the run's ledger total is written here.
        record = await self._records.get_by_mission_run(run_id)
        if record is not None:
            record.total_cost_usd = cost
        if director_objective_met is not None:
            if record is None:
                raise NotFoundError(f"Mission run {run_id} has no execution record")
            await self._record_director_objective_met(run, record.id, director_objective_met)
        await self.transition(run_id, status, reason, detail)

        await self._start_for_raced_approvals(mission_id, plan_id, gate_mode, owner_id)

        kind = _notification_kind(status, reason)
        notification = None
        if kind is not None:
            payload = {
                "sequence": sequence,
                "status": status.value,
                "reason": reason.value if reason is not None else None,
                "detail": detail,
                "cost_usd": cost,
            }
            if kind in (RUN_SUCCEEDED, RUN_FAILED):
                payload |= await self._digest_payload(mission_id, run_id)
            notification = NotificationRequest(
                kind=kind,
                mission_id=mission_id,
                mission_run_id=run_id,
                gate_request_id=None,
                subject_id=run_id,
                payload=payload,
            )
        return FinaliseRunResult(cost_usd=cost, notification=notification)

    async def _digest_payload(self, mission_id: str, run_id: str) -> dict:
        """The digest's generator and summary for the run-finished notification (3.1.7).

        Both are None when the run has no digest (it never reached RUNNING).
        The summary is already at most missions.digest.summary_max_chars.
        """
        digest = await RunMemoryService(self._session).get_digest(mission_id, run_id)
        if digest is None:
            return {"digest_generator": None, "digest_summary": None}
        return {
            "digest_generator": DigestGenerator(digest.generator).value,
            "digest_summary": digest.summary,
        }

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
