"""human_input step executor: Temporal HumanInputWorkflow bridge.

Split out of workflow_run_waves.py (Plan 84 Phase 5.1). Takes the owning
WorkflowRunWavesMixin instance (`mixin`) as an explicit first argument
to reach `_publish_workflow_event` — a pure move, no behavior change.
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    WorkflowHumanInputRequestedEvent,
    WorkflowHumanInputRespondedEvent,
)
from modules.backend.services.workflow_run_steps.helpers import VirtualExecution

if TYPE_CHECKING:
    from modules.backend.models.workflow_run import WorkflowRun
    from modules.backend.schemas.workflow import WorkflowStepSchema
    from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin

logger = get_logger(__name__)


async def execute_human_input_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Start a HumanInputWorkflow in Temporal and await its result."""
    from uuid import uuid4

    from modules.backend.core.config import get_app_config
    from modules.backend.services.condition_evaluator import resolve_template
    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.human_input_models import (
        HumanInputResult,
        HumanInputWorkflowInput,
    )
    from modules.backend.temporal.human_input_workflow import HumanInputWorkflow

    config = step.human_input_config
    prompt_template = config.prompt_message if config else ""
    prompt = resolve_template(prompt_template, completed_outcomes, run.context)

    # Resolve timeout: step config > default 4h
    if config and config.timeout_hours:
        timeout_seconds = int(config.timeout_hours * 3600)
    else:
        app_config = get_app_config()
        timeout_seconds = getattr(app_config.temporal, "approval_timeout_seconds", 14400)

    request_id = str(uuid4())
    temporal_wf_id = f"human-input-{run.id}-{step.id}"

    wf_input = HumanInputWorkflowInput(
        request_id=request_id,
        workflow_run_id=run.id,
        step_id=step.id,
        mission_id=run.mission_id or "",
        session_id=run.session_id or "",
        prompt_message=prompt,
        channel=config.channel if config else "telegram",
        timeout_seconds=timeout_seconds,
        default_response=config.default_response if config else None,
        choices=config.choices or [] if config else [],
    )

    client = await get_temporal_client()

    # Start workflow with deterministic ID (idempotent across retries)
    from temporalio.service import RPCError

    try:
        handle = await client.start_workflow(
            HumanInputWorkflow.run,
            wf_input,
            id=temporal_wf_id,
            task_queue=get_app_config().temporal.task_queue,
        )
    except RPCError:
        # Already started (crash recovery) — reconnect
        handle = client.get_workflow_handle(temporal_wf_id)

    logger.info(
        "HumanInputWorkflow started, awaiting response",
        extra={
            "step_id": step.id,
            "temporal_wf_id": temporal_wf_id,
            "timeout_s": timeout_seconds,
        },
    )

    # Notify frontend that we're waiting for human input
    from datetime import timedelta

    from modules.backend.core.utils import utc_now

    timeout_at = (utc_now() + timedelta(seconds=timeout_seconds)).isoformat()
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowHumanInputRequestedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            request_id=request_id,
            prompt_message=prompt,
            channel=wf_input.channel,
            choices=wf_input.choices,
            timeout_at=timeout_at,
        ),
    )

    # Block until human responds or timeout
    result: HumanInputResult = await handle.result()

    if result.timed_out and not (config and config.default_response):
        raise RuntimeError(f"Human input step '{step.id}' timed out with no default response")

    logger.info(
        "Human input received",
        extra={
            "step_id": step.id,
            "timed_out": result.timed_out,
            "response_len": len(result.response),
        },
    )

    # Notify frontend that human has responded
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowHumanInputRespondedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            request_id=request_id,
            response=result.response,
            responder_id=result.responder_id or "",
            timed_out=result.timed_out,
        ),
    )

    outputs = {
        "response": result.response,
        "timed_out": result.timed_out,
        "responder_id": result.responder_id,
    }
    return VirtualExecution(id=step.id), outputs
