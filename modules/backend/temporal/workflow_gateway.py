"""Temporal workflow gateway (Plan 88, contract 3.5.1).

TemporalWorkflowGateway is the only module outside workflow code that starts
or holds handles for MissionRunWorkflow, MissionScheduleTickWorkflow,
ReconcilerWorkflow and RetentionWorkflow. Later steps add methods here and
never create another gateway.
"""

import enum

from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.core.logging import get_logger
from modules.backend.temporal.client import get_temporal_client
from modules.backend.temporal.mission_run_models import MissionRunWorkflowInput
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

logger = get_logger(__name__)


class WorkflowState(str, enum.Enum):
    RUNNING = "running"
    CLOSED = "closed"
    NOT_FOUND = "not_found"


class TemporalWorkflowGateway:
    """Owns workflow handles for the Plan 88 workflows."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    async def connect(cls) -> "TemporalWorkflowGateway":
        try:
            client = await get_temporal_client()
        except RuntimeError as exc:
            raise ExternalServiceError(f"Temporal unavailable: {exc}") from exc
        return cls(client)

    def _handle(self, workflow_id: str) -> WorkflowHandle:
        return self._client.get_workflow_handle(workflow_id)

    async def state(self, workflow_id: str) -> WorkflowState:
        try:
            description = await self._handle(workflow_id).describe()
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return WorkflowState.NOT_FOUND
            raise ExternalServiceError(
                f"Temporal describe failed for workflow {workflow_id}: {exc}"
            ) from exc
        if description.status == WorkflowExecutionStatus.RUNNING:
            return WorkflowState.RUNNING
        return WorkflowState.CLOSED

    async def cancel(self, workflow_id: str) -> WorkflowState:
        """Cancel the workflow if running. Returns the pre-cancel state."""
        current = await self.state(workflow_id)
        if current == WorkflowState.RUNNING:
            await self._handle(workflow_id).cancel()
            logger.info("Workflow cancel requested", extra={"workflow_id": workflow_id})
        return current

    async def terminate(self, workflow_id: str, reason: str) -> WorkflowState:
        """Terminate the workflow if running. Returns the pre-terminate state."""
        current = await self.state(workflow_id)
        if current == WorkflowState.RUNNING:
            await self._handle(workflow_id).terminate(reason=reason)
            logger.info(
                "Workflow terminated",
                extra={"workflow_id": workflow_id, "reason": reason},
            )
        return current

    async def signal(self, workflow_id: str, signal: str, arg: object) -> WorkflowState:
        """Signal the workflow; NOT_FOUND when it is missing or closed, RUNNING once delivered."""
        try:
            await self._handle(workflow_id).signal(signal, arg)
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return WorkflowState.NOT_FOUND
            raise ExternalServiceError(
                f"Temporal signal {signal} failed for workflow {workflow_id}: {exc}"
            ) from exc
        logger.info("Workflow signalled", extra={"workflow_id": workflow_id, "signal": signal})
        return WorkflowState.RUNNING

    async def start_mission_run(self, inp: MissionRunWorkflowInput) -> None:
        """Start the run's MissionRunWorkflow; a second start for the same run is rejected."""
        workflow_id = mission_run_workflow_id(inp.mission_run_id)
        try:
            await self._client.start_workflow(
                MissionRunWorkflow.run,
                inp,
                id=workflow_id,
                task_queue=inp.config.task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except (RPCError, WorkflowAlreadyStartedError) as exc:
            raise ExternalServiceError(
                f"Temporal start failed for workflow {workflow_id}: {exc}"
            ) from exc
        logger.info(
            "Mission run workflow started",
            extra={"workflow_id": workflow_id, "mission_run_id": inp.mission_run_id},
        )
