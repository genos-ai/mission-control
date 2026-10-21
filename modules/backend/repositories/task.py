"""
Task Repository (Plan 72).

Data access for Task and TaskDependency. Handles task CRUD, bulk upsert,
reconciliation against new plan output, status queries, and dependency
graph operations.

Business logic (dependency closure on approval, state machine enforcement)
lives in the service layer — this is raw data access.
"""

from datetime import datetime
from typing import NamedTuple
from uuid import uuid7

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import selectinload

from modules.backend.core.logging import get_logger
from modules.backend.models.mission_plan import MissionPlan, MissionPlanStatus
from modules.backend.models.task import TERMINAL_TASK_STATUSES, Task, TaskDependency, TaskStatus
from modules.backend.repositories.base import BaseRepository

logger = get_logger(__name__)


class TaskGroup(NamedTuple):
    """The tasks of one mission that share a status: how many, and when."""

    mission_id: str
    count: int
    oldest_created_at: datetime
    latest_updated_at: datetime


class TaskRepository(BaseRepository[Task]):
    """Repository for Task CRUD + dependency management."""

    model = Task

    # ── Query by scope ─────────────────────────────────────────────────────

    async def get_by_plan_id(
        self,
        plan_id: str,
        *,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        """Return all tasks for a plan, optionally filtered by status.

        Ordered by created_at for stable Kanban display.
        """
        query = (
            select(Task)
            .where(Task.plan_id == plan_id)
            .options(selectinload(Task.dependencies))
            .order_by(Task.created_at)
        )
        if status is not None:
            query = query.where(Task.status == status)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_domain_tags_by_ids(self, task_ids: list[str]) -> dict[str, list | None]:
        """Batch-fetch domain_tags for a set of task ids in one query.

        Used by the persistence bridge to annotate task_executions
        without an N+1 query per task.
        """
        if not task_ids:
            return {}
        result = await self.session.execute(
            select(Task.id, Task.domain_tags).where(Task.id.in_(task_ids))
        )
        return {tid: tags or None for tid, tags in result}

    async def get_by_mission_id(
        self,
        mission_id: str,
        *,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        """Return all tasks for a mission (cross-plan)."""
        query = select(Task).where(Task.mission_id == mission_id).order_by(Task.created_at)
        if status is not None:
            query = query.where(Task.status == status)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def summarise_for_missions(
        self,
        mission_ids: list[str],
        status: TaskStatus,
        *,
        exclude_gate_modes: frozenset[str] = frozenset(),
    ) -> list[TaskGroup]:
        """Count each mission's tasks in `status`, for plans that are still open.

        Only plans that are ACTIVE or PAUSED count: a failed task in a completed or
        archived plan is history, not something to act on. One grouped query for all the
        missions, however many tasks there are. `exclude_gate_modes` leaves out plans in
        those gate modes (a plan with no gate mode is never left out: it defaults to
        interactive).
        """
        if not mission_ids:
            return []
        query = (
            select(
                Task.mission_id,
                func.count(Task.id),
                func.min(Task.created_at),
                func.max(Task.updated_at),
            )
            .join(MissionPlan, MissionPlan.id == Task.plan_id)
            .where(
                Task.mission_id.in_(mission_ids),
                Task.status == status,
                MissionPlan.status.in_([MissionPlanStatus.ACTIVE, MissionPlanStatus.PAUSED]),
            )
            .group_by(Task.mission_id)
        )
        if exclude_gate_modes:
            query = query.where(
                or_(
                    MissionPlan.gate_mode.is_(None),
                    MissionPlan.gate_mode.notin_(exclude_gate_modes),
                )
            )
        result = await self.session.execute(query)
        return [TaskGroup(str(mid), n, oldest, latest) for mid, n, oldest, latest in result.all()]

    async def list_in_flight(
        self,
        plan_id: str | None = None,
    ) -> list[Task]:
        """Return all tasks in RUNNING or QUEUED status.

        Used by crash recovery at startup (plan_id=None → global)
        or before dispatch (plan_id set → scoped to one plan).
        """
        conditions = [Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED])]
        if plan_id is not None:
            conditions.append(Task.plan_id == plan_id)
        query = select(Task).where(*conditions).order_by(Task.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ── Single task operations ─────────────────────────────────────────────

    async def create_task(
        self,
        *,
        plan_id: str,
        mission_id: str,
        agent: str,
        description: str,
        instructions: str = "",
        inputs_json: dict | None = None,
        verification_json: dict | None = None,
        constraints_json: dict | None = None,
        domain_tags: list | None = None,
        status: TaskStatus = TaskStatus.PROPOSED,
        task_id: str | None = None,
    ) -> Task:
        """Create a new task. Optionally supply a pre-generated UUID."""
        task = Task(
            id=task_id or str(uuid7()),
            plan_id=plan_id,
            mission_id=mission_id,
            agent=agent,
            description=description,
            instructions=instructions,
            inputs_json=inputs_json or {},
            verification_json=verification_json or {},
            constraints_json=constraints_json or {},
            domain_tags=domain_tags or [],
            status=status,
        )
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    # ── Dependency operations ──────────────────────────────────────────────

    async def set_dependencies(
        self,
        task_id: str,
        depends_on_ids: list[str],
    ) -> None:
        """Replace all dependencies for a task with the given list."""
        await self.session.execute(delete(TaskDependency).where(TaskDependency.task_id == task_id))
        for dep_id in depends_on_ids:
            self.session.add(
                TaskDependency(
                    id=str(uuid7()),
                    task_id=task_id,
                    depends_on_id=dep_id,
                )
            )
        await self.session.flush()

    async def get_dependency_ids(self, task_id: str) -> list[str]:
        """Return IDs of tasks that the given task depends on."""
        query = select(TaskDependency.depends_on_id).where(TaskDependency.task_id == task_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_dependent_ids(self, task_id: str) -> list[str]:
        """Return IDs of tasks that depend on the given task."""
        query = select(TaskDependency.task_id).where(TaskDependency.depends_on_id == task_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ── Bulk reconciliation ────────────────────────────────────────────────

    async def reconcile_tasks(
        self,
        plan_id: str,
        mission_id: str,
        new_task_defs: list[dict],
    ) -> dict[str, int]:
        """Reconcile existing Task rows against a new set of task definitions.

        Moved from MissionPlanOrchestrator._reconcile_task_states (Plan 72).

        Args:
            plan_id: The plan these tasks belong to.
            mission_id: The mission (for new task creation).
            new_task_defs: List of dicts with keys matching Task columns.
                Each must have an 'id' (UUID string) key.

        Returns:
            Stats dict: {"cancelled": N, "new": M, "updated": K}

        Behaviour:
          - Existing UUID in new defs: task UPDATED (description, instructions, etc.)
          - UUID in DB but not in new defs:
              * Non-terminal rows -> status = CANCELLED
              * Terminal rows (completed/skipped/cancelled) -> unchanged
              * Failed rows -> unchanged (preserve audit trail)
          - New UUID in defs: task row CREATED as PROPOSED
        """
        new_ids: set[str] = {d["id"] for d in new_task_defs}
        new_by_id: dict[str, dict] = {d["id"]: d for d in new_task_defs}

        existing_tasks = await self.get_by_plan_id(plan_id)
        existing_by_id: dict[str, Task] = {t.id: t for t in existing_tasks}

        cancelled_count = 0
        new_count = 0
        updated_count = 0

        # Handle existing tasks
        for task in existing_tasks:
            if task.id in new_ids:
                task_def = new_by_id[task.id]
                changed = False
                for field in (
                    "agent",
                    "description",
                    "instructions",
                    "inputs_json",
                    "verification_json",
                    "constraints_json",
                    "domain_tags",
                ):
                    if field in task_def and getattr(task, field) != task_def[field]:
                        setattr(task, field, task_def[field])
                        changed = True
                if changed:
                    updated_count += 1
                if task.status == TaskStatus.CANCELLED:
                    task.status = TaskStatus.PROPOSED
                continue

            # Task disappeared from the new plan
            if task.status in TERMINAL_TASK_STATUSES:
                continue
            if task.status == TaskStatus.FAILED:
                continue
            task.status = TaskStatus.CANCELLED
            cancelled_count += 1

        # Create new tasks
        for task_def in new_task_defs:
            if task_def["id"] in existing_by_id:
                continue
            await self.create_task(
                task_id=task_def["id"],
                plan_id=plan_id,
                mission_id=mission_id,
                agent=task_def["agent"],
                description=task_def["description"],
                instructions=task_def.get("instructions", ""),
                inputs_json=task_def.get("inputs_json", {}),
                verification_json=task_def.get("verification_json", {}),
                constraints_json=task_def.get("constraints_json", {}),
                domain_tags=task_def.get("domain_tags", []),
                status=TaskStatus.PROPOSED,
            )
            new_count += 1

        await self.session.flush()

        logger.debug(
            "Task reconciliation complete",
            plan_id=plan_id,
            cancelled=cancelled_count,
            new=new_count,
            updated=updated_count,
        )
        return {"cancelled": cancelled_count, "new": new_count, "updated": updated_count}

    # ── Bulk dependency rebuild ────────────────────────────────────────────

    async def rebuild_dependencies_for_task_ids(
        self,
        task_ids: set[str],
        dependency_map: dict[str, list[str]],
    ) -> None:
        """Replace all dependency edges for the given task IDs.

        Callers that already have task IDs (e.g. from reconcile_tasks)
        should use this to avoid a redundant query.

        Args:
            task_ids: Set of task UUIDs whose edges will be rebuilt.
            dependency_map: {task_id: [depends_on_id, ...]} for all tasks.
        """
        if task_ids:
            await self.session.execute(
                delete(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
            )

        for task_id, dep_ids in dependency_map.items():
            for dep_id in dep_ids:
                self.session.add(
                    TaskDependency(
                        id=str(uuid7()),
                        task_id=task_id,
                        depends_on_id=dep_id,
                    )
                )

        await self.session.flush()

    async def rebuild_dependencies(
        self,
        plan_id: str,
        dependency_map: dict[str, list[str]],
    ) -> None:
        """Replace all dependency edges for a plan.

        Convenience wrapper that fetches task IDs from the plan first.
        Prefer rebuild_dependencies_for_task_ids when task IDs are
        already available.
        """
        result = await self.session.execute(select(Task.id).where(Task.plan_id == plan_id))
        task_ids = set(result.scalars().all())
        await self.rebuild_dependencies_for_task_ids(task_ids, dependency_map)
