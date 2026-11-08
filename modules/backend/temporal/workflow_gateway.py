"""Temporal workflow gateway (Plan 88, contract 3.5.1).

TemporalWorkflowGateway is the only module outside workflow code that starts
or holds handles for MissionRunWorkflow, MissionScheduleTickWorkflow,
ReconcilerWorkflow and RetentionWorkflow. Later steps add methods here and
never create another gateway.
"""

import enum

from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle
from temporalio.service import RPCError, RPCStatusCode

from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.core.logging import get_logger
from modules.backend.temporal.client import get_temporal_client

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
