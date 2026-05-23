"""
Tool: halt_workflow

Deliberately halt the current workflow run with status=failed
(Plan 79 §9.2 / S1 fix). Used by gate/verification steps that need to
fail loud rather than silently completing the workflow with no
deliverable.

Implementation: raises RuntimeError. The tool_call dispatcher's
existing exception path explicitly re-raises RuntimeError (see
workflow_run_waves.py exception handler in _execute_tool_call_step),
which then propagates up to the wave executor and triggers
WorkflowRun.status = WorkflowRunState.FAILED (services/workflow_run.py
catches RuntimeError/ValueError/OSError and marks failed).

The user sees the failure in the workflow run record AND can read the
reason in the exception message, which is captured in the
WorkflowToolCallCompletedEvent.
"""

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def halt_workflow(*, reason: str, channel: str = "sse") -> None:
    """Halt the workflow with a clear failure status.

    Args:
        reason: Human-readable explanation of why the workflow is
            halting. Will appear in the run's failure message and the
            tool_call event.
        channel: Notification channel hint (sse / telegram). Stored
            for downstream consumers; the wave engine's
            WorkflowToolCallCompletedEvent already publishes the
            failure to SSE subscribers regardless.

    Raises:
        RuntimeError: Always. The tool_call dispatcher re-raises
            RuntimeError so the run is marked failed rather than
            silently completed.
    """
    logger.warning(
        "halt_workflow invoked — workflow will be marked failed",
        extra={"reason": reason, "channel": channel},
    )
    raise RuntimeError(f"Workflow halted: {reason}")


TOOL_DEF = {
    "name": "halt_workflow",
    "description": (
        "Halt the current workflow run with status=failed. Raises "
        "RuntimeError so the wave engine marks the run as failed "
        "rather than completing it with no deliverable."
    ),
    "category": "workflow",
    "deps": [],
}

_impl = halt_workflow
