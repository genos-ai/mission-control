"""Shared dataclasses and pure helpers for workflow step execution.

Split out of workflow_run_waves.py (Plan 84 Phase 5.1). These carry no
dependency on WorkflowRunWavesMixin, so they live here to avoid a
circular import between workflow_run_waves.py and the step-executor
submodules (control.py, io.py, human_input.py, sub_workflow.py) that
all need them.

VirtualExecution and StepContext are re-exported from
workflow_run_waves.py for backward compatibility with existing external
imports (workflow_run.py) — this module is their
canonical home now.
"""

from __future__ import annotations

import os
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from modules.backend.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.schemas.workflow import WorkflowStepSchema
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

logger = get_logger(__name__)


@dataclass
class VirtualExecution:
    """Stand-in for condition/notification nodes that don't create DB Execution records."""

    id: str
    status: str = "COMPLETED"
    total_cost_usd: float = 0.0
    error_data: dict = field(default_factory=dict)


@dataclass
class StepContext:
    """Per-step execution context with its own DB session (Plan 71)."""

    db: AsyncSession
    persistence: ExecutionPersistenceService

    @staticmethod
    @asynccontextmanager
    async def factory():
        """Create a StepContext with its own DB session."""
        from modules.backend.core.database import get_async_session
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with get_async_session() as step_db:
            yield StepContext(
                db=step_db,
                persistence=ExecutionPersistenceService(step_db),
            )
            await step_db.commit()


def extract_run_cost(result: Any, model_name: str | None = None) -> float:
    """Extract cost from a PydanticAI run result using the project's cost calculator."""
    try:
        from modules.backend.agents.mission_control.cost import compute_cost_usd
        from modules.backend.core.model_builder import _resolve_model_alias

        resolved = _resolve_model_alias(model_name) if model_name else None
        usage = result.usage()
        return compute_cost_usd(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model=resolved,
            cache_read_tokens=getattr(usage, "cache_read_tokens", 0),
            cache_write_5m_tokens=getattr(usage, "cache_write_tokens", 0),
        )
    except (AttributeError, TypeError):
        # Narrowed deliberately: result.usage() shape mismatches only.
        # compute_cost_usd's own pricing errors (e.g. unknown model) must
        # NOT be swallowed here — silently returning 0.0 for those would
        # defeat budget enforcement (see Phase 4.6).
        logger.debug("Cost extraction failed", extra={"model": model_name}, exc_info=True)
        return 0.0


def extract_default_agent_output(
    outcome_dict: dict | None,
    *,
    expected_agent: str | None = None,
    mission_id: str | None = None,
) -> dict[str, Any]:
    """Default-populate completed_outcomes for an agent_step (Plan 79 §8.3).

    Without this, agent_step nodes whose workflow YAML does not declare
    output_mapping land in completed_outcomes as `{}` (because
    ExecutionPersistence.extract_outputs short-circuits on no mapping).
    Downstream @node.X.output.field refs then silently resolve to None.

    Strategy:
    1. If `expected_agent` is given, find the TaskResult whose agent_name
       matches. This is the deterministic case for single-capability
       agent_step dispatch (the Plan 79 deliberation workflow case).
    2. Otherwise fall back to the last task_result (legacy multi-task
       behaviour). Log a warning when the fallback fires.

    The result is wrapped under "output" key so @node.X.output.field
    references auto-unwrap (matching the convention used by tool_call
    and llm_call dispatchers).
    """
    if not outcome_dict:
        return {}
    task_results = outcome_dict.get("task_results", []) or []
    if not task_results:
        return {}

    if expected_agent:
        for tr in task_results:
            if isinstance(tr, dict) and tr.get("agent_name") == expected_agent:
                return {"output": tr.get("output_reference", {})}
        logger.warning(
            "Agent name match failed for default-output extraction; "
            "falling back to last task_result",
            extra={
                "mission_id": mission_id,
                "expected_agent": expected_agent,
                "available_agent_names": [
                    tr.get("agent_name") for tr in task_results if isinstance(tr, dict)
                ],
            },
        )

    last = task_results[-1]
    output_ref = last.get("output_reference", {}) if isinstance(last, dict) else {}
    return {"output": output_ref}


