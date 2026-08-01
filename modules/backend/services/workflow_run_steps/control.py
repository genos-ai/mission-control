"""Control-flow step executors: condition, decision, branch, merge.

Split out of workflow_run_waves.py (Plan 84 Phase 5.1). Each function
takes the owning WorkflowRunWavesMixin instance (`mixin`) as an explicit
first argument to reach `_publish_workflow_event` and (for decision
resolution) `_last_decision_cost` — a pure move, no behavior change.
"""

from __future__ import annotations

import re
import uuid as _uuid
from typing import TYPE_CHECKING, Any

from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    SystemEvent,
    WorkflowBranchPassedEvent,
    WorkflowConditionEvaluatedEvent,
    WorkflowDecisionResolvedEvent,
    WorkflowMergeCompletedEvent,
)
from modules.backend.services.workflow_run_steps.helpers import VirtualExecution, extract_run_cost

if TYPE_CHECKING:
    from modules.backend.models.workflow_run import WorkflowRun
    from modules.backend.schemas.workflow import WorkflowStepSchema
    from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin

logger = get_logger(__name__)


async def execute_condition_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Evaluate a condition expression and return branch result."""
    from modules.backend.services.condition_evaluator import (
        ConditionEvaluationError,
        evaluate_condition,
    )

    config = step.condition_config
    expression = config.expression if config else ""

    try:
        result = evaluate_condition(expression, completed_outcomes, run.context)
    except ConditionEvaluationError as e:
        logger.error(
            "Condition evaluation failed",
            extra={
                "mission_id": run.mission_id,
                "step_id": step.id,
                "error": str(e),
            },
        )
        await mixin._publish_workflow_event(
            run.mission_id,
            SystemEvent(
                session_id=_uuid.UUID(run.session_id) if run.session_id else _uuid.uuid4(),
                source="workflow_run_waves",
                level="error",
                message=f"Condition '{step.id}' failed: {e}"[:500],
                mission_id=run.mission_id,
            ),
        )
        raise RuntimeError(f"Condition '{step.id}' failed: {e}") from e

    branch = (
        (config.true_label if result else config.false_label)
        if config
        else ("Yes" if result else "No")
    )

    logger.info(
        "Condition evaluated",
        extra={
            "step_id": step.id,
            "expression": expression,
            "result": result,
            "branch": branch,
        },
    )

    outputs = {"result": result, "branch": branch, "_branch": branch}
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowConditionEvaluatedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            expression=expression,
            result=result,
            branch=branch,
        ),
    )
    return VirtualExecution(id=step.id), outputs


async def execute_decision_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Resolve a decision and return the chosen option as _branch.

    Follows the same signature pattern as execute_condition_step
    (lightweight routing — no session_id needed, extracted from run).
    """
    config = step.decision_config
    if not config:
        raise RuntimeError(f"decision_config missing for step '{step.id}'")

    valid_keys = {o.key for o in config.options}
    mixin._last_decision_cost = 0.0

    if config.resolver == "agent":
        chosen = await resolve_agent_decision(
            mixin,
            step,
            completed_outcomes,
            run.context or {},
        )
    elif config.resolver == "human":
        chosen = await resolve_human_decision(
            mixin,
            run,
            step,
            completed_outcomes,
        )
    elif config.resolver == "rule":
        chosen = await resolve_rule_decision(
            step,
            completed_outcomes,
            run.context or {},
        )
    else:
        raise RuntimeError(f"Unknown resolver '{config.resolver}' in step '{step.id}'")

    if chosen not in valid_keys:
        raise RuntimeError(
            f"Decision '{step.id}' resolver returned '{chosen}' "
            f"which is not in options: {sorted(valid_keys)}"
        )

    logger.info(
        "Decision resolved",
        extra={
            "step_id": step.id,
            "run_id": run.id,
            "resolver": config.resolver,
            "chosen": chosen,
        },
    )

    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowDecisionResolvedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            resolver=config.resolver,
            chosen_option=chosen,
            options=[o.key for o in config.options],
        ),
    )

    outputs = {"chosen": chosen, "_branch": chosen}
    return VirtualExecution(id=step.id, total_cost_usd=mixin._last_decision_cost), outputs


