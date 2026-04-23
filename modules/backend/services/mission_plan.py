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

from modules.backend.agents.mission_control.models import (
    EventBusProtocol,
    NoOpEventBus,
)
from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.events.types import (
    MissionPlanGateModeChangedEvent,
    MissionPlanRefinedEvent,
    MissionPlanTaskStatusChangedEvent,
)
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
from modules.backend.services.mission_plan_dispatch import MissionPlanDispatchMixin


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


class MissionPlanService(MissionPlanDispatchMixin, BaseService):
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
        plan.status = status.value
        await self._session.flush()
        self._log_operation(
            "MissionPlan status changed",
            plan_id=mission_plan_id,
            status=status.value,
        )
        return plan

    # ── Refinement (Planning Agent delegation) ──────────────────────────

    async def refine(
        self,
        mission_plan_id: str,
        instructions: str,
        user_id: str,
        *,
        mission_budget_usd: float = 10.0,
    ) -> MissionPlan:
        """Refine the plan by delegating to the Planning Agent.

        Plan 42 §10.4: the Director never authors tasks directly — when a
        user describes changes in chat, the Director calls this method
        (via a tool) which invokes the Planning Agent in refinement mode.
        The agent receives the current TaskPlan + the user's instructions
        and returns a new TaskPlan that preserves task_ids where possible.

        Task state reconciliation (Plan 42 §10.3 + §10.4):
          - Tasks whose task_id survived refinement keep their state row
            unchanged (approvals, execution links, retry counts).
          - Tasks whose task_id no longer exists in the new plan have
            their non-terminal state rows marked CANCELLED; terminal
            rows (completed / failed / skipped) are preserved so the
            audit trail survives.
          - New task_ids get fresh `proposed` state rows.

        Version is bumped on every successful refinement.

        Args:
            mission_plan_id: The plan to refine.
            instructions: Natural-language refinement request from the user.
            user_id: The user (via the Director) requesting the refinement.
                Currently used for audit logging only.
            mission_budget_usd: Budget to validate the new plan against.
                Defaults to 10.0 — callers that have a per-plan budget
                ceiling should pass it in explicitly.

        Returns:
            The refreshed MissionPlan with the new task_plan_json and
            bumped version. Task states are updated in-place in the same
            transaction.

        Raises:
            NotFoundError: If the plan does not exist.
            ValidationError: If the Planning Agent returns an invalid
                TaskPlan (fails plan_validator's 11 rules).
        """
        from modules.backend.agents.mission_control.helpers.agent_executor import (
            _call_planning_agent,
        )
        from modules.backend.agents.mission_control.plan_validator import validate_plan
        from modules.backend.agents.mission_control.roster import (
            derive_roster_from_team,
        )
        from modules.backend.repositories.mission import MissionRepository

        plan = await self._repo.get_by_id(mission_plan_id)

        # Load mission + brief + roster — same inputs handle_mission uses
        mission = await MissionRepository(self._session).get_by_id(plan.mission_id)
        roster = await derive_roster_from_team(plan.mission_id, self._session)

        # The "mission brief" for refinement is the mission's own brief; the
        # refinement instructions are layered on top inside the prompt.
        brief = mission.brief or mission.description or mission.name

        self._log_operation(
            "MissionPlan refinement requested",
            plan_id=mission_plan_id,
            user_id=user_id,
            instructions_preview=instructions[:200],
            has_current_plan=plan.task_plan_json is not None,
        )

        # The new plan version is current + 1 (version gets bumped after
        # refinement succeeds). Pass it so the Planning Agent generates
        # task IDs with the correct version prefix: v{N}-task-001, etc.
        next_version = plan.version + 1

        planning_result = await _call_planning_agent(
            prompt=brief,
            roster=roster,
            upstream_context=None,
            event_bus=self._event_bus,
            mission_id=plan.mission_id,
            current_plan=plan.task_plan_json,
            refinement_instructions=instructions,
            plan_version=next_version,
        )

        try:
            new_plan = TaskPlan.model_validate(planning_result["task_plan"])
        except Exception as e:
            raise ValidationError(
                f"Planning Agent returned an invalid TaskPlan: {e}"
            ) from e

        budget = plan.budget_usd_ceiling or mission_budget_usd
        validation = validate_plan(new_plan, roster, budget)
        if not validation.is_valid:
            raise ValidationError(
                "Refined TaskPlan failed validation: "
                + "; ".join(validation.errors)
            )

        # Reconcile task states
        reconcile_stats = await self._reconcile_task_states(plan, new_plan)

        # Replace the plan body and bump version
        plan.task_plan_json = new_plan.model_dump()
        plan.version += 1

        await self._session.flush()

        self._log_operation(
            "MissionPlan refined",
            plan_id=mission_plan_id,
            new_version=plan.version,
            new_task_count=len(new_plan.tasks),
        )

        await self._emit(
            plan.mission_id,
            MissionPlanRefinedEvent(
                session_id=uuid.uuid4(),
                source="mission_plan_service",
                mission_id=plan.mission_id,
                plan_id=plan.id,
                version=plan.version,
                task_count=len(new_plan.tasks),
                cancelled_count=reconcile_stats["cancelled"],
                new_count=reconcile_stats["new"],
            ),
        )

        # Refetch with task_states relationship loaded
        return await self._repo.get_by_mission_id_required(plan.mission_id)

    async def _reconcile_task_states(
        self,
        plan: MissionPlan,
        new_plan: TaskPlan,
    ) -> dict[str, int]:
        """Reconcile plan_task_states rows against a new TaskPlan body.

        Returns a stats dict: {"cancelled": N, "new": M}. The caller uses
        these to populate MissionPlanRefinedEvent so subscribers know
        how many rows actually changed during reconciliation.

        Behaviour:
          - Existing task_ids that survived: state row left as-is.
          - Existing task_ids that disappeared:
              * Non-terminal rows -> status = CANCELLED (soft delete)
              * Terminal rows (completed / skipped / cancelled) -> unchanged
                so the audit trail survives. Failed rows are also left as-is
                so the user can still see what went wrong in a prior run.
          - New task_ids: fresh PROPOSED state row.
        """
        new_task_ids: set[str] = {t.task_id for t in new_plan.tasks}
        existing_states = await self._repo.get_task_states(plan.id)
        existing_by_id = {s.task_id: s for s in existing_states}

        cancelled_count = 0
        new_count = 0

        reset_count = 0

        # Handle existing states
        for state in existing_states:
            if state.task_id in new_task_ids:
                # Task survived refinement. If its state is cancelled
                # (from a prior refinement that removed it), reset to
                # proposed so it's actionable again.
                if state.status == PlanTaskStatus.CANCELLED.value:
                    state.status = PlanTaskStatus.PROPOSED.value
                    reset_count += 1
                continue
            # Task disappeared from the new plan
            status_enum = PlanTaskStatus(state.status)
            if status_enum in TERMINAL_PLAN_TASK_STATUSES:
                continue  # already terminal, leave as-is
            if status_enum == PlanTaskStatus.FAILED:
                continue  # preserve failed rows for audit
            state.status = PlanTaskStatus.CANCELLED.value
            cancelled_count += 1

        # Create fresh PROPOSED rows for new task_ids
        for new_task in new_plan.tasks:
            if new_task.task_id in existing_by_id:
                continue
            await self._repo.create_task_state(plan.id, new_task.task_id)
            new_count += 1

        await self._session.flush()

        self._log_debug(
            "Task states reconciled",
            plan_id=plan.id,
            cancelled_count=cancelled_count,
            new_count=new_count,
            reset_count=reset_count,
            total_after=len(new_task_ids),
        )
        return {"cancelled": cancelled_count, "new": new_count, "reset": reset_count}

    # ── Dispatch (Phase 1.6) ────────────────────────────────────────────
    # dispatch_approved, _write_back_task_results, _resolve_task_execution_id,
    # _derive_subset_task_plan, and _post_run_supervisor are provided by
    # MissionPlanDispatchMixin (see mission_plan_dispatch.py).

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
            state.status = PlanTaskStatus.APPROVED.value
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
            PlanTaskStatus.APPROVED.value,
            actor=f"user:{user_id}",
        )
        return transitioned

    # ── Unified execution entry point (Plan 62) ────────────────────────

    async def run_objective(
        self,
        mission_id: str,
        objective: str,
        user_id: str,
        *,
        session_id: str | None = None,
        gate_mode: str | None = None,
        budget_ceiling_usd: float | None = None,
        async_dispatch: bool = False,
    ) -> dict:
        """Create/refine a plan from an objective and dispatch it.

        Unified entry point for all execution — CLI, chat, frontend.
        Single-task objectives produce single-task plans. Complex objectives
        produce multi-task plans. Both go through the full plan infrastructure
        (task states, supervisor, budget tracking, audit trail).

        Args:
            mission_id: The mission to execute against.
            objective: Natural-language objective for the Planning Agent.
            user_id: The user requesting execution.
            session_id: Session for event publishing (optional).
            gate_mode: Override the plan's gate mode (optional).
            budget_ceiling_usd: Override the plan's budget (optional).
            async_dispatch: If False (default), calls dispatch_approved()
                and blocks until all tasks complete (CLI mode). If True,
                starts a Temporal MissionRunWorkflow for autonomous
                multi-wave execution (chat/frontend mode). Returns
                outcome_status="temporal_unavailable" if Temporal is
                not enabled — never silently falls back to blocking.

        Returns:
            dict with: plan_id, plan_version, task_count, outcome_status,
            dispatched_task_ids (sync only), total_cost_usd (sync only).
            In async mode, outcome_status is "dispatching" or
            "temporal_unavailable".

        Raises:
            ConflictError: If the plan has tasks in QUEUED or RUNNING state.
            ValidationError: If the Planning Agent returns an invalid plan.
            NotFoundError: If the mission does not exist.
        """
        # 1. Get or create the plan
        plan = await self.get_or_create_plan(mission_id)

        # 2. Apply overrides
        if gate_mode is not None and gate_mode in VALID_GATE_MODES:
            plan.gate_mode = gate_mode
        if budget_ceiling_usd is not None:
            plan.budget_usd_ceiling = budget_ceiling_usd
        await self._session.flush()

        # 3. Concurrency guard — reject if tasks are in-flight
        await self._check_no_active_tasks(plan.id)

        # 4. Refine: Planning Agent decomposes objective into TaskPlan
        budget = plan.budget_usd_ceiling or 10.0
        plan = await self.refine(
            plan.id,
            objective,
            user_id,
            mission_budget_usd=budget,
        )

        task_plan = self._get_task_plan_or_raise(plan)
        task_count = len(task_plan.tasks)

        # 5. Auto-approve (gate mode permitting)
        effective_gate = plan.gate_mode or "off"
        if effective_gate == "interactive":
            self._log_operation(
                "run_objective: interactive gate — stopping after refine",
                plan_id=plan.id,
                mission_id=mission_id,
                task_count=task_count,
            )
            return {
                "plan_id": plan.id,
                "plan_version": plan.version,
                "task_count": task_count,
                "outcome_status": "awaiting_approval",
                "dispatched_task_ids": [],
                "total_cost_usd": 0.0,
            }

        approved_ids = await self.approve_all_proposed(plan.id, user_id)

        if not approved_ids:
            return {
                "plan_id": plan.id,
                "plan_version": plan.version,
                "task_count": task_count,
                "outcome_status": "no_tasks_to_approve",
                "dispatched_task_ids": [],
                "total_cost_usd": 0.0,
            }

        # 6. Dispatch
        if async_dispatch:
            # Start Temporal MissionRunWorkflow for autonomous multi-wave
            # execution. Falls back to inline dispatch if Temporal is disabled.
            workflow_id = await self._start_temporal_run_workflow(
                plan, session_id,
            )
            self._log_operation(
                "run_objective: async dispatch — Temporal workflow started"
                if workflow_id
                else "run_objective: async dispatch — Temporal unavailable, returning error",
                plan_id=plan.id,
                mission_id=mission_id,
                approved_task_ids=approved_ids,
                workflow_id=workflow_id,
            )
            if workflow_id:
                return {
                    "plan_id": plan.id,
                    "plan_version": plan.version,
                    "task_count": task_count,
                    "outcome_status": "dispatching",
                    "dispatched_task_ids": approved_ids,
                    "total_cost_usd": 0.0,
                    "workflow_id": workflow_id,
                }
            # Temporal not available — refuse rather than silently
            # blocking the caller (e.g. a Director chat turn) for minutes.
            return {
                "plan_id": plan.id,
                "plan_version": plan.version,
                "task_count": task_count,
                "outcome_status": "temporal_unavailable",
                "dispatched_task_ids": [],
                "total_cost_usd": 0.0,
            }

        # Sync dispatch — block until complete
        result = await self.dispatch_approved(
            plan.id,
            user_id,
            session_id=session_id,
        )
        result["plan_id"] = plan.id
        result["plan_version"] = plan.version
        result["task_count"] = task_count
        return result

    async def dispatch_autonomous(
        self,
        mission_plan_id: str,
        session_id: str | None = None,
    ) -> dict | None:
        """Start a Temporal MissionRunWorkflow for autonomous multi-wave execution.

        Returns a dict compatible with DispatchApprovedResponse on success,
        or None if Temporal is not available (caller should return an error
        rather than falling back to blocking inline dispatch).

        The workflow handles the full supervisor loop: execute → evaluate →
        advance/refine/escalate → repeat until done or circuit-breaker trips.
        """
        plan = await self._repo.get_by_id(mission_plan_id)
        workflow_id = await self._start_temporal_run_workflow(
            plan, session_id,
        )
        if workflow_id is None:
            return None

        approved_states = await self._repo.get_task_states(
            mission_plan_id, status=PlanTaskStatus.APPROVED,
        )
        return {
            "outcome_status": "dispatching",
            "dispatched_task_ids": [s.task_id for s in approved_states],
            "total_cost_usd": 0.0,
            "new_total_spent_usd": plan.total_spent_usd,
            "workflow_id": workflow_id,
        }

    async def _start_temporal_run_workflow(
        self,
        plan: MissionPlan,
        session_id: str | None,
    ) -> str | None:
        """Start a MissionRunWorkflow via Temporal. Returns workflow_id or None."""
        try:
            from modules.backend.core.config import get_app_config
            from modules.backend.temporal.client import get_temporal_client
            from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
            from modules.backend.temporal.models import MissionWorkflowInput

            client = await get_temporal_client()
            config = get_app_config()

            mission = await MissionRepository(self._session).get_by_id(plan.mission_id)
            brief = mission.brief or mission.description or mission.name
            remaining_budget = (plan.budget_usd_ceiling or 10.0) - plan.total_spent_usd

            workflow_input = MissionWorkflowInput(
                mission_run_id=plan.id,
                session_id=session_id or str(uuid.uuid4()),
                mission_brief=brief,
                roster_name=mission.default_roster or "default",
                mission_budget_usd=max(remaining_budget, 0.01),
                mission_id=plan.mission_id,
                execution_mode=mission.execution_environment,
            )

            workflow_id = f"mission-run-{plan.id[:12]}-{uuid.uuid4().hex[:8]}"
            await client.start_workflow(
                MissionRunWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=config.temporal.task_queue,
            )
            return workflow_id

        except RuntimeError:
            # Temporal not enabled — caller falls back to inline dispatch
            return None

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

    async def _check_no_active_tasks(self, mission_plan_id: str) -> None:
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
            state.status = PlanTaskStatus.CANCELLED.value
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
            PlanTaskStatus.CANCELLED.value,
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
        if state.status != PlanTaskStatus.FAILED.value:
            raise ValidationError(
                f"Cannot retry task in state {state.status!r}. "
                f"Only failed tasks can be retried."
            )
        plan = await self._repo.get_by_id(mission_plan_id)
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
        await self._emit_task_transitions(
            plan.mission_id, plan.id,
            [(state.task_id, PlanTaskStatus.FAILED.value)],
            PlanTaskStatus.APPROVED.value,
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
    ) -> MissionPlan:
        """Append a single proposed task to the plan's task_plan_json.

        Initialises task_plan_json if the plan has none yet. The new task
        is appended at the end with status=proposed and a fresh task_id.
        A PlanTaskState row is created so approve/reject/dispatch all work.
        """
        plan = await self._repo.get_by_id(mission_plan_id)

        # Look up agent version from registry so the plan validator
        # doesn't reject "latest" as not matching the roster entry.
        from modules.backend.agents.mission_control.registry import get_registry
        registry = get_registry()
        agent_version = "1.0.0"
        if registry.has(agent):
            agent_version = registry.get(agent).version or "1.0.0"

        # Versioned task ID: v{version}-task-{NNN}
        existing: dict = plan.task_plan_json or {}
        version = plan.version
        version_prefix = f"v{version}-task-"
        existing_tasks = existing.get("tasks", [])
        existing_count = sum(
            1 for t in existing_tasks
            if t.get("task_id", "").startswith(version_prefix)
        )
        task_id = f"v{version}-task-{existing_count + 1:03d}"
        task_body = {
            "task_id": task_id,
            "agent": agent,
            "agent_version": agent_version,
            "description": description,
            "instructions": instructions or description,
            "dependencies": dependencies or [],
        }

        tasks = list(existing.get("tasks", []))
        tasks.append(task_body)
        plan.task_plan_json = {**existing, "tasks": tasks}
        await self._session.flush()

        task_state = PlanTaskState(
            id=str(uuid.uuid4()),
            mission_plan_id=plan.id,
            task_id=task_id,
            status=PlanTaskStatus.PROPOSED.value,
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
