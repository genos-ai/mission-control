"""
Mission Plan Orchestrator — orchestration layer for mission plan dispatch and refinement.

Extracted from mission_plan.py (Plan 38 section 2.1) and converted from a mixin
to a standalone BaseService subclass. Contains dispatch_approved,
run_objective, refine, and their helper methods.

This is the documented service-agent boundary crossing point: methods here
call into the agents layer (handle_mission, Planning Agent) and use
MissionPlanService for state CRUD.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_default_budget_usd
from modules.backend.core.exceptions import ConflictError, ValidationError
from modules.backend.core.protocols import EventBusProtocol, NoOpEventBus
from modules.backend.core.utils import utc_now
from modules.backend.events.types import (
    MissionPlanDispatchedEvent,
    MissionPlanRefinedEvent,
    MissionPlanRunCompletedEvent,
    SupervisorDecisionEmittedEvent,
    SystemEvent,
)
from modules.backend.models.mission_plan import (
    VALID_GATE_MODES,
    MissionPlanStatus,
    PlanTaskStatus,
)
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.schemas.execution_outcome import TaskStatus
from modules.backend.schemas.gate import GateAction, GateContext
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services.base import BaseService

if TYPE_CHECKING:
    from modules.backend.models.mission_plan import MissionPlan


class MissionPlanOrchestrator(BaseService):
    """Orchestration layer for mission plan dispatch and refinement.

    Calls into the agents layer (handle_mission, planning agent) and
    uses MissionPlanService for state CRUD. This is the documented
    service-agent boundary crossing point.
    """

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBusProtocol | None = None,
    ) -> None:
        super().__init__(session)
        self._event_bus: EventBusProtocol = event_bus or NoOpEventBus()
        self._repo = MissionPlanRepository(session)
        self._mission_repo = MissionRepository(session)
        # Lazy import to avoid circular dependency within services
        from modules.backend.services.mission_plan import MissionPlanService
        self._plan_svc = MissionPlanService(session, event_bus=event_bus)

    # ── Event emission helper ──────────────────────────────────────────

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

    # ── Refinement (Planning Agent delegation) ──────────────────────────

    async def refine(
        self,
        mission_plan_id: str,
        instructions: str,
        user_id: str,
        *,
        mission_budget_usd: float | None = None,
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
                Defaults to get_default_budget_usd() when None — callers
                that have a per-plan budget ceiling should pass it in
                explicitly.

        Returns:
            The refreshed MissionPlan with the new task_plan_json and
            bumped version. Task states are updated in-place in the same
            transaction.

        Raises:
            NotFoundError: If the plan does not exist.
            ValidationError: If the Planning Agent returns an invalid
                TaskPlan (fails plan_validator's 11 rules).
        """
        mission_budget_usd = mission_budget_usd or get_default_budget_usd()

        from modules.backend.agents.mission_control.helpers.agent_executor import (
            _call_planning_agent,
        )
        from modules.backend.agents.mission_control.plan_validator import validate_plan
        from modules.backend.agents.mission_control.roster import (
            derive_roster_from_team,
        )

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
        budget = plan.budget_usd_ceiling or mission_budget_usd

        # Retry loop: if the Planning Agent produces invalid output,
        # feed the validation errors back and re-call. Max 3 attempts.
        from modules.backend.agents.mission_control.helpers.prompt_builder import (
            _append_validation_feedback,
        )

        max_attempts = 3
        last_errors: list[str] = []
        new_plan: TaskPlan | None = None
        refinement_prompt = instructions

        for attempt in range(1, max_attempts + 1):
            planning_result = await _call_planning_agent(
                prompt=brief,
                roster=roster,
                upstream_context=None,
                event_bus=self._event_bus,
                mission_id=plan.mission_id,
                current_plan=plan.task_plan_json,
                refinement_instructions=refinement_prompt,
                plan_version=next_version,
            )

            # Validate schema
            errors: list[str] = []
            try:
                candidate = TaskPlan.model_validate(planning_result["task_plan"])
            except Exception as e:
                errors.append(f"Schema validation failed: {e}")
                candidate = None

            # Validate semantics (only if schema passed)
            if candidate is not None:
                validation = validate_plan(candidate, roster, budget)
                if not validation.is_valid:
                    errors.extend(validation.errors)

            if not errors and candidate is not None:
                new_plan = candidate
                break

            last_errors = errors
            self._log_operation(
                "Planning Agent produced invalid plan, retrying",
                plan_id=mission_plan_id,
                attempt=attempt,
                error_count=len(errors),
                errors=errors[:5],
            )

            if attempt < max_attempts:
                # Notify console so the user knows why there's a second
                # thinking animation — without this the UX is confusing.
                await self._emit(
                    plan.mission_id,
                    SystemEvent(
                        session_id=uuid.uuid4(),
                        source="mission_plan_orchestrator",
                        level="warning",
                        message=(
                            f"Plan validation failed ({len(errors)} error(s)), "
                            f"retrying (attempt {attempt + 1}/{max_attempts})..."
                        ),
                        mission_id=plan.mission_id,
                    ),
                )

                # Append errors to the refinement instructions so the
                # planner can self-correct on the next attempt.
                refinement_prompt = _append_validation_feedback(
                    instructions, errors,
                )

        if new_plan is None:
            raise ValidationError(
                f"Planning Agent failed after {max_attempts} attempts: "
                + "; ".join(last_errors)
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
                source="mission_plan_orchestrator",
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
        from modules.backend.models.mission_plan import TERMINAL_PLAN_TASK_STATUSES

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
                if state.status == PlanTaskStatus.CANCELLED:
                    state.status = PlanTaskStatus.PROPOSED
                    reset_count += 1
                continue
            # Task disappeared from the new plan
            status_enum = PlanTaskStatus[state.status]
            if status_enum in TERMINAL_PLAN_TASK_STATUSES:
                continue  # already terminal, leave as-is
            if status_enum == PlanTaskStatus.FAILED:
                continue  # preserve failed rows for audit
            state.status = PlanTaskStatus.CANCELLED
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
    ) -> dict:
        """Create/refine a plan from an objective and dispatch via Temporal.

        Unified entry point for all execution — CLI, chat, frontend.
        Single-task objectives produce single-task plans. Complex objectives
        produce multi-task plans. Both go through the full plan infrastructure
        (task states, supervisor, budget tracking, audit trail).

        Always starts a Temporal MissionRunWorkflow for dispatch and
        returns immediately. Returns outcome_status="temporal_unavailable"
        if Temporal is not reachable.

        Args:
            mission_id: The mission to execute against.
            objective: Natural-language objective for the Planning Agent.
            user_id: The user requesting execution.
            session_id: Session for event publishing (optional).
            gate_mode: Override the plan's gate mode (optional).
            budget_ceiling_usd: Override the plan's budget (optional).

        Returns:
            dict with: plan_id, plan_version, task_count, outcome_status,
            dispatched_task_ids, workflow_id.

        Raises:
            ConflictError: If the plan has tasks in QUEUED or RUNNING state.
            ValidationError: If the Planning Agent returns an invalid plan.
            NotFoundError: If the mission does not exist.
        """
        # 1. Get or create the plan
        plan = await self._plan_svc.get_or_create_plan(mission_id)

        # 2. Apply overrides
        if gate_mode is not None and gate_mode in VALID_GATE_MODES:
            plan.gate_mode = gate_mode
        if budget_ceiling_usd is not None:
            plan.budget_usd_ceiling = budget_ceiling_usd
        await self._session.flush()

        # 3. Concurrency guard — reject if tasks are in-flight
        await self._plan_svc.check_no_active_tasks(plan.id)

        # 4. Refine: Planning Agent decomposes objective into TaskPlan
        budget = plan.budget_usd_ceiling or get_default_budget_usd()
        plan = await self.refine(
            plan.id,
            objective,
            user_id,
            mission_budget_usd=budget,
        )

        task_plan = self._plan_svc._get_task_plan_or_raise(plan)
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

        approved_ids = await self._plan_svc.approve_all_proposed(plan.id, user_id)

        if not approved_ids:
            return {
                "plan_id": plan.id,
                "plan_version": plan.version,
                "task_count": task_count,
                "outcome_status": "no_tasks_to_approve",
                "dispatched_task_ids": [],
                "total_cost_usd": 0.0,
            }

        # 6. Dispatch via Temporal
        workflow_id = await self._start_temporal_run_workflow(
            plan, session_id,
        )
        self._log_operation(
            "run_objective: Temporal workflow started",
            plan_id=plan.id,
            mission_id=mission_id,
            approved_task_ids=approved_ids,
            workflow_id=workflow_id,
        )
        return {
            "plan_id": plan.id,
            "plan_version": plan.version,
            "task_count": task_count,
            "outcome_status": "dispatching",
            "dispatched_task_ids": approved_ids,
            "total_cost_usd": 0.0,
            "workflow_id": workflow_id,
        }

    async def dispatch_autonomous(
        self,
        mission_plan_id: str,
        session_id: str | None = None,
    ) -> dict:
        """Start a Temporal MissionRunWorkflow for autonomous multi-wave execution.

        Returns a dict compatible with DispatchApprovedResponse. Raises if
        Temporal is unavailable — callers should let it propagate.

        The workflow handles the full supervisor loop: execute → evaluate →
        advance/refine/escalate → repeat until done or circuit-breaker trips.
        """
        plan = await self._repo.get_by_id(mission_plan_id)
        workflow_id = await self._start_temporal_run_workflow(
            plan, session_id,
        )

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
    ) -> str:
        """Start a MissionRunWorkflow via Temporal. Returns the workflow_id.

        Raises if Temporal is unavailable — callers should let it propagate.
        """
        from modules.backend.core.config import get_app_config
        from modules.backend.temporal.client import get_temporal_client
        from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
        from modules.backend.temporal.models import MissionWorkflowInput

        client = await get_temporal_client()
        config = get_app_config()

        mission = await MissionRepository(self._session).get_by_id(plan.mission_id)
        brief = mission.brief or mission.description or mission.name
        remaining_budget = (plan.budget_usd_ceiling or get_default_budget_usd()) - plan.total_spent_usd

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

    # ── Dispatch ───────────────────────────────────────────────────────

    async def dispatch_approved(
        self,
        mission_plan_id: str,
        user_id: str,
        *,
        session_id: str | None = None,
        skip_post_run_supervisor: bool = False,
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

        plan = await self._repo.get_by_id(mission_plan_id)
        task_plan = self._plan_svc._get_task_plan_or_raise(plan)

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
        # Dependencies that completed in prior runs are treated as satisfied.
        derived_plan = await self._derive_subset_task_plan(
            task_plan, approved_task_ids, mission_plan_id,
        )

        # Mark approved → running and commit immediately so the kanban
        # board shows the task in the "Running" column during execution.
        # We skip "queued" because handle_mission starts immediately —
        # there's no queue delay in the synchronous dispatch path.
        now = utc_now()
        for state in approved_states:
            state.status = PlanTaskStatus.RUNNING
            state.last_attempt_at = now
        await self._session.commit()

        # Fetch mission for brief + session service
        mission = await MissionRepository(self._session).get_by_id(plan.mission_id)
        brief = mission.brief or mission.description or mission.name

        # Create an early execution record so the run is visible in the
        # "runs" tab and the background-task badge while it executes.
        # persist_mission_results will UPDATE this record on completion.
        task_type = self._infer_task_type(derived_plan)
        early_record = await self._create_early_execution_record(
            plan=plan,
            mission=mission,
            session_id=session_id,
            task_type=task_type,
            approved_task_ids=approved_task_ids,
        )
        early_record_id = early_record.id if early_record else None

        self._log_operation(
            "MissionPlan dispatching",
            plan_id=mission_plan_id,
            user_id=user_id,
            task_count=len(approved_task_ids),
            task_ids=sorted(approved_task_ids),
            gate_mode=plan.gate_mode,
            execution_record_id=early_record_id,
        )

        # Build the gate reviewer from the plan's gate_mode (Plan 42 §10.4)
        gate_reviewer = None
        if plan.gate_mode and plan.gate_mode != "off":
            from modules.backend.agents.mission_control.gate import create_gate
            gate_reviewer = create_gate(mode_override=plan.gate_mode)

        # Load outputs from prior waves so downstream tasks can resolve
        # from_upstream references to tasks that completed in earlier
        # dispatch_approved calls.
        prior_outputs = await self._load_prior_outputs(mission_plan_id)

        # Dispatch via the Phase 0 precomputed_plan path
        budget = plan.budget_usd_ceiling or get_default_budget_usd()
        if plan.budget_usd_ceiling is not None:
            budget = plan.budget_usd_ceiling - plan.total_spent_usd

        from modules.backend.services.session import SessionService
        outcome = await handle_mission(
            mission_run_id=mission_plan_id,
            mission_brief=brief,
            session_service=SessionService(self._session),  # type: ignore[arg-type]
            event_bus=self._event_bus,
            roster_name=mission.default_roster,
            mission_budget_usd=budget,
            session_id=session_id,
            mission_id=plan.mission_id,
            db_session=self._session,
            gate=gate_reviewer,
            execution_mode=mission.execution_environment or "local",
            precomputed_plan=derived_plan,
            mission_repo_root=mission.repo_root,
            prior_outputs=prior_outputs,
            execution_record_id=early_record_id,
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
                source="mission_plan_orchestrator",
                mission_id=plan.mission_id,
                plan_id=plan.id,
                execution_record_id=outcome.execution_record_id,
                dispatched_task_ids=sorted(approved_task_ids),
            ),
        )

        # When called from Temporal's execute_mission activity, skip the
        # inline supervisor — the MissionRunWorkflow handles the supervisor
        # loop, Director notifications, and plan status changes. Running
        # both causes double-evaluation and the inline one steals decisions.
        if not skip_post_run_supervisor:
            await self._session.refresh(plan, ["status"])
            if plan.status != MissionPlanStatus.ACTIVE:
                self._log_operation(
                    "Skipping post-run supervisor — plan no longer active",
                    plan_id=mission_plan_id,
                    plan_status=plan.status,
                )
            else:
                await self._post_run_supervisor(
                    plan, outcome, session_id=session_id,
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
            # Full serialized outcome for Temporal's persist_mission_outcome
            # activity (MissionRunWorkflow Step 2). handle_mission already
            # persists inside dispatch_approved, but the workflow also
            # persists independently for durability.
            "outcome_json": outcome.model_dump(mode="json"),
        }

    # ── Post-run supervisor ────────────────────────────────────────────

    async def _post_run_supervisor(
        self,
        plan: MissionPlan,
        outcome,
        *,
        session_id: str | None,
    ) -> None:
        """Run post-run supervisor evaluation and emit events.

        Computes denormalised task counts, persists them on the
        execution_records row, emits the run-completed event, and
        fires any matching session followups in-process.
        """
        _task_results = getattr(outcome, "task_results", []) or []
        _completed = sum(1 for r in _task_results if r.status == TaskStatus.SUCCESS)
        _failed = sum(1 for r in _task_results if r.status == TaskStatus.FAILED)

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
            source="mission_plan_orchestrator",
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

        # Plan 52: inline supervisor for non-Temporal dispatch paths
        try:
            from modules.backend.agents.mission_control.gate_post_run import AutonomousPostRunReviewer
            from modules.backend.agents.adapters.supervisor_introspection import get_recent_run_outcomes

            recent = await get_recent_run_outcomes(self._session, mission_id=plan.mission_id, limit=5)
            task_states_now = await self._plan_svc.get_task_states(plan.id)
            summary = {
                "approved": sum(1 for s in task_states_now if s.status == PlanTaskStatus.APPROVED),
                "proposed": sum(1 for s in task_states_now if s.status == PlanTaskStatus.PROPOSED),
                "running": sum(1 for s in task_states_now if s.status == PlanTaskStatus.RUNNING),
                "completed": sum(1 for s in task_states_now if s.status in (PlanTaskStatus.COMPLETED,)),
                "failed": sum(1 for s in task_states_now if s.status == PlanTaskStatus.FAILED),
                "total_completed": sum(r.get("completed_task_count", 0) for r in recent),
                "execution_record_id": outcome.execution_record_id,
                "max_supervisor_iterations": plan.max_supervisor_iterations,
            }
            mission_obj = await self._mission_repo.get_by_id(plan.mission_id)
            context = GateContext(
                gate_type="post_run", mission_id=plan.mission_id,
                total_cost_usd=plan.total_spent_usd,
                budget_usd=plan.budget_usd_ceiling or 0.0,
                recent_run_outcomes=recent, plan_task_summary=summary,
                mission_brief=mission_obj.brief or mission_obj.description or "",
                supervisor_iteration_count=plan.supervisor_iteration_count,
            )
            reviewer = AutonomousPostRunReviewer(session=self._session, gate_mode=plan.gate_mode)
            decision = await reviewer.review(context)
            plan.supervisor_iteration_count += 1
            await self._apply_supervisor_decision(
                plan, decision, outcome, session_id=session_id,
            )
            await self._session.flush()
            # Emit decision event
            _decision_event = SupervisorDecisionEmittedEvent(
                session_id=uuid.UUID(session_id) if session_id else uuid.uuid4(),
                source="mission_plan_orchestrator", mission_id=plan.mission_id,
                plan_id=plan.id, execution_record_id=outcome.execution_record_id or "",
                action=decision.action.value, reason=(decision.reason or "")[:500],
                reviewer=decision.reviewer,
            )
            await self._emit(plan.mission_id, _decision_event)
            self._log_operation("Post-run supervisor", plan_id=plan.id, action=decision.action.value)

            # Fire matching session followups so the Director wakes up
            # and posts a proactive chat update (Plan 51 Phase E).
            await self._fire_followups(
                plan, _run_completed_event, _decision_event,
            )
        except Exception:
            self._logger.warning("Post-run supervisor evaluation failed", exc_info=True)

    async def _fire_followups(
        self,
        plan: MissionPlan,
        run_event,
        decision_event,
    ) -> None:
        """Fire matching session followups for both supervisor events.

        Creates a lightweight agent_turn_runner adapter that starts a
        Director chat turn via handle_mission. Followup failures are
        swallowed by SessionFollowupService — they never block the
        dispatch path.
        """
        from modules.backend.services.session_followup import (
            SessionFollowupService,
        )

        followup_svc = SessionFollowupService(
            self._session, event_bus=self._event_bus,
        )

        async def _agent_turn_runner(
            session_id: str, mission_id: str, prompt: str,
        ) -> None:
            """Adapter: start a Director chat turn for the followup."""
            from modules.backend.agents.mission_control.mission_control import (
                handle_mission,
            )
            from modules.backend.services.session import SessionService

            await handle_mission(
                mission_run_id=plan.id,
                mission_brief=prompt,
                session_service=SessionService(self._session),  # type: ignore[arg-type]
                event_bus=self._event_bus,
                session_id=session_id,
                mission_id=mission_id,
                db_session=self._session,
            )

        # Fire for both events — followups may subscribe to either
        # "mission_plan.run.completed" or "mission_plan.supervisor_decision".
        for event in (run_event, decision_event):
            try:
                await followup_svc.fire_matching(
                    event, agent_turn_runner=_agent_turn_runner,
                )
            except Exception:
                self._logger.warning(
                    "Failed to fire followups for event",
                    extra={
                        "event_type": getattr(event, "event_type", "unknown"),
                        "plan_id": plan.id,
                    },
                    exc_info=True,
                )

    async def _apply_supervisor_decision(
        self,
        plan: MissionPlan,
        decision,
        outcome,
        *,
        session_id: str | None,
    ) -> None:
        """Route the supervisor's gate decision (inline path).

        Used when dispatch_approved is called directly (e.g. the UI Run
        button). The Temporal MissionRunWorkflow has its own decision
        routing. ADVANCE_APPROVED and ADVANCE_REFINE prepare state for
        the next dispatch cycle without looping.
        """
        from modules.backend.models.mission_plan import (
            PlanTaskStatus as _PTS,
        )

        action = decision.action

        # Safety: re-read plan status before mutating. If the plan was
        # paused or completed while the supervisor was evaluating, refuse
        # to advance — only PROPOSE_COMPLETE and ESCALATE (which pause
        # the plan themselves) are safe to apply regardless.
        await self._session.refresh(plan, ["status"])
        _plan_active = plan.status == MissionPlanStatus.ACTIVE

        if action in (GateAction.WAIT, GateAction.ADVANCE_APPROVED, GateAction.ADVANCE_REFINE):
            if not _plan_active:
                self._log_operation(
                    f"Supervisor: {action.value} suppressed — plan is {plan.status}",
                    plan_id=plan.id,
                )
                return

        if action == GateAction.WAIT:
            # Approved tasks still pending — next dispatch cycle picks them up.
            self._log_operation(
                "Supervisor: WAIT", plan_id=plan.id,
                reason="Approved tasks remain; next dispatch picks them up",
            )

        elif action == GateAction.ADVANCE_APPROVED:
            # Flip all proposed → approved for the next dispatch cycle.
            for ts in await self._plan_svc.get_task_states(plan.id, status=_PTS.PROPOSED):
                await self._plan_svc.approve_task(
                    plan.id, ts.task_id, "mission.supervisor.agent",
                )
            self._log_operation(
                "Supervisor: ADVANCE_APPROVED", plan_id=plan.id,
            )

        elif action == GateAction.ADVANCE_REFINE:
            # Ask the Planning Agent to generate the next wave of tasks,
            # then approve the new proposed tasks for dispatch.
            _run_status = (
                outcome.status.value
                if hasattr(outcome.status, "value")
                else str(outcome.status)
            )
            instructions = (
                f"The last wave {_run_status}. "
                f"Total cost so far: ${plan.total_spent_usd:.2f}. "
                f"Generate the next wave of tasks based on outcomes."
            )
            try:
                await self.refine(
                    plan.id, instructions, "mission.supervisor.agent",
                    mission_budget_usd=(
                        plan.budget_usd_ceiling - plan.total_spent_usd
                        if plan.budget_usd_ceiling is not None
                        else 10.0
                    ),
                )
                # Auto-approve newly proposed tasks so daemon dispatches them.
                for ts in await self._plan_svc.get_task_states(plan.id, status=_PTS.PROPOSED):
                    await self._plan_svc.approve_task(
                        plan.id, ts.task_id, "mission.supervisor.agent",
                    )
            except Exception:
                self._logger.warning(
                    "Supervisor ADVANCE_REFINE: refinement failed, "
                    "pausing plan for human review",
                    exc_info=True,
                )
                plan.status = MissionPlanStatus.PAUSED
            self._log_operation(
                "Supervisor: ADVANCE_REFINE", plan_id=plan.id,
            )

        elif action == GateAction.PROPOSE_COMPLETE:
            # Plan stays active — an idle plan with zero approved tasks
            # costs nothing. The Director followup asks the user to
            # confirm completion; the user archives when ready.
            self._log_operation(
                "Supervisor: PROPOSE_COMPLETE — notifying user",
                plan_id=plan.id,
                reason=(decision.reason or "")[:200],
            )

        elif action == GateAction.ESCALATE:
            # Pause and escalate — human attention required.
            plan.status = MissionPlanStatus.PAUSED
            self._log_operation(
                "Supervisor: ESCALATE — plan paused for human review",
                plan_id=plan.id,
                reason=(decision.reason or "")[:200],
            )

        else:
            # Unknown action — safe default: do nothing, log.
            self._logger.warning(
                "Supervisor returned unknown action",
                extra={"action": str(action), "plan_id": plan.id},
            )

    # ── Dispatch helpers ───────────────────────────────────────────────

    async def _load_prior_outputs(
        self,
        mission_plan_id: str,
    ) -> dict[str, dict]:
        """Load output_reference dicts from tasks completed in prior waves.

        Reads plan_task_states where status is completed/skipped and
        result_summary is not null. result_summary contains the JSON-
        serialized output_reference stored by _write_back_task_results.

        Returns a {task_id: output_dict} mapping that seeds the dispatch
        loop's completed_outputs so from_upstream references resolve.
        """
        completed_states = await self._repo.get_task_states(
            mission_plan_id, status=PlanTaskStatus.COMPLETED,
        )
        prior: dict[str, dict] = {}
        for state in completed_states:
            if not state.result_summary:
                continue
            try:
                prior[state.task_id] = json.loads(state.result_summary)
            except (TypeError, ValueError, json.JSONDecodeError):
                # result_summary might be plain text from older runs
                prior[state.task_id] = {"result": state.result_summary}
        return prior

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
            state.status = new_status
            state.execution_record_id = outcome.execution_record_id
            # Look up the actual task_executions.id PK
            state.task_execution_id = await self._resolve_task_execution_id(
                outcome.execution_record_id, task_id,
            )
            state.last_attempt_at = utc_now()

            # Denormalized metrics (Plan 46 Phase 2 #2)
            state.cost_usd = float(task_result.cost_usd or 0.0)
            state.duration_seconds = float(task_result.duration_seconds or 0.0)

            if new_status == PlanTaskStatus.FAILED:
                state.failure_reason = getattr(
                    task_result, "failure_reason", None,
                ) or "Task failed during dispatch"
                state.retry_count += 1
            else:
                # Persist the agent's output so downstream tasks in
                # later waves can access it via from_upstream inputs.
                output = task_result.output_reference
                if output:
                    try:
                        state.result_summary = json.dumps(output, default=str)
                    except (TypeError, ValueError):
                        state.result_summary = str(output)
                state.failure_reason = None

            updated_ids.append(task_id)

        # Tasks dispatched but never reported: mark failed
        for task_id in dispatched_task_ids - seen_task_ids:
            state = await self._repo.get_task_state(plan.id, task_id)
            if state is None or state.status not in (PlanTaskStatus.QUEUED, PlanTaskStatus.RUNNING):
                continue
            state.status = PlanTaskStatus.FAILED
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
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return row

    async def _derive_subset_task_plan(
        self,
        full_plan: TaskPlan,
        approved_task_ids: set[str],
        mission_plan_id: str,
    ) -> TaskPlan:
        """Filter a full TaskPlan to only the approved tasks.

        Dependencies that already completed or were skipped in a prior
        run are considered satisfied — they don't need to be in the
        approved subset because they already ran.
        """
        filtered_tasks = [
            t for t in full_plan.tasks if t.task_id in approved_task_ids
        ]

        # Build the set of task_ids whose dependencies are already
        # satisfied (completed, skipped — they ran in a prior wave).
        all_states = await self._repo.get_task_states(mission_plan_id)
        satisfied_ids = {
            s.task_id for s in all_states
            if s.status in (PlanTaskStatus.COMPLETED, PlanTaskStatus.SKIPPED)
        }

        # The "safe" set is: tasks being dispatched now + already done.
        safe_ids = approved_task_ids | satisfied_ids

        # Validate closure: every dependency must be safe
        for task in filtered_tasks:
            for dep_id in task.dependencies:
                if dep_id not in safe_ids:
                    raise ValidationError(
                        f"Task {task.task_id!r} depends on {dep_id!r}, "
                        f"which is neither approved nor completed. "
                        f"Approve the dependency first."
                    )

        # Filter execution_hints.critical_path to only tasks in this subset —
        # the plan validator rejects references to tasks not in the plan.
        hints = full_plan.execution_hints
        if hints and hasattr(hints, "critical_path") and hints.critical_path:
            filtered_ids = {t.task_id for t in filtered_tasks}
            hints = hints.model_copy(update={
                "critical_path": [
                    tid for tid in hints.critical_path if tid in filtered_ids
                ],
            })

        return TaskPlan(
            version=full_plan.version,
            mission_id=full_plan.mission_id,
            summary=full_plan.summary,
            estimated_cost_usd=full_plan.estimated_cost_usd,
            estimated_duration_seconds=full_plan.estimated_duration_seconds,
            tasks=filtered_tasks,
            execution_hints=hints,
        )

    @staticmethod
    def _infer_task_type(plan: TaskPlan) -> str:
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

    async def _create_early_execution_record(
        self,
        plan,
        mission,
        *,
        session_id: str | None,
        task_type: str,
        approved_task_ids: set[str],
    ):
        """Insert a 'running' ExecutionRecord before dispatch starts.

        Makes the run visible in the Runs tab and background-task badge
        while execution is in progress.  persist_mission_results will
        UPDATE this record with final results on completion.
        """
        from modules.backend.models.execution_record import (
            ExecutionRecord,
            ExecutionRecordStatus,
        )

        try:
            record = ExecutionRecord(
                session_id=session_id,
                status=ExecutionRecordStatus.RUNNING,
                mission_id=plan.mission_id,
                roster_name=mission.default_roster,
                objective_statement=(
                    mission.brief or mission.description or mission.name
                ),
                task_type=task_type,
                task_params={
                    "plan_id": plan.id,
                    "task_ids": sorted(approved_task_ids),
                },
                started_at=utc_now(),
            )
            self._session.add(record)
            await self._session.commit()
            return record
        except Exception:
            await self._session.rollback()
            self._logger.warning(
                "Failed to create early execution record (non-fatal)",
                exc_info=True,
            )
            return None
