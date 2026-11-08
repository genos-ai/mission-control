"""Execution cancellation (Plan 88, step 88.0.9).

Cancelling an execution record or a workflow run reaches Temporal first, then
marks the row cancelled. If Temporal is unavailable, ExternalServiceError
propagates and the row is left untouched.

A record whose workflow id is mission-run-{plan_id} cancels the whole mission
run; that is intended.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.models.execution_record import ExecutionRecord, ExecutionRecordStatus
from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState
from modules.backend.repositories.execution_record import ExecutionRecordRepository
from modules.backend.repositories.workflow_run import WorkflowRunRepository
from modules.backend.services.base import BaseService
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.workflow_run import WorkflowRunService
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway

logger = get_logger(__name__)

_TERMINAL_EXECUTION = frozenset(
    {
        ExecutionRecordStatus.COMPLETED,
        ExecutionRecordStatus.FAILED,
        ExecutionRecordStatus.CANCELLED,
        ExecutionRecordStatus.TIMED_OUT,
    }
)
_TERMINAL_RUN = frozenset(
    {
        WorkflowRunState.COMPLETED,
        WorkflowRunState.FAILED,
        WorkflowRunState.CANCELLED,
    }
)


class ExecutionCancellationService(BaseService):
    """Cancels execution records and workflow runs, reaching Temporal first."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._record_repo = ExecutionRecordRepository(session)
        self._run_repo = WorkflowRunRepository(session)

    async def _cancel_temporal(self, workflow_id: str | None) -> bool:
        """End the read transaction, then cancel the workflow. Returns True if a cancel was sent."""
        await self._session.commit()
        if workflow_id is None:
            return False
        gateway = await TemporalWorkflowGateway.connect()
        await gateway.cancel(workflow_id)
        return True

    async def cancel_execution(
        self, execution_id: str, *, user_id: str, reason: str
    ) -> tuple[ExecutionRecord, bool, bool]:
        """Cancel an execution record. Returns (row, changed, temporal_cancelled).

        Caller commits.
        """
        record = await self._record_repo.get_by_id(execution_id)
        if ExecutionRecordStatus(record.status) in _TERMINAL_EXECUTION:
            return record, False, False

        workflow_id = record.temporal_workflow_id
        temporal_cancelled = await self._cancel_temporal(workflow_id)

        record = await ExecutionPersistenceService(self._session).complete_execution(
            execution_record_id=execution_id,
            status=ExecutionRecordStatus.CANCELLED.value,
        )
        logger.info(
            "Execution cancelled",
            extra={
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "temporal_cancelled": temporal_cancelled,
                "user_id": user_id,
                "reason": reason,
            },
        )
        return record, True, temporal_cancelled

    async def cancel_workflow_run(
        self, mission_id: str, run_id: str, *, user_id: str
    ) -> tuple[WorkflowRun, bool, bool]:
        """Cancel a workflow run of a mission. Returns (row, changed, temporal_cancelled).

        Raises NotFoundError when the run does not exist in the mission. Caller commits.
        """
        run = await self._run_repo.get_by_id_or_none(run_id)
        if run is None or run.mission_id != mission_id:
            raise NotFoundError(f"Workflow run {run_id} not found in mission {mission_id}")
        if WorkflowRunState(run.status) in _TERMINAL_RUN:
            return run, False, False

        workflow_id: str | None = None
        if run.execution_record_id is not None:
            linked = await self._record_repo.get_by_id_or_none(run.execution_record_id)
            if linked is not None:
                workflow_id = linked.temporal_workflow_id
        temporal_cancelled = await self._cancel_temporal(workflow_id)

        run, changed = await WorkflowRunService(self._session).cancel_run(
            run_id, mission_id=mission_id
        )
        logger.info(
            "Workflow run cancelled",
            extra={
                "mission_id": mission_id,
                "run_id": run_id,
                "workflow_id": workflow_id,
                "temporal_cancelled": temporal_cancelled,
                "user_id": user_id,
            },
        )
        return run, changed, temporal_cancelled
