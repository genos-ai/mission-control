"""
Mission Plan Service (Plan 42).

Business logic for the long-lived mission backlog. Thin orchestrator —
holds no execution logic itself; it delegates to other services
(PlanningAgent for refinement, handle_mission for dispatch) in later
phases. Phase 1.0 scope: CRUD + task state transitions with dependency
closure.

State transitions follow Plan 42 §2.3. Approval is dependency-transitive
(§10.2) — approving a task auto-approves all transitive dependencies;
rejecting a task cancels all transitive dependents.
"""

from collections import defaultdict, deque
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.models.mission_plan import (
    VALID_GATE_MODES,
    MissionPlan,
    MissionPlanStatus,
    PlanTaskState,
    PlanTaskStatus,
    TERMINAL_PLAN_TASK_STATUSES,
)
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services.base import BaseService


# States a task can transition *out of* when the user approves it.
# Tasks already approved/running/completed are not touched by an approval
# call — this makes "approve with transitive deps" idempotent.
_APPROVABLE_FROM = frozenset({PlanTaskStatus.PROPOSED.value})

# States a task can be rejected *out of*. Rejecting a running task is
# explicitly not supported here — cancelling an in-flight run goes through
# the execution layer.
_REJECTABLE_FROM = frozenset({
    PlanTaskStatus.PROPOSED.value,
    PlanTaskStatus.APPROVED.value,
})


