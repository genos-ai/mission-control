"""MissionPlanOrchestrator's task/plan materialization and write-back helpers.

Split out of mission_plan_orchestrator.py (Plan 84 Phase 5.2). Pure move,
no behavior change. Functions that need DB/repo access take the owning
MissionPlanOrchestrator instance (`orchestrator`) as an explicit first
argument — mirroring the Phase 5.1 pattern in workflow_run_steps/.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from modules.backend.models.mission_run import ACTIVE_RUN_STATUSES, MissionRunStatus
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.task_plan import TaskDefinition, TaskPlan

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.models.mission_plan import MissionPlan
    from modules.backend.models.task import Task
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator


def _task_row_dict(task: Task) -> dict:
    """The TaskDefinition-shaped dict of one Task row and its dependency edges."""
    return {
        "task_id": task.id,
        "agent": task.agent,
        "description": task.description,
        "instructions": task.instructions,
        "inputs": task.inputs_json or {},
        "dependencies": [d.depends_on_id for d in task.dependencies],
        "verification": task.verification_json or {},
        "constraints": task.constraints_json or {},
        "domain_tags": task.domain_tags or [],
    }


def task_definition_from_row(task: Task) -> TaskDefinition:
    """Build the TaskDefinition dispatch runs from one Task row (dependencies loaded)."""
    return TaskDefinition.model_validate(_task_row_dict(task))


def _scoped_tasks(plan: MissionPlan, *, mission_run_id: str | None) -> list[Task]:
    """The plan's Task rows in scope: the run's tasks and the backlog (mission_run_id IS NULL)."""
    return [t for t in plan.tasks if t.mission_run_id in (mission_run_id, None)]


def materialize_plan_dict(plan: MissionPlan, *, mission_run_id: str | None) -> dict | None:
    """Build a TaskPlan-shaped dict from the plan's Task rows in scope.

    In scope are the run's tasks and the backlog (mission_run_id IS NULL);
    a None mission_run_id means the backlog only. Used to feed the planning
    agent's current_plan parameter during refinement. Returns None if no
    task is in scope.
    """
    scoped = _scoped_tasks(plan, mission_run_id=mission_run_id)
    if not scoped:
        return None
    tasks = [_task_row_dict(t) for t in scoped]
    return {
        "version": f"{plan.version}.0.0",
        "mission_id": plan.mission_id,
        "summary": plan.summary or "",
        "estimated_cost_usd": float(plan.estimated_cost_usd or 0),
        "estimated_duration_seconds": int(plan.estimated_duration or 0),
        "execution_hints": plan.execution_hints_json or {},
        "tasks": tasks,
    }


def materialize_task_states(plan: MissionPlan, *, mission_run_id: str | None) -> list[dict]:
    """Status and failure record of each Task row in scope (see materialize_plan_dict).

    Plan 88 contracts 3.8.6, Planning Agent row. Each entry is
    ``{task_id, status, failure}``: ``status`` is the lowercase TaskStatus value,
    ``failure`` is ``{origin, failure_class, summary}`` from the task's failure
    columns for a FAILED task, otherwise None. Rendered beside current_plan in
    the planning prompt; never seeded into PlanBuildingSession.tasks, because
    TaskDefinition forbids extra keys.
    """
    return [
        {
            "task_id": t.id,
            "status": t.status.value,
            "failure": _failure_dict(t) if t.status == TaskStatus.FAILED else None,
        }
        for t in _scoped_tasks(plan, mission_run_id=mission_run_id)
    ]


def _failure_dict(task: Task) -> dict:
    """The planner-facing failure record of a FAILED task: lowercase enum values and summary."""
    return {
        "origin": task.failure_origin.value if task.failure_origin is not None else None,
        "failure_class": task.failure_class.value if task.failure_class is not None else None,
        "summary": task.failure_reason,
    }


async def resolve_run_scope(
    orchestrator: MissionPlanOrchestrator,
    mission_id: str,
    mission_run_id: str | None,
) -> str | None:
    """The run a plan change is scoped to: the given run, else the mission's active run.

    So tasks created by a Director refine during an active run join that run.
    None means no run is active and the change touches the backlog only.
    """
    if mission_run_id is not None:
        return mission_run_id
    active = await MissionRunRepository(orchestrator._session).get_active_for_mission(mission_id)
    return active.id if active is not None else None


async def _joinable_run(
    orchestrator: MissionPlanOrchestrator, mission_id: str, run_id: str | None
) -> str | None:
    """The run new tasks join: run_id while it is still active, else None (the backlog).

    Locks the run row until the caller commits. finalise and begin take the
    same lock before they touch the run's tasks, so a refine that commits
    after its run ended puts its new tasks in the backlog (contract 3.5.1)
    instead of on a terminal run, where no later run would adopt them.
    """
    if run_id is None:
        return None
    run = await MissionRunRepository(orchestrator._session).lock_current(mission_id, run_id)
    if run is None or MissionRunStatus(run.status) not in ACTIVE_RUN_STATUSES:
        return None
    return run_id


async def reconcile_tasks(
    orchestrator: MissionPlanOrchestrator,
    plan: MissionPlan,
    new_plan: TaskPlan,
    *,
    mission_run_id: str | None,
) -> dict[str, int]:
    """Reconcile the run's and the backlog's Task rows against a new TaskPlan.

    Delegates to TaskRepository.reconcile_tasks for the core logic; tasks of
    other runs are never touched, and new tasks join the run while it is
    active, else the backlog. When mission_run_id is None the mission's
    active run, if any, is the scope.
    Also rebuilds task_dependencies from the new plan's dependency edges.
    """
    mission_run_id = await resolve_run_scope(orchestrator, plan.mission_id, mission_run_id)
    # Convert TaskDefinition schemas to task dicts for the repository
    new_task_defs: list[dict] = []
    for task_def in new_plan.tasks:
        new_task_defs.append(
            {
                "id": task_def.task_id,
                "agent": task_def.agent,
                "description": task_def.description,
                "instructions": task_def.instructions,
                "inputs_json": task_def.inputs.model_dump() if task_def.inputs else {},
                "verification_json": (
                    task_def.verification.model_dump() if task_def.verification else {}
                ),
                "constraints_json": (
                    task_def.constraints.model_dump() if task_def.constraints else {}
                ),
                "domain_tags": task_def.domain_tags or [],
            }
        )

    stats = await orchestrator._task_repo.reconcile_tasks(
        plan.id,
        plan.mission_id,
        new_task_defs,
        scope_run_id=mission_run_id,
        assign_run_id=await _joinable_run(orchestrator, plan.mission_id, mission_run_id),
    )

    # Rebuild dependency graph using task IDs we already know
    # (avoids a redundant query — reconcile_tasks already fetched them)
    all_task_ids = {d["id"] for d in new_task_defs}
    dep_map: dict[str, list[str]] = {}
    for task_def in new_plan.tasks:
        dep_map[task_def.task_id] = task_def.dependencies or []
    await orchestrator._task_repo.rebuild_dependencies_for_task_ids(
        all_task_ids,
        dep_map,
    )

    return stats


async def load_prior_outputs(
    orchestrator: MissionPlanOrchestrator,
    mission_plan_id: str,
) -> dict[str, dict]:
    """Load output_reference dicts from tasks completed in prior waves.

    Reads plan_task_states where status is completed/skipped and
    result_summary is not null. result_summary contains the JSON-
    serialized output_reference stored by RunTaskExecutionService.record.

    Returns a {task_id: output_dict} mapping that seeds the dispatch
    loop's completed_outputs so from_upstream references resolve.
    """
    completed_states = await orchestrator._task_repo.get_by_plan_id(
        mission_plan_id,
        status=TaskStatus.COMPLETED,
    )
    return _decode_result_summaries(completed_states)


async def load_dependency_outputs(session: AsyncSession, task_id: str) -> dict[str, dict]:
    """Outputs of the task's direct dependencies, keyed by dependency task id.

    Reads result_summary of every COMPLETED task the given task depends on
    (task_dependencies.depends_on_id), whatever run it completed in: explicit
    dependency edges are not bounded by run. A dependency that is not
    COMPLETED is absent even when it carries a result_summary from an
    earlier run (recording never clears it), and so is one without a
    result_summary; a from_upstream reference to either fails.
    """
    dependencies = await TaskRepository(session).get_dependency_tasks(
        task_id, status=TaskStatus.COMPLETED
    )
    return _decode_result_summaries(dependencies)


def _decode_result_summaries(tasks: list[Task]) -> dict[str, dict]:
    """{task_id: output_dict} from each task's JSON result_summary; tasks without one skipped."""
    outputs: dict[str, dict] = {}
    for task in tasks:
        if not task.result_summary:
            continue
        try:
            outputs[task.id] = json.loads(task.result_summary)
        except (TypeError, ValueError, json.JSONDecodeError):
            outputs[task.id] = {"result": task.result_summary}
    return outputs


async def resolve_task_execution_id(
    orchestrator: MissionPlanOrchestrator,
    execution_record_id: str | None,
    task_id: str,
) -> str | None:
    """Look up the task_executions.id PK for a given run + task.

    Returns None if the execution_record is missing or the task
    wasn't persisted (e.g. skipped).
    """
    if not execution_record_id:
        return None
    from sqlalchemy import select

    from modules.backend.models.execution_record import TaskExecution

    stmt = (
        select(TaskExecution.id)
        .where(
            TaskExecution.execution_record_id == execution_record_id,
            TaskExecution.task_id == task_id,
        )
        .limit(1)
    )
    result = await orchestrator._session.execute(stmt)
    row = result.scalar_one_or_none()
    return row


def infer_task_type(plan: TaskPlan) -> str:
    """Derive a task_type label from the plan's tasks.

    Used to populate execution_records.task_type so the background-
    task badge can display running dispatches. Special loop types
    (research_loop, convergence_loop) get their own label; standard
    multi-agent plans use "plan_dispatch".
    """
    for task in plan.tasks:
        static_type = task.inputs.static.get("type", "")
        if static_type == "research_loop":
            return "research"
        if static_type == "convergence_loop":
            return "convergence"
    return "plan_dispatch"
