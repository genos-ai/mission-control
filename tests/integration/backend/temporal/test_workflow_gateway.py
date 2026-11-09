"""TemporalWorkflowGateway.start_mission_run against a local dev server (Plan 88 step 88.1.7)."""

import dataclasses
from uuid import uuid4

import pytest
from temporalio.testing import WorkflowEnvironment

from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.temporal.config_snapshots import build_run_config_snapshot
from modules.backend.temporal.mission_run_models import MissionRunWorkflowInput
from modules.backend.temporal.workflow_gateway import TemporalWorkflowGateway, WorkflowState
from modules.backend.temporal.workflow_ids import mission_run_workflow_id

# No worker polls this queue, so the started workflow only waits to be terminated.
_QUEUE = "p88-workflow-gateway-test"


async def test_start_mission_run_rejects_duplicate(temporal_env: WorkflowEnvironment) -> None:
    gateway = TemporalWorkflowGateway(temporal_env.client)
    config = dataclasses.replace(build_run_config_snapshot(), task_queue=_QUEUE)
    inp = MissionRunWorkflowInput(
        mission_run_id=str(uuid4()), mission_id=str(uuid4()), plan_id=str(uuid4()), config=config
    )
    workflow_id = mission_run_workflow_id(inp.mission_run_id)
    try:
        await gateway.start_mission_run(inp)
        assert await gateway.state(workflow_id) == WorkflowState.RUNNING
        with pytest.raises(ExternalServiceError):
            await gateway.start_mission_run(inp)
    finally:
        await gateway.terminate(workflow_id, "test cleanup")