class MissionPlanService(BaseService):
    """Orchestrates the long-lived mission plan and its task states.

    Responsibilities (Phase 1.0):
        - Lazy plan creation per mission, inheriting gate_mode
        - Task state transitions: approve, reject, retry, set gate mode
        - Dependency closure enforcement so derived subsets are always
          DAG-valid when §10.1's dispatch path filters the TaskPlan
        - Validation of user input (gate mode, state machine edges)

    NOT yet (Phase 1.5/1.6):
        - `refine()` — Planning Agent delegation (needs refinement prompt)
        - `dispatch_approved()` — handle_mission integration
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._repo = MissionPlanRepository(session)
        self._mission_repo = MissionRepository(session)

    # ── Read ─────────────────────────────────────────────────────────────

    async def get_or_create_plan(self, mission_id: str) -> MissionPlan:
        """Return the mission's plan, creating it lazily on first access.

        The new plan inherits the mission's `gate_mode` so autonomy mode
        set at mission creation becomes the starting default. Subsequent
        changes to either are independent.
        """
        existing = await self._repo.get_by_mission_id(mission_id)
        if existing is not None:
            return existing

        # Fetch mission for gate_mode inheritance. NotFoundError bubbles up
        # — callers should have validated mission existence before this.
        mission = await self._mission_repo.get_by_id(mission_id)

        plan = await self._repo.create_for_mission(
            mission_id=mission_id,
            gate_mode=mission.gate_mode,
        )
        self._log_operation(
            "MissionPlan created",
            mission_id=mission_id,
            plan_id=plan.id,
            gate_mode=plan.gate_mode,
        )
        return plan

    async def get_task_states(
        self,
        mission_plan_id: str,
        *,
        status: PlanTaskStatus | None = None,
    ) -> list[PlanTaskState]:
        """List all task states for a plan, optionally filtered by status."""
        return await self._repo.get_task_states(mission_plan_id, status=status)

    # ── Mutate plan-level config ────────────────────────────────────────

    async def set_gate_mode(
        self,
        mission_plan_id: str,
        gate_mode: str,
    ) -> MissionPlan:
        """Update the plan's autonomy mode.

        Validates that `gate_mode` is one of the modes supported by the
        existing gate system (config/settings/gate.yaml). See Plan 42 §10.4.
        """
        if gate_mode not in VALID_GATE_MODES:
            raise ValidationError(
                f"Invalid gate_mode {gate_mode!r}. "
                f"Must be one of: {sorted(VALID_GATE_MODES)}"
            )
        plan = await self._repo.get_by_id(mission_plan_id)
        plan.gate_mode = gate_mode
        await self._session.flush()
        self._log_operation(
            "MissionPlan gate_mode changed",
            plan_id=mission_plan_id,
            gate_mode=gate_mode,
        )
        return plan

    async def set_plan_status(
        self,
        mission_plan_id: str,
        status: MissionPlanStatus,
    ) -> MissionPlan:
        """Update the plan's lifecycle status (active/paused/completed/archived)."""
        plan = await self._repo.get_by_id(mission_plan_id)
        plan.status = status.value
        await self._session.flush()
        self._log_operation(
            "MissionPlan status changed",
            plan_id=mission_plan_id,
            status=status.value,
        )
        return plan

    # ── Task state transitions ──────────────────────────────────────────

    async def approve_task(
        self,
        mission_plan_id: str,
        task_id: str,
        user_id: str,
    ) -> list[PlanTaskState]:
        """Approve a task AND all its transitive dependencies.

        Returns the list of task states that were actually transitioned
        (in dependency order). Already-approved / running / completed
        tasks are left untouched — this makes the operation idempotent
        and safe to call repeatedly.

        Plan 42 §10.2: approval is dependency-transitive to guarantee
        the derived subset dispatched at run time forms a closed DAG.
        """
        plan = await self._repo.get_by_id(mission_plan_id)
        task_plan = self._get_task_plan_or_raise(plan)

        # Build the set of tasks that must be approved (target + all
        # transitive deps). Use topological order so deps are approved
        # before their dependents.
        required_ids = self._transitive_dependencies(task_plan, task_id)
        required_ids.append(task_id)

        transitioned: list[PlanTaskState] = []
        now = utc_now()

        for tid in required_ids:
            state = await self._repo.get_task_state_required(
                mission_plan_id, tid,
            )
            if state.status not in _APPROVABLE_FROM:
                # Already approved / running / done — skip silently.
                continue
            state.status = PlanTaskStatus.APPROVED.value
            state.approved_by_user_id = user_id
            state.approved_at = now
            transitioned.append(state)

        await self._session.flush()
        self._log_operation(
            "MissionPlan tasks approved",
            plan_id=mission_plan_id,
            target_task_id=task_id,
            transitioned_count=len(transitioned),
            transitioned_task_ids=[s.task_id for s in transitioned],
        )
        return transitioned

    async def reject_task(
        self,
        mission_plan_id: str,
        task_id: str,
        user_id: str,
    ) -> list[PlanTaskState]:
        """Reject (cancel) a task AND all of its transitive dependents.

        Anything that depends on the rejected task becomes undispatch-
        able, so those tasks are cancelled too. Running tasks are not
        touched — rejecting a running task requires cancelling the run
        through ExecutionService.

        Plan 42 §10.2: rejection is transitive in the opposite direction
        from approval.
        """
        plan = await self._repo.get_by_id(mission_plan_id)
        task_plan = self._get_task_plan_or_raise(plan)

        # Collect the target plus everything downstream of it.
        affected_ids = [task_id] + self._transitive_dependents(
            task_plan, task_id,
        )

        transitioned: list[PlanTaskState] = []

        for tid in affected_ids:
            state = await self._repo.get_task_state(mission_plan_id, tid)
            if state is None:
                continue
            if state.status not in _REJECTABLE_FROM:
                # Running / completed / failed / already cancelled — skip.
                # Failed tasks need an explicit retry to re-approve; we
                # don't cancel them as a side effect of rejecting a peer.
                continue
            state.status = PlanTaskStatus.CANCELLED.value
            transitioned.append(state)

        await self._session.flush()
        self._log_operation(
            "MissionPlan tasks rejected",
            plan_id=mission_plan_id,
            target_task_id=task_id,
            user_id=user_id,
            transitioned_count=len(transitioned),
        )
        return transitioned

    async def retry_task(
        self,
        mission_plan_id: str,
        task_id: str,
        user_id: str,
    ) -> PlanTaskState:
        """Move a failed task back into `approved` so it can be re-dispatched.

        Only failed tasks can be retried. Other states raise ValidationError.
        Approvals for transitive deps are NOT re-walked — retry is scoped
        to the single failed task; its deps already completed successfully
        last run.
        """
        state = await self._repo.get_task_state_required(
            mission_plan_id, task_id,
        )
        if state.status != PlanTaskStatus.FAILED.value:
            raise ValidationError(
                f"Cannot retry task in state {state.status!r}. "
                f"Only failed tasks can be retried."
            )
        state.status = PlanTaskStatus.APPROVED.value
        state.approved_by_user_id = user_id
        state.approved_at = utc_now()
        state.retry_count += 1
        state.failure_reason = None
        await self._session.flush()
        self._log_operation(
            "MissionPlan task retried",
            plan_id=mission_plan_id,
            task_id=task_id,
            retry_count=state.retry_count,
        )
        return state

    # ── Helpers ─────────────────────────────────────────────────────────

    def _get_task_plan_or_raise(self, plan: MissionPlan) -> TaskPlan:
        """Deserialize the plan's task_plan_json into a TaskPlan model."""
        if plan.task_plan_json is None:
            raise ValidationError(
                f"MissionPlan {plan.id} has no tasks yet. "
                f"Refine the plan before approving tasks."
            )
        return TaskPlan.model_validate(plan.task_plan_json)

    @staticmethod
    def _transitive_dependencies(
        task_plan: TaskPlan,
        task_id: str,
    ) -> list[str]:
        """Return all tasks that `task_id` depends on, in topological order.

        Walk the `dependencies` edges backward from `task_id`. The return
        order is deps-first so callers iterating it approve the deepest
        prerequisites before their dependents.

        Raises NotFoundError if `task_id` is not in the plan.
        """
        if task_plan.get_task(task_id) is None:
            raise NotFoundError(f"Task {task_id!r} not in current plan")

        by_id = {t.task_id: t for t in task_plan.tasks}

        # BFS/DFS the reverse graph
        visited: set[str] = set()
        order: list[str] = []

        def _visit(tid: str) -> None:
            if tid in visited:
                return
            visited.add(tid)
            task = by_id.get(tid)
            if task is None:
                return
            for dep_id in task.dependencies:
                _visit(dep_id)
                if dep_id not in order and dep_id != task_id:
                    order.append(dep_id)

        _visit(task_id)
        return order

    @staticmethod
    def _transitive_dependents(
        task_plan: TaskPlan,
        task_id: str,
    ) -> list[str]:
        """Return all tasks that transitively depend on `task_id`.

        Builds a reverse-adjacency list once, then BFS forward. Order is
        the BFS traversal order (shallowest dependents first), which is
        fine because rejection is an atomic state flip — order only
        matters for audit log readability.
        """
        if task_plan.get_task(task_id) is None:
            raise NotFoundError(f"Task {task_id!r} not in current plan")

        # Build reverse adjacency: dep_id -> [tasks that depend on dep_id]
        reverse: dict[str, list[str]] = defaultdict(list)
        for task in task_plan.tasks:
            for dep_id in task.dependencies:
                reverse[dep_id].append(task.task_id)

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