async def resolve_agent_decision(
    mixin: WorkflowRunWavesMixin,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
    workflow_context: dict,
) -> str:
    """LLM picks an option key."""
    config = step.decision_config

    if not config.model:
        raise RuntimeError(
            f"Decision '{step.id}' agent resolver requires a model. "
            f"Set decision_config.model in the workflow step definition."
        )
    model_name = config.model

    from modules.backend.services.condition_evaluator import resolve_template

    prompt = resolve_template(config.prompt, completed_outcomes, workflow_context)
    options_desc = "\n".join(f"- {o.key}: {o.label}" for o in config.options)

    full_prompt = (
        f"{prompt}\n\n"
        f"Available options:\n{options_desc}\n\n"
        f"Respond with ONLY the option key. No explanation."
    )

    from pydantic_ai import Agent as PydanticAgent

    from modules.backend.core.model_builder import _build_model

    model = _build_model(model_name)
    agent = PydanticAgent(
        model,
        output_type=str,
        instructions="You are a routing decision agent. Return only the option key.",
    )
    result = await agent.run(full_prompt)

    # Track cost on the parent decision step's VirtualExecution
    mixin._last_decision_cost = extract_run_cost(result, model_name)

    chosen = re.sub(r"[^a-z0-9_]", "", result.output.strip().lower())
    return chosen


async def resolve_human_decision(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> str:
    """Present options to human and wait for selection.

    Reuses execute_human_input_step by constructing a temporary
    human_input-shaped step. Template resolution of prompt_message
    happens inside execute_human_input_step — do NOT resolve here
    or the template gets resolved twice.
    """
    from modules.backend.services.workflow_run_steps.human_input import execute_human_input_step

    config = step.decision_config
    choices = [o.key for o in config.options]

    from modules.backend.schemas.workflow import HumanInputConfig
    from modules.backend.schemas.workflow import WorkflowStepSchema as StepSchema

    hi_config = HumanInputConfig(
        prompt_message=config.prompt_message,
        channel=config.channel or "chat",
        timeout_hours=config.timeout_hours,
        default_response=config.default_option,
        choices=choices,
    )

    temp_step = StepSchema(
        id=step.id,
        node_type="human_input",
        human_input_config=hi_config,
        depends_on=step.depends_on,
    )

    _, outputs = await execute_human_input_step(
        mixin,
        run,
        temp_step,
        completed_outcomes,
    )

    response = outputs.get("response", "")
    if response in {o.key for o in config.options}:
        return response
    if outputs.get("timed_out") and config.default_option:
        return config.default_option

    raise RuntimeError(
        f"Decision '{step.id}' human response '{response}' " f"does not match any option key"
    )


async def resolve_rule_decision(
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
    workflow_context: dict,
) -> str:
    """Evaluate expression to get option key."""
    config = step.decision_config

    from modules.backend.services.condition_evaluator import (
        ConditionEvaluationError,
        evaluate_expression,
    )

    try:
        return evaluate_expression(
            config.expression,
            completed_outcomes,
            workflow_context,
        )
    except ConditionEvaluationError as e:
        raise RuntimeError(f"Decision '{step.id}' rule evaluation failed: {e}") from e


async def execute_branch_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Pass-through fork node. Downstream steps run in parallel via wave scheduling."""
    # Forward all upstream outputs so downstream forks can reference them
    upstream_data: dict[str, Any] = {}
    for dep_id in step.depends_on:
        dep_out = completed_outcomes.get(dep_id, {})
        upstream_data[dep_id] = dep_out

    # Count outgoing edges (fork_count) — not available here, use 0 as placeholder
    logger.info("Branch passed", extra={"step_id": step.id, "run_id": run.id})
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowBranchPassedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            fork_count=0,
        ),
    )
    outputs = {"_passthrough": True, **upstream_data}
    return VirtualExecution(id=step.id), outputs


async def execute_merge_step(
    mixin: WorkflowRunWavesMixin,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Sync barrier — collects outputs from all incoming paths.

    Flat-merges all output-mapped keys from non-skipped dependencies into
    a single dict. This allows downstream steps to receive all upstream
    data naturally via resolve_upstream_context, regardless of which
    branches actually ran.
    """
    flat: dict[str, Any] = {}
    merged_by_dep: dict[str, dict] = {}
    for dep_id in step.depends_on:
        dep_out = completed_outcomes.get(dep_id, {})
        if not dep_out.get("_skipped"):
            merged_by_dep[dep_id] = dep_out
            # Flat-merge: output-mapped keys from each dep become top-level
            for k, v in dep_out.items():
                if not k.startswith("_"):
                    flat[k] = v

    strategy = "wait_all"
    if step.merge_config:
        strategy = step.merge_config.strategy

    logger.info(
        "Merge completed",
        extra={
            "step_id": step.id,
            "run_id": run.id,
            "strategy": strategy,
            "inputs": len(merged_by_dep),
        },
    )
    await mixin._publish_workflow_event(
        run.mission_id,
        WorkflowMergeCompletedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            strategy=strategy,
            inputs_merged=len(merged_by_dep),
        ),
    )
    outputs = {
        **flat,
        "_merged_deps": list(merged_by_dep.keys()),
        "_input_count": len(merged_by_dep),
    }
    return VirtualExecution(id=step.id), outputs