@dataclass(frozen=True)
class DispatchParams:
    """What ``handle_mission`` needs to dispatch one workflow step."""

    execution_mode: str
    roster_name: str
    mission_repo_root: str | None


async def resolve_dispatch_params(
    db_session: AsyncSession,
    mission_id: str | None,
    step: WorkflowStepSchema,
) -> DispatchParams:
    """Resolve execution mode, roster name and mission repo root for a workflow step.

    Raises ``ExecutionEnvironmentError`` when the resolved mode needs a
    repo_root the mission does not have (contracts 3.8.5).
    """
    from modules.backend.agents.mission_control.dispatch.environment import (
        resolve_execution_mode,
    )
    from modules.backend.core.config import find_project_root

    mission_environment = None
    mission_repo_root = None
    if mission_id:
        try:
            from modules.backend.repositories.mission import MissionRepository

            repo = MissionRepository(db_session)
            mission_obj = await repo.get_by_id_or_none(mission_id)
            if mission_obj:
                mission_environment = mission_obj.execution_environment
                mission_repo_root = mission_obj.repo_root
        except SQLAlchemyError:
            logger.debug("Could not load mission for env resolution", exc_info=True)

    resolved_mode = step.environment or resolve_execution_mode(
        mission_environment=mission_environment,
        mission_repo_root=mission_repo_root,
    )

    roster_name = step.roster
    if step.complexity_tier and step.complexity_tier != "simple":
        tier_roster = (
            find_project_root()
            / "config"
            / "mission_control"
            / "rosters"
            / f"{step.roster}-{step.complexity_tier}.yaml"
        )
        if os.path.exists(tier_roster):
            roster_name = f"{step.roster}-{step.complexity_tier}"

    return DispatchParams(
        execution_mode=resolved_mode,
        roster_name=roster_name,
        mission_repo_root=mission_repo_root,
    )


def extract_first_task_failure(execution: Any) -> str | None:
    """Pull a human-meaningful failure reason from an ExecutionOutcome.

    Looks at the first task_results entry's output_reference,
    retry_history, and verification_outcome for any error /
    failure_reason / abort_reason hint. Returns None when we can't
    find a specific reason — caller should fall back to a generic
    message.
    """
    task_results = getattr(execution, "task_results", None) or []
    if not task_results:
        return None
    first = task_results[0]
    output = getattr(first, "output_reference", None) or {}
    if isinstance(output, dict):
        for key in ("error", "failure_reason", "abort_reason"):
            value = output.get(key)
            if value:
                return str(value)
    retry_history = getattr(first, "retry_history", None) or []
    if retry_history:
        last = retry_history[-1]
        reason = getattr(last, "failure_reason", None)
        if reason:
            return str(reason)
    verification = getattr(first, "verification_outcome", None)
    if verification:
        for tier_attr in ("tier_3", "tier_2", "tier_1"):
            tier = getattr(verification, tier_attr, None)
            tier_status = getattr(tier, "status", None) if tier else None
            tier_reason = getattr(tier, "failure_reason", None) if tier else None
            if tier_status == "fail" and tier_reason:
                return f"{tier_attr}: {tier_reason}"
    return None


