"""sub_workflow step executor: invoke a named child workflow and await it.

Split out of workflow_run_waves.py (Plan 84 Phase 5.1). Takes the owning
WorkflowRunWavesMixin instance (`mixin`) as an explicit first argument
to reach `_publish_workflow_event` and `run_workflow_from_definition`
(defined on WorkflowRunService itself) — a pure move, no behavior change.
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING, Any

from modules.backend.core.logging import get_logger
from modules.backend.events.types import WorkflowSubWorkflowCompletedEvent
from modules.backend.services.workflow_run_steps.helpers import StepContext, VirtualExecution

if TYPE_CHECKING:
    from modules.backend.models.workflow_run import WorkflowRun
    from modules.backend.schemas.workflow import WorkflowStepSchema
    from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin

logger = get_logger(__name__)


async def execute_sub_workflow_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    session_id: str,
    completed_outcomes: dict[str, dict],
    ctx: StepContext,
) -> tuple[VirtualExecution, dict]:
    """Invoke another saved workflow as a child and await its completion."""
    config = step.sub_workflow_config
    if not config:
        raise RuntimeError(f"sub_workflow_config missing for step '{step.id}'")

    # Depth guard — prevent unbounded recursion
    parent_depth = (run.context or {}).get("_sub_workflow_depth", 0)
    if parent_depth >= config.max_depth:
        raise RuntimeError(
            f"Sub-workflow depth limit reached ({config.max_depth}) at step '{step.id}'"
        )

    # Build child context
    child_context: dict[str, Any] = {"_sub_workflow_depth": parent_depth + 1}
    if config.pass_context:
        child_context.update(run.context or {})
        child_context["_sub_workflow_depth"] = parent_depth + 1

    logger.info(
        "Starting sub-workflow",
        extra={
            "step_id": step.id,
            "run_id": run.id,
            "child_workflow_id": config.workflow_id,
            "depth": parent_depth + 1,
        },
    )

    child_run = await mixin.run_workflow_from_definition(
        workflow_definition_id=config.workflow_id,
        mission_id=run.mission_id,
        triggered_by=f"sub_workflow:{step.id}",
        context_overrides=child_context,
    )

    child_status = child_run.status if isinstance(child_run.status, str) else child_run.status.value
    success = child_status.upper() != "FAILED"

    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowSubWorkflowCompletedEvent(
            session_id=_uuid.UUID(session_id),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            child_run_id=child_run.id,
            success=success,
            child_cost_usd=child_run.total_cost_usd,
        ),
    )

    outputs = {
        "child_run_id": child_run.id,
        "status": child_status,
        "result_summary": child_run.result_summary or "",
        "total_cost_usd": child_run.total_cost_usd,
    }

    if not success:
        raise RuntimeError(
            f"Sub-workflow step '{step.id}' child run failed: {child_run.error_data}"
        )

    return VirtualExecution(id=step.id, total_cost_usd=child_run.total_cost_usd), outputs
