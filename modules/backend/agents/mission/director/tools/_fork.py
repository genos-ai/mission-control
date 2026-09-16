"""Shared helpers for Director tools that fork work into Temporal.

`run_workflow` and `design_workflow` both create an execution record and
start a durable workflow, then return immediately so the Director can
keep talking to the user (Plan 56 Phase B). Moved here from
tools_workflow.py when that became a registration-only module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Maps the workflow name a tool asks for to its Temporal run method.
_FORK_WORKFLOWS = ("DesignWorkflowWorkflow", "RunWorkflowWorkflow")


@dataclass(frozen=True)
class BackgroundRecordRef:
    """The id of a created execution record.

    Only the id survives: the ORM instance is detached once the service's
    session commits, so returning it would give callers an object whose
    attribute access raises.
    """

    id: str


async def create_background_record(
    *,
    mission_id: str,
    session_id: str,
    task_type: str,
    objective: str,
    params: dict,
) -> BackgroundRecordRef:
    """Create an ExecutionRecord for a background task via the service layer.

    Args:
        mission_id: Mission the task belongs to.
        session_id: Transport session that requested it (P15).
        task_type: Discriminator, e.g. "run_workflow" or "design_workflow".
        objective: Human-readable summary of the work.
        params: Tool arguments, persisted for replay and debugging.

    Returns:
        A reference carrying the new record's id.
    """
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    async with ExecutionPersistenceService.factory() as svc:
        record = await svc.create_background_record(
            mission_id=mission_id,
            session_id=session_id,
            task_type=task_type,
            objective=objective,
            params=params,
        )
        record_id = record.id

    return BackgroundRecordRef(record_id)


def build_fork_workflow_id(workflow_name: str, record_id: str) -> str:
    """Build the Temporal workflow id for a forked tool call.

    Deterministic in its inputs apart from the random suffix, which keeps
    repeated forks of the same record distinct.
    """
    return f"tool-fork-{workflow_name.lower()}-{record_id[:12]}-{uuid.uuid4().hex[:8]}"


async def start_tool_fork_workflow(
    *,
    workflow_name: str,
    input_data: Any,
    record_id: str,
) -> str:
    """Start a Temporal workflow for a forked tool call.

    Args:
        workflow_name: One of `_FORK_WORKFLOWS`.
        input_data: The workflow's typed input dataclass.
        record_id: Execution record to stamp with the workflow id.

    Returns:
        The started workflow's id.
    """
    from modules.backend.services.execution_persistence import ExecutionPersistenceService
    from modules.backend.temporal.client import get_temporal_client, get_temporal_config
    from modules.backend.temporal.tool_fork_workflow import (
        DesignWorkflowWorkflow,
        RunWorkflowWorkflow,
    )

    workflow_map = {
        "DesignWorkflowWorkflow": DesignWorkflowWorkflow.run,
        "RunWorkflowWorkflow": RunWorkflowWorkflow.run,
    }

    run_method = workflow_map[workflow_name]
    client = await get_temporal_client()
    config = get_temporal_config()

    workflow_id = build_fork_workflow_id(workflow_name, record_id)
    await client.start_workflow(
        run_method,
        input_data,
        id=workflow_id,
        task_queue=config.task_queue,
    )

    # Stamp the record so check_background_tasks can correlate it.
    async with ExecutionPersistenceService.factory() as svc:
        record = await svc.get_execution(record_id)
        if record is not None:
            record.temporal_workflow_id = workflow_id

    return workflow_id