def should_skip(
    step_id: str,
    step_map: dict[str, WorkflowStepSchema],
    completed_outcomes: dict[str, dict],
    edges_map: dict[tuple[str, str], str | None],
    workflow_context: dict[str, Any] | None = None,
    mission_id: str | None = None,
) -> bool:
    """Check if a step should be skipped.

    A step is skipped when:
    1. It has an inline ``condition`` expression that evaluates to false, OR
    2. ANY of its dependencies is a condition node whose branch result
       does not match the edge label connecting them, OR
    3. ANY of its dependencies was itself skipped (propagation).

    Exception: merge nodes never propagate skips from dependencies.
    A merge is a join point that collects whatever completed; its
    _execute_merge_step already filters out skipped deps at runtime.

    If no edge label exists on a condition-node edge the step always runs
    (backward-compatible).
    """
    step = step_map[step_id]

    # ── Inline step-level condition guard ──
    if step.condition:
        from modules.backend.services.condition_evaluator import (
            ConditionEvaluationError,
            evaluate_condition,
        )

        try:
            result = evaluate_condition(
                step.condition,
                completed_outcomes,
                workflow_context or {},
            )
            if not result:
                logger.info(
                    "Step skipped by inline condition",
                    extra={"step_id": step_id, "condition": step.condition},
                )
                return True
        except ConditionEvaluationError:
            # best-effort — this is a static helper with no event_bus in
            # scope; fails safe by treating the step as skipped rather
            # than crashing the whole run.
            logger.error(
                "Inline condition evaluation failed — skipping step",
                extra={
                    "mission_id": mission_id,
                    "step_id": step_id,
                    "condition": step.condition,
                },
                exc_info=True,
            )
            return True

    # Merge nodes are join points — they never skip due to dep propagation.
    # Their execution logic already handles skipped deps gracefully.
    is_merge = getattr(step, "node_type", "agent_step") == "merge"

    # ── Graph-based condition-node routing ──
    for dep_id in step.depends_on:
        dep = step_map.get(dep_id)
        if dep is None:
            continue
        dep_type = getattr(dep, "node_type", "agent_step")
        if dep_type not in ("condition", "decision"):
            # Propagate skips — unless this step is a merge node
            if not is_merge:
                dep_outcome = completed_outcomes.get(dep_id, {})
                if dep_outcome.get("_skipped"):
                    return True
            continue

        # Dependency is a condition or decision node — check the branch
        dep_outcome = completed_outcomes.get(dep_id, {})
        if dep_outcome.get("_skipped") and not is_merge:
            return True
        branch_taken = dep_outcome.get("_branch")
        if branch_taken is None:
            continue  # condition hasn't run yet — shouldn't happen in wave order

        edge_label = edges_map.get((dep_id, step_id))
        if edge_label is None:
            continue  # no label on edge — always run
        if edge_label != branch_taken and not is_merge:
            return True
        # Merge nodes: the edge-label-mismatch check is suppressed.
        # A merge is a multi-path join point: it should run whenever
        # *any* incoming branch reached it, not require *every*
        # condition/decision dep's branch label to match. Without
        # this guard, a merge that has both labelled (e.g. halt/
        # continue) and unlabelled (always-run) incoming edges gets
        # skipped whenever a labelled dep chose the unmatched
        # branch, even though the unlabelled dep correctly reached
        # the merge. _execute_merge_step already filters skipped
        # deps at runtime; this matches that intent here.

    return False


def build_step_objective(
    step: WorkflowStepSchema,
    step_input: dict[str, Any],
) -> str:
    """Build an objective string from the step definition and resolved input.

    Plan 79 §8.2 — dict/list values are JSON-encoded so structured
    upstream context (e.g. a debater's prior turn, the research
    packet) reaches the agent in machine-parseable form rather than
    being dropped silently. None values are skipped. Scalar values
    (str/int/float/bool) format as `key: value`.
    """
    import json

    parts = [step.description or f"Execute step: {step.id}"]

    if step_input:
        context_parts = []
        for key, value in step_input.items():
            if value is None:
                continue
            if isinstance(value, str):
                context_parts.append(f"{key}: {value}")
            elif isinstance(value, (dict, list)):
                context_parts.append(f"{key}: {json.dumps(value, default=str)}")
            else:
                # int, float, bool, etc.
                context_parts.append(f"{key}: {value}")
        if context_parts:
            parts.append("Context: " + "; ".join(context_parts))

    return ". ".join(parts)


def compute_waves(
    steps: list[WorkflowStepSchema],
) -> list[list[str]]:
    """Topologically sort steps into execution waves.

    Steps with no unmet dependencies run in the same wave (parallel).
    Returns a list of waves, each wave is a list of step IDs.
    """
    # Build dependency graph
    in_degree: dict[str, int] = {}
    dependents: dict[str, list[str]] = defaultdict(list)

    for step in steps:
        in_degree[step.id] = len(step.depends_on)
        for dep in step.depends_on:
            dependents[dep].append(step.id)

    waves: list[list[str]] = []
    remaining = set(in_degree.keys())

    while remaining:
        # Find all steps with no unmet dependencies
        wave = [sid for sid in remaining if in_degree[sid] == 0]

        if not wave:
            raise RuntimeError("Dependency cycle detected in workflow steps")

        waves.append(sorted(wave))

        # Remove completed steps and update degrees
        for sid in wave:
            remaining.remove(sid)
            for dependent in dependents[sid]:
                in_degree[dependent] -= 1

    return waves
