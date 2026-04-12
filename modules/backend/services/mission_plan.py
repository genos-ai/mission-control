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
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.agents.mission_control.models import (
    EventBusProtocol,
    NoOpEventBus,
)
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.events.types import (
    MissionPlanDispatchedEvent,
    MissionPlanGateModeChangedEvent,
    MissionPlanRefinedEvent,
    MissionPlanRunCompletedEvent,
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

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBusProtocol | None = None,
    ) -> None:
        super().__init__(session)
        self._repo = MissionPlanRepository(session)
        self._mission_repo = MissionRepository(session)
        self._event_bus: EventBusProtocol = event_bus or NoOpEventBus()

    # ── Plan 51 Phase C: no-op agent turn runner ──────────────────────
    # In Phase C, fire_matching runs but no agent actually wakes — the
    # real runner gets plugged in by Phase E (Director followup). This
    # no-op logs the fire so the audit trail is visible even before
    # the Director consumer is wired.

    @staticmethod
    async def _noop_agent_turn_runner(
        session_id: str, mission_id: str, prompt: str,
    ) -> None:
        """Placeholder agent turn runner — logs and returns."""
        from modules.backend.core.logging import get_logger as _gl
        _gl(__name__).info(
            "Post-run followup fired (no agent runner wired yet — Phase E)",
            extra={
                "session_id": session_id,
                "mission_id": mission_id,
                "prompt_preview": prompt[:200],
            },
        )

    # ── Plan 51 Phase E: post-run reviewer + Director followup ────────

    async def _run_post_run_reviewer(
        self,
        *,
        plan: "MissionPlan",
        outcome: Any,
        session_id: str | None,
        completed_count: int,
        failed_count: int,
    ) -> None:
        """Invoke the AutonomousPostRunReviewer and emit the decision event.

        Called by dispatch_approved after the run-completed event. The
        reviewer evaluates the decision matrix (§4.2), writes an audit
        row, and returns a GateDecision. This method then:
        1. Increments supervisor_iteration_count on the plan
        2. Emits SupervisorDecisionEmittedEvent
        3. Calls fire_matching for Director followups
        4. Applies the decision (advance / wait / escalate)
        """
        from modules.backend.agents.mission_control.gate_models import (
            GateAction,
            GateContext,
        )
        from modules.backend.agents.mission_control.gate_post_run import (
            AutonomousPostRunReviewer,
        )
        from modules.backend.agents.tools.supervisor_introspection import (
            get_recent_run_outcomes,
        )
        from modules.backend.events.types import SupervisorDecisionEmittedEvent

        # Build the GateContext for the reviewer.
        recent = await get_recent_run_outcomes(
            self._session, mission_id=plan.mission_id, limit=5,
        )
        task_states = await self.get_task_states(plan.id)
        summary = {
            "approved": sum(1 for s in task_states if s.status == "approved"),
            "proposed": sum(1 for s in task_states if s.status == "proposed"),
            "running": sum(1 for s in task_states if s.status == "running"),
            "completed": sum(1 for s in task_states if s.status in ("completed", "done")),
            "failed": sum(1 for s in task_states if s.status == "failed"),
            "total_completed": sum(
                r.get("completed_task_count", 0) for r in recent
            ),
            "execution_record_id": outcome.execution_record_id,
            "max_supervisor_iterations": plan.max_supervisor_iterations,
        }

        # Fetch mission brief for Haiku prompt (branch #8).
        mission = await self._mission_repo.get_by_id(plan.mission_id)
        mission_brief = mission.brief or mission.description or ""

        context = GateContext(
            gate_type="post_run",
            mission_id=plan.mission_id,
            total_cost_usd=plan.total_spent_usd,
            budget_usd=plan.budget_usd_ceiling or 0.0,
            recent_run_outcomes=recent,
            plan_task_summary=summary,
            mission_brief=mission_brief,
            supervisor_iteration_count=plan.supervisor_iteration_count,
        )

        # Invoke the reviewer.
        reviewer = AutonomousPostRunReviewer(
            session=self._session,
            gate_mode=plan.gate_mode,
        )
        decision = await reviewer.review(context)

        # Increment iteration counter (idempotency check in the
        # reviewer prevents double-increment on retries).
        plan.supervisor_iteration_count += 1
        await self._session.flush()

        # Emit the supervisor decision event.
        _decision_event = SupervisorDecisionEmittedEvent(
            session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
            source="mission_plan_service",
            mission_id=plan.mission_id,
            plan_id=plan.id,
            execution_record_id=outcome.execution_record_id or "",
            action=decision.action.value,
            reason=(decision.reason or "")[:500],
            reviewer=decision.reviewer,
        )
        await self._emit(plan.mission_id, _decision_event)

        # Fire Director followups on the supervisor decision event.
        try:
            from modules.backend.services.session_followup import (
                SessionFollowupService,
            )
            _followup_svc = SessionFollowupService(
                self._session, event_bus=self._event_bus,
            )
            await _followup_svc.fire_matching(
                _decision_event,
                agent_turn_runner=self._create_agent_turn_runner(),
            )
        except Exception:
            self._logger.warning(
                "fire_matching(supervisor_decision) failed",
                extra={"mission_id": plan.mission_id},
                exc_info=True,
            )

        # Apply the decision.
        await self._apply_supervisor_decision(plan, decision)

        self._log_operation(
            "Post-run reviewer complete",
            plan_id=plan.id,
            action=decision.action.value,
            reviewer=decision.reviewer,
            supervisor_iteration=plan.supervisor_iteration_count,
        )

    async def _apply_supervisor_decision(
        self,
        plan: "MissionPlan",
        decision: Any,
    ) -> None:
        """Apply a supervisor GateDecision to the plan state.

        ADVANCE_APPROVED: flip proposed → approved so daemon picks
        them up. ADVANCE_REFINE / PROPOSE_COMPLETE / ESCALATE: no
        plan state change here — the Director handles these via its
        followup (it calls refine_plan or asks the user). WAIT: no-op.
        """
        from modules.backend.agents.mission_control.gate_models import GateAction
        from modules.backend.models.mission_plan import PlanTaskStatus

        if decision.action == GateAction.ADVANCE_APPROVED:
            # Approve all proposed tasks.
            task_states = await self.get_task_states(
                plan.id, status=PlanTaskStatus.PROPOSED,
            )
            for ts in task_states:
                await self.approve_task(
                    plan.id,
                    ts.task_id,
                    approved_by="mission.supervisor.agent",
                    reason="Auto-advanced by supervisor (rule-based)",
                )
        # WAIT, ADVANCE_REFINE, PROPOSE_COMPLETE, ESCALATE — no
        # plan state change. The Director's followup handles these.

    def _create_agent_turn_runner(self):
        """Create a real agent_turn_runner that spawns a Director turn.

        Returns an async callable with signature
        ``(session_id, mission_id, prompt) -> None`` that calls
        ``mission_control.handle()`` to spawn a fresh Director turn
        in the given session. The turn's events flow through the
        event bus and messages are persisted by handle() itself.

        Uses a fresh db session so the Director's turn doesn't
        conflict with the dispatch_approved transaction.
        """
        event_bus = self._event_bus

        async def _run_turn(session_id: str, mission_id: str, prompt: str) -> None:
            from modules.backend.agents.mission_control.mission_control import handle
            from modules.backend.core.database import get_async_session
            from modules.backend.services.session import SessionService

            async with get_async_session() as db:
                svc = SessionService(db)
                async for _event in handle(
                    session_id,
                    prompt,
                    mission_id=mission_id,
                    session_service=svc,
                    event_bus=event_bus,
                    channel="followup",
                    sender_id="session_followup_service",
                ):
                    pass  # Events are published by handle() internally.
                await db.commit()

        return _run_turn

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

        planning_result = await _call_planning_agent(
            prompt=brief,
            roster=roster,
            upstream_context=None,
            mission_id=plan.mission_id,
            current_plan=plan.task_plan_json,
            refinement_instructions=instructions,
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

        # Cancel non-terminal rows whose task disappeared
        for state in existing_states:
            if state.task_id in new_task_ids:
                continue  # survived
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
            total_after=len(new_task_ids),
        )
        return {"cancelled": cancelled_count, "new": new_count}

    # ── Dispatch (Phase 1.6) ────────────────────────────────────────────

    async def dispatch_approved(
        self,
        mission_plan_id: str,
        user_id: str,
        *,
        session_id: str | None = None,
    ) -> dict:
        """Dispatch all currently-approved tasks as a single run.

        Plan 42 §10.1 + §10.5: filters the plan's task_plan_json to the
        approved subset, validates that the subset is a closed DAG
        (should always be true because approve_task transitively
        approves dependencies), and hands the derived TaskPlan to the
        existing dispatch pipeline via handle_mission(precomputed_plan=).

        After the run completes, reads outcome.task_results to update
        each dispatched task_state row with its execution_record_id,
        task_execution_id, completion status, and result summary.
        plan.total_spent_usd is incremented by the run cost.

        Plan 42 §10.7 cumulative budget check: before dispatch, rejects
        if total_spent_usd >= budget_usd_ceiling (when set).

        Returns a dict with:
            outcome_status: "success" | "partial" | "failed"
            execution_record_id: the linked ExecutionRecord row (or None)
            dispatched_task_ids: list of task_ids that were sent to dispatch
            updated_task_ids: list of task_ids whose state was written back
            total_cost_usd: cost of this individual run
            new_total_spent_usd: cumulative total after the run

        Raises:
            ValidationError: If no tasks are approved, the plan is empty,
                the budget is exhausted, or the derived plan fails
                validation.
        """
        from modules.backend.agents.mission_control.mission_control import (
            handle_mission,
        )
        from modules.backend.agents.mission_control.outcome import TaskStatus
        from modules.backend.repositories.mission import MissionRepository

        plan = await self._repo.get_by_id(mission_plan_id)
        task_plan = self._get_task_plan_or_raise(plan)

        # Budget check (Plan 42 §10.7)
        if plan.budget_usd_ceiling is not None:
            remaining = plan.budget_usd_ceiling - plan.total_spent_usd
            if remaining <= 0:
                raise ValidationError(
                    f"Plan budget exhausted: spent "
                    f"${plan.total_spent_usd:.4f} of "
                    f"${plan.budget_usd_ceiling:.4f} ceiling. "
                    f"Increase budget_usd_ceiling to continue."
                )

        # Collect approved task ids
        approved_states = await self._repo.get_task_states(
            mission_plan_id, status=PlanTaskStatus.APPROVED,
        )
        if not approved_states:
            raise ValidationError(
                "No tasks are approved for dispatch. Approve tasks via "
                "the Plan tab before running."
            )
        approved_task_ids = {s.task_id for s in approved_states}

        # Derive the filtered TaskPlan. Approval is transitive (§10.2) so
        # the closure guarantee should hold — but verify and raise if not.
        derived_plan = self._derive_subset_task_plan(task_plan, approved_task_ids)

        # Mark approved → queued (Plan 42 §2.3 state machine)
        now = utc_now()
        for state in approved_states:
            state.status = PlanTaskStatus.QUEUED.value
            state.last_attempt_at = now
        await self._session.flush()

        self._log_operation(
            "MissionPlan dispatching",
            plan_id=mission_plan_id,
            user_id=user_id,
            task_count=len(approved_task_ids),
            task_ids=sorted(approved_task_ids),
            gate_mode=plan.gate_mode,
        )

        # Build the gate reviewer from the plan's gate_mode (Plan 42 §10.4)
        gate_reviewer = None
        if plan.gate_mode and plan.gate_mode != "off":
            from modules.backend.agents.mission_control.gate import create_gate
            gate_reviewer = create_gate(mode_override=plan.gate_mode)

        # Fetch mission for brief + session service
        mission = await MissionRepository(self._session).get_by_id(plan.mission_id)
        brief = mission.brief or mission.description or mission.name

        # Dispatch via the Phase 0 precomputed_plan path
        budget = plan.budget_usd_ceiling or 10.0
        if plan.budget_usd_ceiling is not None:
            budget = plan.budget_usd_ceiling - plan.total_spent_usd

        from modules.backend.services.session import SessionService
        outcome = await handle_mission(
            mission_run_id=mission_plan_id,
            mission_brief=brief,
            session_service=SessionService(self._session),  # type: ignore[arg-type]
            roster_name=mission.default_roster,
            mission_budget_usd=budget,
            session_id=session_id,
            mission_id=plan.mission_id,
            db_session=self._session,
            gate=gate_reviewer,
            execution_mode=mission.execution_environment or "local",
            precomputed_plan=derived_plan,
            mission_repo_root=mission.repo_root,
        )

        # Write back task states from outcome (Plan 42 §10.5 batch write-back)
        updated_ids = await self._write_back_task_results(
            plan,
            outcome,
            dispatched_task_ids=approved_task_ids,
        )

        # Update cumulative cost (Plan 42 §10.7)
        plan.total_spent_usd += float(outcome.total_cost_usd or 0.0)
        await self._session.flush()

        self._log_operation(
            "MissionPlan dispatched",
            plan_id=mission_plan_id,
            outcome_status=outcome.status.value if hasattr(outcome.status, 'value') else str(outcome.status),
            execution_record_id=outcome.execution_record_id,
            run_cost_usd=outcome.total_cost_usd,
            total_spent_usd=plan.total_spent_usd,
        )

        await self._emit(
            plan.mission_id,
            MissionPlanDispatchedEvent(
                session_id=uuid.uuid4(),
                source="mission_plan_service",
                mission_id=plan.mission_id,
                plan_id=plan.id,
                execution_record_id=outcome.execution_record_id,
                dispatched_task_ids=sorted(approved_task_ids),
            ),
        )

        # ── Plan 51 Phase C: post-run event + followup fire ─────────
        # Compute denormalised task counts from the outcome, persist
        # them on the execution_records row, emit the run-completed
        # event, and fire any matching session followups in-process.
        from modules.backend.agents.mission_control.outcome import TaskStatus as _TS

        _task_results = getattr(outcome, "task_results", []) or []
        _completed = sum(1 for r in _task_results if r.status == _TS.SUCCESS)
        _failed = sum(1 for r in _task_results if r.status == _TS.FAILED)

        # Persist denormalised counts on the execution_records row.
        if outcome.execution_record_id:
            try:
                from modules.backend.repositories.execution_record import (
                    ExecutionRecordRepository,
                )
                _exec_repo = ExecutionRecordRepository(self._session)
                _exec_row = await _exec_repo.get_by_id_or_none(
                    outcome.execution_record_id,
                )
                if _exec_row is not None:
                    _exec_row.completed_task_count = _completed
                    _exec_row.failed_task_count = _failed
                    await self._session.flush()
            except Exception:
                self._logger.warning(
                    "Failed to persist task counts on execution_record",
                    extra={"execution_record_id": outcome.execution_record_id},
                    exc_info=True,
                )

        _run_status = (
            outcome.status.value
            if hasattr(outcome.status, "value")
            else str(outcome.status)
        )

        _run_completed_event = MissionPlanRunCompletedEvent(
            session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
            source="mission_plan_service",
            mission_id=plan.mission_id,
            plan_id=plan.id,
            execution_record_id=outcome.execution_record_id or "",
            run_status=_run_status,
            run_cost_usd=float(outcome.total_cost_usd or 0.0),
            completed_task_count=_completed,
            failed_task_count=_failed,
            total_spent_usd=plan.total_spent_usd,
        )
        await self._emit(plan.mission_id, _run_completed_event)

        # Fire matching session followups for run.completed in-process.
        # (Currently no production consumer subscribes to this event
        # via followups — the supervisor is called directly below.
        # This call is here for future consumers and test harnesses.)
        try:
            from modules.backend.services.session_followup import (
                SessionFollowupService,
            )
            _followup_svc = SessionFollowupService(
                self._session, event_bus=self._event_bus,
            )
            await _followup_svc.fire_matching(
                _run_completed_event,
                agent_turn_runner=self._noop_agent_turn_runner,
            )
        except Exception:
            self._logger.warning(
                "fire_matching(run.completed) failed",
                extra={"mission_id": plan.mission_id},
                exc_info=True,
            )

        # ── Plan 51 Phase E: invoke the post-run reviewer + fire
        # Director followups on the supervisor decision. This is the
        # autonomy loop's core feedback path: reviewer decides →
        # emits supervisor_decision event → Director's followup
        # fires → Director posts a chat update to the user.
        try:
            await self._run_post_run_reviewer(
                plan=plan,
                outcome=outcome,
                session_id=session_id,
                completed_count=_completed,
                failed_count=_failed,
            )
        except Exception:
            self._logger.warning(
                "Post-run reviewer failed",
                extra={"mission_id": plan.mission_id},
                exc_info=True,
            )

        return {
            "outcome_status": (
                outcome.status.value
                if hasattr(outcome.status, "value")
                else str(outcome.status)
            ),
            "execution_record_id": outcome.execution_record_id,
            "dispatched_task_ids": sorted(approved_task_ids),
            "updated_task_ids": updated_ids,
            "total_cost_usd": float(outcome.total_cost_usd or 0.0),
            "new_total_spent_usd": plan.total_spent_usd,
        }

    async def _write_back_task_results(
        self,
        plan: MissionPlan,
        outcome,  # ExecutionOutcome
        *,
        dispatched_task_ids: set[str],
    ) -> list[str]:
        """Persist per-task outcomes back to plan_task_states.

        For each task_result in the outcome, update the matching
        plan_task_state row with status, execution linkage, result
        summary, and failure reason. Tasks that were dispatched but
        did not appear in outcome.task_results are marked FAILED
        (a dispatcher bug or a mid-run abort).

        Plan 42 §10.5 batch write-back — no modification to the
        dispatch loop or persistence_bridge.
        """
        from modules.backend.agents.mission_control.outcome import TaskStatus

        status_map = {
            TaskStatus.SUCCESS: PlanTaskStatus.COMPLETED,
            TaskStatus.FAILED: PlanTaskStatus.FAILED,
            TaskStatus.TIMEOUT: PlanTaskStatus.FAILED,
            TaskStatus.SKIPPED: PlanTaskStatus.SKIPPED,
        }

        seen_task_ids: set[str] = set()
        updated_ids: list[str] = []

        for task_result in outcome.task_results:
            task_id = task_result.task_id
            seen_task_ids.add(task_id)

            state = await self._repo.get_task_state(plan.id, task_id)
            if state is None:
                continue  # task not in plan state (shouldn't happen)

            new_status = status_map.get(
                task_result.status, PlanTaskStatus.FAILED,
            )
            state.status = new_status.value
            state.execution_record_id = outcome.execution_record_id
            # Look up the actual task_executions.id (the auto-UUID PK)
            # by matching on execution_record_id + task_id. We cannot
            # use TaskResult.execution_id because that's the dispatch-
            # loop UUID stored in task_executions.execution_id (a
            # separate column), not task_executions.id (the PK that
            # plan_task_states.task_execution_id FK references).
            state.task_execution_id = await self._resolve_task_execution_id(
                outcome.execution_record_id, task_id,
            )
            state.last_attempt_at = utc_now()

            # Denormalized metrics (Plan 46 Phase 2 #2). Both fields
            # are always present on TaskResult (default 0.0), so we
            # write unconditionally rather than guarding with getattr
            # on a per-task basis.
            state.cost_usd = float(task_result.cost_usd or 0.0)
            state.duration_seconds = float(task_result.duration_seconds or 0.0)

            if new_status == PlanTaskStatus.FAILED:
                state.failure_reason = getattr(
                    task_result, "failure_reason", None,
                ) or "Task failed during dispatch"
                state.retry_count += 1
            else:
                state.result_summary = getattr(
                    task_result, "result_summary", None,
                )
                state.failure_reason = None

            updated_ids.append(task_id)

        # Tasks that were dispatched but never reported a result row: mark
        # failed so they do not get stuck in `queued` state.
        for task_id in dispatched_task_ids - seen_task_ids:
            state = await self._repo.get_task_state(plan.id, task_id)
            if state is None or state.status != PlanTaskStatus.QUEUED.value:
                continue
            state.status = PlanTaskStatus.FAILED.value
            state.failure_reason = (
                "Task was dispatched but did not report a result. "
                "This usually indicates a mid-run abort or dispatcher bug."
            )
            state.retry_count += 1
            updated_ids.append(task_id)

        await self._session.flush()
        return updated_ids

    async def _resolve_task_execution_id(
        self,
        execution_record_id: str | None,
        task_id: str,
    ) -> str | None:
        """Look up the task_executions.id PK for a given run + task.

        Returns None if the execution_record is missing or the task
        wasn't persisted (e.g. skipped). Used by _write_back_task_results
        to set plan_task_states.task_execution_id correctly — the FK
        references task_executions.id (auto-UUID), NOT
        task_executions.execution_id (dispatch-loop UUID).
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
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return row

    def _derive_subset_task_plan(
        self,
        full_plan: TaskPlan,
        approved_task_ids: set[str],
    ) -> TaskPlan:
        """Filter a full TaskPlan to only the approved tasks.

        Raises ValidationError if the subset has dangling dependency
        references — this should be impossible because approve_task
        transitively closes the dependency set, but it's cheap to check
        and the error message points to the exact inconsistency.
        """
        filtered_tasks = [
            t for t in full_plan.tasks if t.task_id in approved_task_ids
        ]

        # Validate closure: every dependency must also be in the subset
        for task in filtered_tasks:
            for dep_id in task.dependencies:
                if dep_id not in approved_task_ids:
                    raise ValidationError(
                        f"Task {task.task_id!r} depends on {dep_id!r}, "
                        f"which is not in the approved subset. Approve the "
                        f"dependency first (approve_task is supposed to "
                        f"handle this automatically)."
                    )

        return TaskPlan(
            version=full_plan.version,
            mission_id=full_plan.mission_id,
            summary=full_plan.summary,
            estimated_cost_usd=full_plan.estimated_cost_usd,
            estimated_duration_seconds=full_plan.estimated_duration_seconds,
            tasks=filtered_tasks,
            execution_hints=full_plan.execution_hints,
        )

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

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task_body = {
            "task_id": task_id,
            "agent": agent,
            "agent_version": "latest",
            "description": description,
            "instructions": instructions or description,
            "dependencies": dependencies or [],
        }

        existing: dict = plan.task_plan_json or {}
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
