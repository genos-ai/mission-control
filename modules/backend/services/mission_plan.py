"""
Mission Plan Service (Plan 42, updated by Plan 72).

Business logic for the long-lived mission backlog. Thin orchestrator —
holds no execution logic itself; it delegates to other services
(PlanningAgent for refinement, handle_mission for dispatch).

Plan 72 changes: task operations now work directly on Task rows via
TaskRepository instead of PlanTaskState shadow table + JSON blobs.
"""

import uuid
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.core.protocols import EventBusProtocol, NoOpEventBus
from modules.backend.core.utils import utc_now
from modules.backend.events.types import (
    MissionPlanGateModeChangedEvent,
    MissionPlanTaskStatusChangedEvent,
)
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.mission_plan import VALID_GATE_MODES, MissionPlan, MissionPlanStatus
from modules.backend.models.task import Task, TaskStatus
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.services.base import BaseService

# States a task can transition *out of* when the user approves it.
_APPROVABLE_FROM = frozenset({TaskStatus.PROPOSED})

# States a task can be rejected *out of*.
_REJECTABLE_FROM = frozenset(
    {
        TaskStatus.PROPOSED,
        TaskStatus.APPROVED,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
    }
)


class MissionPlanService(BaseService):
    """Orchestrates the long-lived mission plan and its task states.

    Responsibilities:
        - Lazy plan creation per mission, inheriting gate_mode
        - Task state transitions: approve, reject, retry, set gate mode
        - Dependency closure enforcement so derived subsets are always
          DAG-valid when dispatch filters the plan
        - Validation of user input (gate mode, state machine edges)
    """

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBusProtocol | None = None,
    ) -> None:
        super().__init__(session)
        self._repo = MissionPlanRepository(session)
        self._mission_repo = MissionRepository(session)
        self._task_repo = TaskRepository(session)
        self._event_bus: EventBusProtocol = event_bus or NoOpEventBus()

    # ── Event emission helpers ──────────────────────────────────────────

    async def _emit(self, mission_id: str, event) -> None:
        """Publish a mission_plan.* event, swallowing failures.

        Event emission is best-effort — a Redis blip should never fail a
        plan mutation. We log the failure for observability and continue.
        """
        try:
            await self._event_bus.publish_to_mission(mission_id, event)
        except Exception as e:  # noqa: BLE001
            self._logger.warning(
                "Failed to publish mission_plan event",
                extra={
                    "event_type": event.event_type,
                    "mission_id": mission_id,
                    "error": str(e),
                },
            )

    async def _emit_task_transitions(
        self,
        mission_id: str,
        plan_id: str,
        transitions: list[tuple[str, str]],
        to_status: str,
        *,
        actor: str,
    ) -> None:
        """Fan out one task.status_changed event per transitioned row."""
        for task_id, from_status in transitions:
            await self._emit(
                mission_id,
                MissionPlanTaskStatusChangedEvent(
                    session_id=uuid.uuid4(),
                    source="mission_plan_service",
                    mission_id=mission_id,
                    plan_id=plan_id,
                    task_id=task_id,
                    from_status=from_status,
                    to_status=to_status,
                    actor=actor,
                ),
            )

    # ── Read ─────────────────────────────────────────────────────────────

    async def get_plan(self, mission_id: str) -> MissionPlan | None:
        """Return the mission's plan, or None if it hasn't been created yet."""
        return await self._repo.get_by_mission_id(mission_id)

    async def get_or_create_plan(self, mission_id: str) -> MissionPlan:
        """Return the mission's plan, creating it lazily on first access."""
        existing = await self._repo.get_by_mission_id(mission_id)
        if existing is not None:
            return existing

        mission = await self._mission_repo.get_by_id(mission_id)

        plan = await self._repo.create_for_mission(
            mission_id=mission_id,
            gate_mode=mission.gate_mode,
            budget_usd_ceiling=mission.budget_ceiling_usd,
        )
        self._log_operation(
            "MissionPlan created",
            mission_id=mission_id,
            plan_id=plan.id,
            gate_mode=plan.gate_mode,
        )
        return plan

    async def get_tasks(
        self,
        mission_plan_id: str,
        *,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        """List all tasks for a plan, optionally filtered by status."""
        return await self._task_repo.get_by_plan_id(
            mission_plan_id,
            status=status,
        )

    # ── Mutate plan-level config ────────────────────────────────────────

    async def set_gate_mode(
        self,
        mission_plan_id: str,
        gate_mode: str,
    ) -> MissionPlan:
        """Update the plan's autonomy mode."""
        if gate_mode not in VALID_GATE_MODES:
            raise ValidationError(
                f"Invalid gate_mode {gate_mode!r}. " f"Must be one of: {sorted(VALID_GATE_MODES)}"
            )
        plan = await self._repo.get_by_id(mission_plan_id)
        previous_mode = plan.gate_mode
        plan.gate_mode = gate_mode
        await self._session.flush()
        self._log_operation(
            "MissionPlan gate_mode changed",
            plan_id=mission_plan_id,
            gate_mode=gate_mode,
        )
        await self._emit(
            plan.mission_id,
            MissionPlanGateModeChangedEvent(
                session_id=uuid.uuid4(),
                source="mission_plan_service",
                mission_id=plan.mission_id,
                plan_id=plan.id,
                from_mode=previous_mode,
                to_mode=gate_mode,
            ),
        )
        return plan

    async def set_plan_status(
        self,
        mission_plan_id: str,
        status: MissionPlanStatus,
    ) -> MissionPlan:
        """Update the plan's lifecycle status."""
        plan = await self._repo.get_by_id(mission_plan_id)
        plan.status = status
        await self._session.flush()
        self._log_operation(
            "MissionPlan status changed",
            plan_id=mission_plan_id,
            status=status,
        )
        return plan

    async def pause_all_autonomous_plans(self) -> int:
        """Pause every ACTIVE plan running in autonomous gate mode.

        Emergency stop: a single UPDATE — no per-plan loop, no race
        window. The daemon's next tick sees zero active plans and idles.
        Returns the number of plans paused. Caller commits.
        """
        result = await self._session.execute(
            update(MissionPlan)
            .where(
                MissionPlan.status == MissionPlanStatus.ACTIVE,
                MissionPlan.gate_mode == "autonomous",
            )
            .values(status=MissionPlanStatus.PAUSED)
        )
        paused_count = result.rowcount
        self._log_operation(
            "Emergency stop: all autonomous plans paused",
            paused_count=paused_count,
        )
        return paused_count

    # ── Manual gate requests (Plan 80g) ─────────────────────────────────

    async def list_pending_gate_requests(self, mission_id: str) -> list[GateRequest]:
        """Return the mission's PENDING gate requests, oldest first."""
        result = await self._session.execute(
            select(GateRequest)
            .where(
                GateRequest.mission_id == mission_id,
                GateRequest.status == GateRequestStatus.PENDING,
            )
            .order_by(GateRequest.created_at.asc()),
        )
        return list(result.scalars().all())

    async def get_gate_request(
        self,
        mission_id: str,
        request_id: str,
    ) -> GateRequest:
        """Return one gate request scoped to the mission.

        Raises:
            NotFoundError: no such gate request for this mission.
        """
        result = await self._session.execute(
            select(GateRequest).where(
                GateRequest.id == request_id,
                GateRequest.mission_id == mission_id,
            ),
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Gate request {request_id} not found for mission {mission_id}.")
        return row

    async def get_pending_gate_request(
        self,
        mission_id: str,
        request_id: str,
    ) -> GateRequest:
        """Return one gate request, requiring it to still be PENDING.

        Raises:
            NotFoundError: no such gate request for this mission.
            ConflictError: the request was already decided / timed out /
                cancelled.
        """
        row = await self.get_gate_request(mission_id, request_id)
        current_status = row.status.value if hasattr(row.status, "value") else row.status
        if str(current_status) != GateRequestStatus.PENDING.value:
            raise ConflictError(
                f"Gate request {request_id} is not pending " f"(current status: {current_status})."
            )
        return row

    async def record_gate_decision(
        self,
        request_id: str,
        *,
        decision: dict[str, Any],
        decided_by_user_id: str,
    ) -> None:
        """Persist a reviewer decision on a gate request.

        Marks the row DECIDED with the decision payload and timestamp.
        Caller commits, then fires the dispatcher's asyncio.Event.
        """
        await self._session.execute(
            update(GateRequest)
            .where(GateRequest.id == request_id)
            .values(
                status=GateRequestStatus.DECIDED,
                decision_json=decision,
                decided_by_user_id=decided_by_user_id,
                decided_at=utc_now(),
            ),
        )
        self._log_operation(
            "Gate decision recorded",
            request_id=request_id,
            action=decision.get("action"),
        )

    # ── Task state transitions ──────────────────────────────────────────

    async def approve_task(
        self,
        mission_plan_id: str,
        task_id: str,
        user_id: str,
    ) -> list[Task]:
        """Approve a task AND all its transitive dependencies.

        Returns the list of tasks that were actually transitioned.
        Already-approved/running/completed tasks are left untouched.
        """
        plan = await self._repo.get_by_id(mission_plan_id)
        tasks = await self._task_repo.get_by_plan_id(mission_plan_id)

        # Build dependency graph for transitive closure
        required_ids = self._transitive_dependencies_from_tasks(tasks, task_id)
        required_ids.append(task_id)

        transitioned: list[Task] = []
        transition_pairs: list[tuple[str, str]] = []
        now = utc_now()

        tasks_by_id = {t.id: t for t in tasks}

        for tid in required_ids:
            task = tasks_by_id.get(tid)
            if task is None:
                raise NotFoundError(f"Task {tid!r} not found in plan")
            if task.status not in _APPROVABLE_FROM:
                continue
            previous = task.status
            task.status = TaskStatus.APPROVED
            task.approved_by_user_id = user_id
            task.approved_at = now
            transitioned.append(task)
            transition_pairs.append((task.id, previous))

        await self._session.flush()
        self._log_operation(
            "MissionPlan tasks approved",
            plan_id=mission_plan_id,
            target_task_id=task_id,
            transitioned_count=len(transitioned),
        )
        await self._emit_task_transitions(
            plan.mission_id,
            plan.id,
            transition_pairs,
            TaskStatus.APPROVED,
            actor=f"user:{user_id}",
        )
        return transitioned

    async def approve_all_proposed(
        self,
        mission_plan_id: str,
        user_id: str,
    ) -> list[str]:
        """Approve all tasks currently in PROPOSED state.

        Returns the list of task IDs that were transitioned to APPROVED.
        """
        proposed_tasks = await self._task_repo.get_by_plan_id(
            mission_plan_id,
            status=TaskStatus.PROPOSED,
        )
        if not proposed_tasks:
            return []

        all_transitioned: list[str] = []
        for task in proposed_tasks:
            transitioned = await self.approve_task(
                mission_plan_id,
                task.id,
                user_id,
            )
            all_transitioned.extend(t.id for t in transitioned)

        # Deduplicate (transitive approval may overlap)
        seen: set[str] = set()
        return [t for t in all_transitioned if not (t in seen or seen.add(t))]

    async def check_no_active_tasks(self, mission_plan_id: str) -> None:
        """Raise ConflictError if the plan has tasks in QUEUED or RUNNING state."""
        tasks = await self._task_repo.get_by_plan_id(mission_plan_id)
        active = [t for t in tasks if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)]
        if active:
            active_ids = [t.id[:8] for t in active]
            raise ConflictError(
                f"Plan has {len(active)} in-progress task(s): "
                f"{', '.join(active_ids[:5])}. "
                "Wait for completion or cancel before starting a new run."
            )

    async def reject_task(
        self,
        mission_plan_id: str,
        task_id: str,
        user_id: str,
    ) -> list[Task]:
        """Reject (cancel) a task AND all of its transitive dependents."""
        plan = await self._repo.get_by_id(mission_plan_id)
        tasks = await self._task_repo.get_by_plan_id(mission_plan_id)

        affected_ids = [task_id] + self._transitive_dependents_from_tasks(
            tasks,
            task_id,
        )

        tasks_by_id = {t.id: t for t in tasks}
        transitioned: list[Task] = []
        transition_pairs: list[tuple[str, str]] = []

        for tid in affected_ids:
            task = tasks_by_id.get(tid)
            if task is None:
                continue
            if task.status not in _REJECTABLE_FROM:
                continue
            previous = task.status
            task.status = TaskStatus.CANCELLED
            transitioned.append(task)
            transition_pairs.append((task.id, previous))

        await self._session.flush()
        self._log_operation(
            "MissionPlan tasks rejected",
            plan_id=mission_plan_id,
            target_task_id=task_id,
            user_id=user_id,
            transitioned_count=len(transitioned),
        )
        await self._emit_task_transitions(
            plan.mission_id,
            plan.id,
            transition_pairs,
            TaskStatus.CANCELLED,
            actor=f"user:{user_id}",
        )
        return transitioned

    async def retry_task(
        self,
        mission_plan_id: str,
        task_id: str,
        user_id: str,
    ) -> Task:
        """Move a failed task back into `approved` so it can be re-dispatched."""
        task = await self._task_repo.get_by_id(task_id)
        if task.status != TaskStatus.FAILED:
            raise ValidationError(
                f"Cannot retry task in state {task.status!r}. " f"Only failed tasks can be retried."
            )
        plan = await self._repo.get_by_id(mission_plan_id)
        task.status = TaskStatus.APPROVED
        task.approved_by_user_id = user_id
        task.approved_at = utc_now()
        task.retry_count += 1
        task.failure_reason = None
        await self._session.flush()
        self._log_operation(
            "MissionPlan task retried",
            plan_id=mission_plan_id,
            task_id=task_id,
            retry_count=task.retry_count,
        )
        await self._emit_task_transitions(
            plan.mission_id,
            plan.id,
            [(task.id, TaskStatus.FAILED)],
            TaskStatus.APPROVED,
            actor=f"user:{user_id}",
        )
        return task

    async def add_task(
        self,
        mission_plan_id: str,
        *,
        description: str,
        agent: str,
        instructions: str = "",
        dependencies: list[str] | None = None,
        inputs: dict | None = None,
    ) -> MissionPlan:
        """Add a single proposed task to the plan.

        Creates a Task row directly. If the plan is COMPLETED, it is
        reactivated. ARCHIVED plans reject.
        """
        plan = await self._repo.get_by_id(mission_plan_id)

        if plan.status == MissionPlanStatus.ARCHIVED:
            raise ValidationError(
                f"Cannot add tasks to archived plan {mission_plan_id}. "
                f"Create a new plan or un-archive first."
            )

        if plan.status == MissionPlanStatus.COMPLETED:
            self._log_operation(
                "Reactivating plan for new task",
                plan_id=mission_plan_id,
                previous_status=plan.status,
            )
            plan.status = MissionPlanStatus.ACTIVE
            await self._session.flush()

        # Create the task row
        task = await self._task_repo.create_task(
            plan_id=plan.id,
            mission_id=plan.mission_id,
            agent=agent,
            description=description,
            instructions=instructions or description,
            inputs_json=inputs or {},
            status=TaskStatus.PROPOSED,
        )

        # Set dependencies if provided
        if dependencies:
            await self._task_repo.set_dependencies(task.id, dependencies)

        self._log_operation(
            "MissionPlan task added manually",
            plan_id=mission_plan_id,
            task_id=task.id,
            agent=agent,
        )
        return await self._repo.get_by_id(mission_plan_id)

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _transitive_dependencies_from_tasks(
        tasks: list[Task],
        task_id: str,
    ) -> list[str]:
        """Return all tasks that `task_id` depends on, in topological order.

        Uses the Task.dependencies relationship (TaskDependency rows).
        """
        tasks_by_id = {t.id: t for t in tasks}
        if task_id not in tasks_by_id:
            raise NotFoundError(f"Task {task_id!r} not in plan")

        # Build adjacency: task_id -> [depends_on_ids]
        dep_map: dict[str, list[str]] = {}
        for t in tasks:
            dep_map[t.id] = [d.depends_on_id for d in t.dependencies]

        visited: set[str] = set()
        order: list[str] = []

        def _visit(tid: str) -> None:
            if tid in visited:
                return
            visited.add(tid)
            for dep_id in dep_map.get(tid, []):
                _visit(dep_id)
                if dep_id not in order and dep_id != task_id:
                    order.append(dep_id)

        _visit(task_id)
        return order

    @staticmethod
    def _transitive_dependents_from_tasks(
        tasks: list[Task],
        task_id: str,
    ) -> list[str]:
        """Return all tasks that transitively depend on `task_id`."""
        tasks_by_id = {t.id: t for t in tasks}
        if task_id not in tasks_by_id:
            raise NotFoundError(f"Task {task_id!r} not in plan")

        # Build reverse adjacency: dep_id -> [tasks that depend on dep_id]
        reverse: dict[str, list[str]] = defaultdict(list)
        for t in tasks:
            for dep in t.dependencies:
                reverse[dep.depends_on_id].append(t.id)

        visited: set[str] = set()
        order: list[str] = []
        queue: deque[str] = deque([task_id])

        while queue:
            current = queue.popleft()
            for dependent_id in reverse.get(current, []):
                if dependent_id in visited:
                    continue
                visited.add(dependent_id)
                order.append(dependent_id)
                queue.append(dependent_id)

        return order
