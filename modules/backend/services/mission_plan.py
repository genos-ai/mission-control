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
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.agent_registry import get_registry
from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.core.protocols import EventBusProtocol, NoOpEventBus
from modules.backend.core.utils import utc_now
from modules.backend.events.types import (
    MissionPlanGateModeChangedEvent,
    MissionPlanTaskStatusChangedEvent,
)
from modules.backend.models.mission_plan import (
    VALID_GATE_MODES,
    MissionPlan,
    MissionPlanStatus,
    PlanTaskState,
    PlanTaskStatus,
)
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services.base import BaseService


# States a task can transition *out of* when the user approves it.
# Tasks already approved/running/completed are not touched by an approval
# call — this makes "approve with transitive deps" idempotent.
_APPROVABLE_FROM = frozenset({PlanTaskStatus.PROPOSED})

# States a task can be rejected *out of*. Rejecting a running task is
# explicitly not supported here — cancelling an in-flight run goes through
# the execution layer.
_REJECTABLE_FROM = frozenset({
    PlanTaskStatus.PROPOSED,
    PlanTaskStatus.APPROVED,
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

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBusProtocol | None = None,
    ) -> None:
        super().__init__(session)
        self._repo = MissionPlanRepository(session)
        self._mission_repo = MissionRepository(session)
        self._event_bus: EventBusProtocol = event_bus or NoOpEventBus()

    # Plan 52: Supervisor loop and Director followups are handled by
    # Temporal workflows (MissionRunWorkflow, ChatTurnWorkflow).
    # The inline _run_post_run_reviewer, _apply_supervisor_decision,
    # _create_agent_turn_runner, and _noop_agent_turn_runner methods
    # have been removed. See temporal/mission_run_workflow.py and
    # temporal/supervisor_activities.py.

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
            budget_usd_ceiling=mission.budget_ceiling_usd,
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
        """Update the plan's lifecycle status (active/paused/completed/archived)."""
        plan = await self._repo.get_by_id(mission_plan_id)
        plan.status = status
        await self._session.flush()
        self._log_operation(
            "MissionPlan status changed",
            plan_id=mission_plan_id,
            status=status,
        )
        return plan

    # ── Orchestration methods ──────────────────────────────────────────
    # refine(), _reconcile_task_states(), run_objective(),
    # dispatch_autonomous(), _start_temporal_run_workflow(),
    # dispatch_approved(), and related helpers live in
    # MissionPlanOrchestrator (see mission_plan_orchestrator.py).

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
        transition_pairs: list[tuple[str, str]] = []  # (task_id, previous_status)
        now = utc_now()

        for tid in required_ids:
            state = await self._repo.get_task_state_required(
                mission_plan_id, tid,
            )
            if state.status not in _APPROVABLE_FROM:
                # Already approved / running / done — skip silently.
                continue
            previous = state.status
            state.status = PlanTaskStatus.APPROVED
            state.approved_by_user_id = user_id
            state.approved_at = now
            transitioned.append(state)
            transition_pairs.append((state.task_id, previous))

        await self._session.flush()
        self._log_operation(
            "MissionPlan tasks approved",
            plan_id=mission_plan_id,
            target_task_id=task_id,
            transitioned_count=len(transitioned),
            transitioned_task_ids=[s.task_id for s in transitioned],
        )
        await self._emit_task_transitions(
            plan.mission_id, plan.id,
            transition_pairs,
            PlanTaskStatus.APPROVED,
            actor=f"user:{user_id}",
        )
        return transitioned

    async def approve_all_proposed(
        self,
        mission_plan_id: str,
        user_id: str,
    ) -> list[str]:
        """Approve all tasks currently in PROPOSED state.

        Calls approve_task() for each proposed task, which handles
        transitive dependency approval. Returns the list of task_ids
        that were transitioned to APPROVED.
        """
        states = await self._repo.get_task_states(
            mission_plan_id, status=PlanTaskStatus.PROPOSED,
        )
        if not states:
            return []

        all_transitioned: list[str] = []
        for state in states:
            transitioned = await self.approve_task(
                mission_plan_id, state.task_id, user_id,
            )
            all_transitioned.extend(s.task_id for s in transitioned)

        # Deduplicate (transitive approval may overlap)
        seen: set[str] = set()
        return [t for t in all_transitioned if not (t in seen or seen.add(t))]

    async def check_no_active_tasks(self, mission_plan_id: str) -> None:
        """Raise ConflictError if the plan has tasks in QUEUED or RUNNING state.

        Prevents refine() from clobbering in-progress tasks when a second
        run_objective() is called on the same mission concurrently.
        """
        active_statuses = (PlanTaskStatus.QUEUED.value, PlanTaskStatus.RUNNING.value)
        all_states = await self._repo.get_task_states(mission_plan_id)
        active = [s for s in all_states if s.status in active_statuses]
        if active:
            active_ids = [s.task_id for s in active]
            raise ConflictError(
                f"Plan has {len(active)} in-progress task(s): "
                f"{', '.join(active_ids[:5])}. "
                "Wait for completion or cancel before starting a new run."
            )

    # ── Task state transitions ──────────────────────────────────────────

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
        transition_pairs: list[tuple[str, str]] = []

        for tid in affected_ids:
            state = await self._repo.get_task_state(mission_plan_id, tid)
            if state is None:
                continue
            if state.status not in _REJECTABLE_FROM:
                # Running / completed / failed / already cancelled — skip.
                # Failed tasks need an explicit retry to re-approve; we
                # don't cancel them as a side effect of rejecting a peer.
                continue
            previous = state.status
            state.status = PlanTaskStatus.CANCELLED
            transitioned.append(state)
            transition_pairs.append((state.task_id, previous))

        await self._session.flush()
        self._log_operation(
            "MissionPlan tasks rejected",
            plan_id=mission_plan_id,
            target_task_id=task_id,
            user_id=user_id,
            transitioned_count=len(transitioned),
        )
        await self._emit_task_transitions(
            plan.mission_id, plan.id,
            transition_pairs,
            PlanTaskStatus.CANCELLED,
            actor=f"user:{user_id}",
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
        if state.status != PlanTaskStatus.FAILED:
            raise ValidationError(
                f"Cannot retry task in state {state.status!r}. "
                f"Only failed tasks can be retried."
            )
        plan = await self._repo.get_by_id(mission_plan_id)
        state.status = PlanTaskStatus.APPROVED
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
        await self._emit_task_transitions(
            plan.mission_id, plan.id,
            [(state.task_id, PlanTaskStatus.FAILED)],
            PlanTaskStatus.APPROVED,
            actor=f"user:{user_id}",
        )
        return state

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
        """Append a single proposed task to the plan's task_plan_json.

        Initialises task_plan_json if the plan has none yet. The new task
        is appended at the end with status=proposed and a fresh task_id.
        A PlanTaskState row is created so approve/reject/dispatch all work.

        If the plan is COMPLETED, it is reactivated to ACTIVE before
        adding the task. ARCHIVED plans reject — they are terminal and
        read-only. PAUSED plans accept new tasks without status change
        (they'll dispatch when unpaused).
        """
        plan = await self._repo.get_by_id(mission_plan_id)

        if plan.status == MissionPlanStatus.ARCHIVED:
            raise ValidationError(
                f"Cannot add tasks to archived plan {mission_plan_id}. "
                f"Create a new plan or un-archive first."
            )

        # Reactivate completed plans so new tasks can be dispatched.
        if plan.status == MissionPlanStatus.COMPLETED:
            self._log_operation(
                "Reactivating plan for new task",
                plan_id=mission_plan_id,
                previous_status=plan.status,
            )
            plan.status = MissionPlanStatus.ACTIVE
            await self._session.flush()

        from modules.backend.agents.mission.planning.build_session import (
            extract_task_sequence,
            generate_task_id,
            resolve_agent_version,
        )

        agent_version = resolve_agent_version(agent)

        # Versioned task ID: v{version}-task-{NNN}
        existing: dict = plan.task_plan_json or {}
        version = plan.version
        existing_tasks = existing.get("tasks", [])
        max_seq = max(
            (extract_task_sequence(t.get("task_id", "")) for t in existing_tasks),
            default=0,
        )
        task_id = generate_task_id(version, max_seq + 1)
        task_body: dict = {
            "task_id": task_id,
            "agent": agent,
            "agent_version": agent_version,
            "description": description,
            "instructions": instructions or description,
            "dependencies": dependencies or [],
        }
        if inputs:
            task_body["inputs"] = inputs

        tasks = list(existing.get("tasks", []))
        tasks.append(task_body)

        # Initialise the full TaskPlan scaffold if starting from scratch.
        # TaskPlan requires mission_id, summary, estimated_cost_usd,
        # estimated_duration_seconds — dispatch validates these on read.
        if not existing or "mission_id" not in existing:
            existing = {
                "version": f"{version}.0.0",
                "mission_id": plan.mission_id,
                "summary": description,
                "estimated_cost_usd": 5.0,
                "estimated_duration_seconds": 300,
                "execution_hints": {"critical_path": [task_id]},
            }
        plan.task_plan_json = {**existing, "tasks": tasks}
        await self._session.flush()

        task_state = PlanTaskState(
            id=str(uuid.uuid4()),
            mission_plan_id=plan.id,
            task_id=task_id,
            status=PlanTaskStatus.PROPOSED.name,
        )
        self._session.add(task_state)
        await self._session.flush()

        self._log_operation(
            "MissionPlan task added manually",
            plan_id=mission_plan_id,
            task_id=task_id,
            agent=agent,
        )
        return await self._repo.get_by_id(mission_plan_id)

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
