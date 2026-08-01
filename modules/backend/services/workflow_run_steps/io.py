"""I/O step executors: notification, tool_call, llm_call node types.

Split out of workflow_run_waves.py (Plan 84 Phase 5.1). Each function
takes the owning WorkflowRunWavesMixin instance (`mixin`) as an explicit
first argument to reach `_publish_workflow_event` and the mixin's other
instance state — a pure move, no behavior change.
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    WorkflowLlmCallCompletedEvent,
    WorkflowNotificationSentEvent,
    WorkflowToolCallCompletedEvent,
)
from modules.backend.services.workflow_run_steps.helpers import VirtualExecution, extract_run_cost

if TYPE_CHECKING:
    from modules.backend.models.workflow_run import WorkflowRun
    from modules.backend.schemas.workflow import WorkflowStepSchema
    from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin

logger = get_logger(__name__)


async def execute_notification_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Send a notification via the configured channel."""
    from modules.backend.services.condition_evaluator import resolve_template
    from modules.backend.services.run_notifier import _dispatch_to_channels

    config = step.notification_config
    channel = config.channel if config else "sse"
    template = config.message_template if config else ""

    message = resolve_template(template, completed_outcomes, run.context)
    title = f"Workflow notification: {step.id}"

    try:
        await _dispatch_to_channels(
            [channel],
            title,
            message,
            "info",
            {"mission_id": run.mission_id, "run_id": run.id},
        )
        success = True
    except Exception:
        # Catch-all justified: wraps an external notification dispatch
        # whose failure modes are unbounded (network, auth, service
        # down). best-effort — the step continues with success=False,
        # which is reported via the unconditional
        # WorkflowNotificationSentEvent below.
        logger.warning("Notification step failed", extra={"step_id": step.id}, exc_info=True)
        success = False

    logger.info(
        "Notification sent", extra={"step_id": step.id, "channel": channel, "success": success}
    )
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowNotificationSentEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            channel=channel,
            success=success,
        ),
    )
    outputs = {"sent": success, "channel": channel}
    return VirtualExecution(id=step.id), outputs


async def execute_tool_call_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Invoke a registered tool directly without an agent wrapper."""
    from modules.backend.services.condition_evaluator import resolve_template, walk_refs
    from modules.backend.tools.registry import get_tool_registry

    config = step.tool_call_config
    tool_name = config.tool_name if config else ""
    tool_args = dict(config.tool_args) if config else {}

    registry = get_tool_registry()
    if not registry.has(tool_name):
        raise RuntimeError(f"Tool '{tool_name}' not found in registry (step '{step.id}')")

    tool_info = registry.get(tool_name)
    tool_mod = tool_info["module"]
    impl = getattr(tool_mod, "_impl", None)
    if impl is None:
        raise RuntimeError(f"Tool '{tool_name}' has no _impl function (step '{step.id}')")

    # Plan 79 §8.4 — deep-resolve refs in tool_args. Walks nested dicts
    # and lists so structured args (e.g. compute_stance_delta's
    # previous_round: {systems: "{{@node.X.output}}", ...}) get their
    # inner refs resolved. Standalone refs preserve Python type per §8.6.
    resolved_args = walk_refs(
        tool_args,
        completed_outcomes,
        run.context,
        leaf_resolver=lambda s: resolve_template(
            s,
            completed_outcomes,
            run.context,
        ),
    )

    # Provision tool dependencies
    deps = tool_info.get("deps", [])
    _HANDLED_DEPS = {"http_client", "mission_id"}
    if "mission_id" in deps:
        resolved_args["mission_id"] = str(run.mission_id)

    try:
        import httpx

        if "http_client" in deps:
            async with httpx.AsyncClient(timeout=60) as client:
                resolved_args["http_client"] = client
                result = await impl(**resolved_args)
        else:
            unsupported = [d for d in deps if d not in _HANDLED_DEPS]
            if unsupported:
                raise RuntimeError(
                    f"Tool '{tool_name}' requires unsupported deps: "
                    f"{unsupported} (step '{step.id}')"
                )
            result = await impl(**resolved_args)
        success = True
    except RuntimeError:
        raise
    except Exception as e:
        # Catch-all justified: `impl` is an arbitrary tool function
        # whose exception surface is unbounded. best-effort — the step
        # continues with success=False, which is reported via the
        # unconditional WorkflowToolCallCompletedEvent below.
        logger.warning(
            "Tool call step failed",
            extra={"step_id": step.id, "tool": tool_name},
            exc_info=True,
        )
        result = {"error": str(e)}
        success = False

    logger.info(
        "Tool call completed", extra={"step_id": step.id, "tool": tool_name, "success": success}
    )
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowToolCallCompletedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            tool_name=tool_name,
            success=success,
        ),
    )
    outputs = {"output": result, "tool_name": tool_name}
    return VirtualExecution(id=step.id), outputs


async def execute_llm_call_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Make a raw LLM call with template substitution — no agent framework."""
    from modules.backend.services.condition_evaluator import resolve_template

    config = step.llm_call_config
    if not config:
        raise RuntimeError(f"llm_call_config missing for step '{step.id}'")

    # Resolve templates
    prompt = resolve_template(config.prompt_template, completed_outcomes, run.context)
    system = (
        resolve_template(config.system_prompt, completed_outcomes, run.context)
        if config.system_prompt
        else None
    )

    try:
        from pydantic_ai import Agent as PydanticAgent

        from modules.backend.core.model_builder import _build_model

        model = _build_model(config.model)
        agent = PydanticAgent(model, output_type=str, instructions=system or "")
        result = await agent.run(prompt)
        text = result.output
        cost = extract_run_cost(result, config.model)
        success = True
    except Exception as e:
        # Catch-all justified: wraps a raw LLM call whose exception
        # surface is unbounded (network, auth, quota, provider bugs).
        # best-effort — the step continues with success=False, which
        # is reported via the unconditional
        # WorkflowLlmCallCompletedEvent below.
        logger.warning(
            "LLM call step failed",
            extra={
                "mission_id": run.mission_id,
                "step_id": step.id,
                "model": config.model,
            },
            exc_info=True,
        )
        text = f"Error: {e}"
        cost = 0.0
        success = False

    logger.info(
        "LLM call completed",
        extra={"step_id": step.id, "model": config.model, "success": success, "cost": cost},
    )
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowLlmCallCompletedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            model=config.model,
            success=success,
        ),
    )
    outputs = {"output": text, "model": config.model}
    return VirtualExecution(id=step.id, total_cost_usd=cost), outputs
