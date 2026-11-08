"""Run reconciliation (Plan 88 step 88.0.10, contract 3.5.1).

Fails tasks, execution records and workflow runs whose Temporal workflow is
gone. Replaces the API-startup reconcilers, which failed every in-flight row
without asking Temporal. Runs periodically in the worker via
ReconcilerWorkflow.

The pass runs in strict order: collect candidates and commit, resolve every
Temporal state (one describe per workflow id), decide, then write in one
transaction that re-selects the orphans with FOR UPDATE SKIP LOCKED and the
same predicates. Temporal unreachable means nothing is written and
ExternalServiceError propagates, so the activity retries.

Rows with no Temporal id (CLI, TUI and other in-process work) are never
selected; tasks owned by an in-process workflow run are left alone.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.events.bus import SessionEventBus
from modules.backend.events.types import (
    MissionPlanTaskStatusChangedEvent,
    SessionEvent,
    WorkflowRunFailedEvent,
)
from modules.backend.models.execution_record import ExecutionRecordStatus
from modules.backend.models.task import TaskStatus
from modules.backend.models.workflow_run import WorkflowRunState
from modules.backend.repositories.execution_record import ExecutionRecordRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.services.base import BaseService
from modules.backend.temporal.mission_run_models import ReconcileStats
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

RECONCILER_ACTOR = "system:reconciler"
_SOURCE = "run_reconciliation"


@dataclass
class _TaskRow:
    id: str
    plan_id: str
    mission_id: str


@dataclass
class _RecordRow:
    id: str
    workflow_id: str | None  # resolved; None means in-process


@dataclass
class _RunRow:
    id: str
    mission_id: str | None
    session_id: str | None
    workflow_name: str
    total_cost_usd: float
    workflow_id: str | None  # never None given the repository join; None means in-process


@dataclass
class _ActiveRun:
    status: WorkflowRunState
    workflow_id: str | None  # None means in-process


@dataclass
class _Orphan:
    id: str
    workflow_id: str
    state: WorkflowState


class RunReconciliationService(BaseService):
    """Temporal-aware reconciler for in-flight execution rows."""

    def __init__(
        self,
        session: AsyncSession,
        gateway: TemporalWorkflowGateway,
        event_bus: SessionEventBus | None,
    ) -> None:
        super().__init__(session)
        self._gateway = gateway
        self._event_bus = event_bus
        self._tasks = TaskRepository(session)
        self._records = ExecutionRecordRepository(session)
        self._runs = WorkflowRunRepository(session)
        self._states: dict[str, WorkflowState] = {}

    async def reconcile(self, orphan_grace_seconds: int) -> ReconcileStats:
        cutoff = utc_now() - timedelta(seconds=orphan_grace_seconds)
        self._states = {}

        # ── Collect ──────────────────────────────────────────────────────
        tasks, records, runs, active = await self._collect(cutoff)
        await self._session.commit()

        stats = ReconcileStats(
            examined_tasks=len(tasks),
            examined_execution_records=len(records),
            examined_workflow_runs=len(runs),
            failed_tasks=0,
            failed_execution_records=0,
            failed_workflow_runs=0,
            left_running=0,
            left_in_process=0,
            schedule_sync=None,
        )

        # ── Resolve and decide (every Temporal call happens here) ────────
        orphan_records: list[_Orphan] = []
        for rec in records:
            if rec.workflow_id is None:
                stats.left_in_process += 1
                continue
            state = await self._state(rec.workflow_id)
            if state == WorkflowState.RUNNING:
                stats.left_running += 1
            else:
                orphan_records.append(_Orphan(rec.id, rec.workflow_id, state))

        orphan_runs: list[_Orphan] = []
        for run in runs:
            if run.workflow_id is None:
                stats.left_in_process += 1
                continue
            state = await self._state(run.workflow_id)
            if state == WorkflowState.RUNNING:
                stats.left_running += 1
            else:
                orphan_runs.append(_Orphan(run.id, run.workflow_id, state))

        orphan_tasks: list[_Orphan] = []
        for task in tasks:
            plan_wid = mission_run_workflow_id(task.plan_id)
            mission_runs = active.get(task.mission_id, [])
            if await self._task_live(plan_wid, mission_runs):
                stats.left_running += 1
            elif any(r.workflow_id is None for r in mission_runs):
                stats.left_in_process += 1
            else:
                orphan_tasks.append(_Orphan(task.id, plan_wid, self._states[plan_wid]))

        # ── Write (one transaction) ──────────────────────────────────────
        events = await self._write(cutoff, orphan_tasks, orphan_records, orphan_runs, runs, stats)
        await self._session.commit()

        self._logger.info(
            "Run reconciliation complete",
            extra={
                "examined_tasks": stats.examined_tasks,
                "examined_execution_records": stats.examined_execution_records,
                "examined_workflow_runs": stats.examined_workflow_runs,
                "failed_tasks": stats.failed_tasks,
                "failed_execution_records": stats.failed_execution_records,
                "failed_workflow_runs": stats.failed_workflow_runs,
                "left_running": stats.left_running,
                "left_in_process": stats.left_in_process,
            },
        )

        # ── Emit (after commit, best-effort) ─────────────────────────────
        await self._emit(events)
        return stats

    async def _collect(
        self, cutoff: datetime
    ) -> tuple[list[_TaskRow], list[_RecordRow], list[_RunRow], dict[str, list[_ActiveRun]]]:
        record_wids: dict[str, str | None] = {}

        async def record_wid(execution_record_id: str | None) -> str | None:
            if execution_record_id is None:
                return None
            if execution_record_id not in record_wids:
                rec = await self._records.get_by_id_or_none(execution_record_id)
                record_wids[execution_record_id] = rec.temporal_workflow_id if rec else None
            return record_wids[execution_record_id]

        async def run_wid(workflow_run_id: str) -> str | None:
            run = await self._runs.get_by_id_or_none(workflow_run_id)
            return await record_wid(run.execution_record_id) if run else None

        tasks = [
            _TaskRow(t.id, t.plan_id, t.mission_id)
            for t in await self._tasks.list_in_flight_older_than(cutoff)
        ]

        records: list[_RecordRow] = []
        for rec in await self._records.list_in_flight_older_than(cutoff):
            wid = rec.temporal_workflow_id
            if wid is None:
                wid = await run_wid(rec.workflow_run_id)
            records.append(_RecordRow(rec.id, wid))

        runs: list[_RunRow] = []
        for run in await self._runs.list_in_flight_older_than(cutoff):
            wid = await record_wid(run.execution_record_id)
            runs.append(
                _RunRow(
                    id=run.id,
                    mission_id=run.mission_id,
                    session_id=run.session_id,
                    workflow_name=run.workflow_name,
                    total_cost_usd=run.total_cost_usd,
                    workflow_id=wid,
                )
            )

        active: dict[str, list[_ActiveRun]] = {}
        for mission_id in {t.mission_id for t in tasks}:
            active[mission_id] = [
                _ActiveRun(WorkflowRunState(r.status), await record_wid(r.execution_record_id))
                for r in await self._runs.list_active_for_mission(mission_id)
            ]
        return tasks, records, runs, active

    async def _state(self, workflow_id: str) -> WorkflowState:
        if workflow_id not in self._states:
            self._states[workflow_id] = await self._gateway.state(workflow_id)
        return self._states[workflow_id]

    async def _task_live(self, plan_wid: str, mission_runs: list[_ActiveRun]) -> bool:
        if await self._state(plan_wid) == WorkflowState.RUNNING:
            return True
        for run in mission_runs:
            if run.status == WorkflowRunState.AWAITING_INPUT:
                return True
            if run.workflow_id is not None and await self._state(run.workflow_id) == (
                WorkflowState.RUNNING
            ):
                return True
        return False

    async def _write(
        self,
        cutoff: datetime,
        orphan_tasks: list[_Orphan],
        orphan_records: list[_Orphan],
        orphan_runs: list[_Orphan],
        runs: list[_RunRow],
        stats: ReconcileStats,
    ) -> list[tuple[str, SessionEvent]]:
        events: list[tuple[str, SessionEvent]] = []
        now = utc_now()

        if orphan_tasks:
            by_id = {o.id: o for o in orphan_tasks}
            for task in await self._tasks.list_in_flight_older_than(
                cutoff, ids=by_id, for_update=True
            ):
                orphan = by_id[task.id]
                from_status = TaskStatus(task.status)
                task.transition_status(TaskStatus.FAILED)
                task.failure_reason = (
                    f"orphaned: workflow {orphan.workflow_id} {orphan.state.value}"
                )[:500]
                task.last_attempt_at = now
                stats.failed_tasks += 1
                events.append(
                    (
                        task.mission_id,
                        MissionPlanTaskStatusChangedEvent(
                            session_id=uuid.uuid4(),
                            source=_SOURCE,
                            mission_id=task.mission_id,
                            plan_id=task.plan_id,
                            task_id=task.id,
                            from_status=from_status.value,
                            to_status=TaskStatus.FAILED.value,
                            actor=RECONCILER_ACTOR,
                        ),
                    )
                )

        if orphan_records:
            ids = {o.id for o in orphan_records}
            for rec in await self._records.list_in_flight_older_than(
                cutoff, ids=ids, for_update=True
            ):
                rec.status = ExecutionRecordStatus.FAILED
                rec.completed_at = now
                stats.failed_execution_records += 1

        if orphan_runs:
            by_id = {o.id: o for o in orphan_runs}
            run_rows = {r.id: r for r in runs}
            for run in await self._runs.list_in_flight_older_than(
                cutoff, ids=by_id, for_update=True
            ):
                orphan = by_id[run.id]
                message = f"workflow {orphan.workflow_id} {orphan.state.value}"
                run.status = WorkflowRunState.FAILED
                run.completed_at = now
                run.error_data = {"type": "OrphanedWorkflow", "message": message}
                stats.failed_workflow_runs += 1
                row = run_rows[run.id]
                if row.mission_id:
                    events.append(
                        (
                            row.mission_id,
                            WorkflowRunFailedEvent(
                                session_id=(
                                    uuid.UUID(row.session_id) if row.session_id else uuid.uuid4()
                                ),
                                source=_SOURCE,
                                workflow_run_id=row.id,
                                workflow_name=row.workflow_name,
                                error=message,
                                total_cost_usd=row.total_cost_usd,
                            ),
                        )
                    )

        await self._session.flush()
        return events

    async def _emit(self, events: list[tuple[str, SessionEvent]]) -> None:
        if self._event_bus is None:
            return
        for mission_id, event in events:
            try:
                await self._event_bus.publish_to_mission(mission_id, event)
            except Exception as exc:  # noqa: BLE001
                # best-effort — this IS the event-emission path; the rows are
                # already committed and there is nowhere further to escalate to.
                self._logger.warning(
                    "Reconciler: failed to publish event",
                    extra={
                        "mission_id": mission_id,
                        "event_type": event.event_type,
                        "error": str(exc),
                    },
                )
