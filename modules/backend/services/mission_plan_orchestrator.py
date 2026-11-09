"""
Mission Plan Orchestrator — orchestration layer for mission plan dispatch and refinement.

Extracted from mission_plan.py (Plan 38 section 2.1) and converted from a mixin
to a standalone BaseService subclass. Contains dispatch_approved,
run_objective, refine, and their helper methods.

This is the documented service-agent boundary crossing point: methods here
call into the agents layer (handle_mission, Planning Agent) and use
MissionPlanService for state CRUD.

Plan 84 Phase 5.2: dispatch, post-run-supervisor, and task-materialization
internals live in the sibling mission_plan_dispatch.py,
mission_plan_supervisor.py, and mission_plan_taskio.py modules. This file
keeps the public API (refine, apply_plan, run_objective, _persist_plan,
_emit) plus thin delegating methods for dispatch_autonomous and
dispatch_approved — external callers (endpoints, Temporal activities)
import these from the orchestrator instance exactly as before.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_default_budget_usd
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.protocols import EventBusProtocol
from modules.backend.events.types import MissionPlanRefinedEvent, SystemEvent
from modules.backend.models.mission_plan import GateMode
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services import mission_plan_dispatch, mission_plan_taskio
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
        event_bus: EventBusProtocol,
    ) -> None:
        super().__init__(session)
        self._event_bus: EventBusProtocol = event_bus
        self._repo = MissionPlanRepository(session)
        self._mission_repo = MissionRepository(session)
        self._task_repo = TaskRepository(session)
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
            # Catch-all justified: this IS the event-emission path (Redis
            # publish can fail many ways) and there is nowhere further to
            # escalate to. best-effort.
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
            The refreshed MissionPlan with updated tasks and bumped
            version. Task rows are reconciled in the same transaction.

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
        from modules.backend.agents.mission_control.roster import derive_roster_from_team

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
            has_current_plan=len(plan.tasks) > 0,
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
                current_plan=mission_plan_taskio.materialize_plan_dict(plan),
                refinement_instructions=refinement_prompt,
                plan_version=next_version,
            )

            # Validate schema
            errors: list[str] = []
            try:
                candidate = TaskPlan.model_validate(planning_result["task_plan"])
            except (PydanticValidationError, KeyError, TypeError) as e:
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
                    instructions,
                    errors,
                )

        if new_plan is None:
            raise ValidationError(
                f"Planning Agent failed after {max_attempts} attempts: " + "; ".join(last_errors)
            )

        await self._persist_plan(plan, new_plan, source="mission_plan_orchestrator")

        # Refetch with tasks relationship loaded
        return await self._repo.get_by_mission_id_required(plan.mission_id)

    # ── Shared persist helper ────────────────────────────────────────────

    async def _persist_plan(
        self,
        plan: "MissionPlan",
        candidate: TaskPlan,
        *,
        source: str = "mission_plan_orchestrator",
    ) -> dict[str, int]:
        """Reconcile tasks, persist plan metadata, bump version, emit event.

        Shared by refine() and apply_plan(). Returns reconciliation stats.
        """
        reconcile_stats = await mission_plan_taskio.reconcile_tasks(self, plan, candidate)
        # Update plan-level metadata (Plan 72 — no more task_plan_json)
        plan.summary = candidate.summary or ""
        plan.estimated_cost_usd = candidate.estimated_cost_usd or 0.0
        plan.estimated_duration = candidate.estimated_duration_seconds or 0
        plan.execution_hints_json = (
            candidate.execution_hints.model_dump() if candidate.execution_hints else {}
        )
        plan.version += 1
        await self._session.flush()

        self._log_operation(
            "MissionPlan persisted",
            plan_id=plan.id,
            new_version=plan.version,
            new_task_count=len(candidate.tasks),
            source=source,
        )

        await self._emit(
            plan.mission_id,
            MissionPlanRefinedEvent(
                session_id=uuid.uuid4(),
                source=source,
                mission_id=plan.mission_id,
                plan_id=plan.id,
                version=plan.version,
                task_count=len(candidate.tasks),
                cancelled_count=reconcile_stats["cancelled"],
                new_count=reconcile_stats["new"],
            ),
        )
        return reconcile_stats

    # ── Direct plan application (chat mode) ─────────────────────────────

    async def apply_plan(
        self,
        mission_id: str,
        plan_dict: dict,
        user_id: str,
        *,
        mission_budget_usd: float | None = None,
    ) -> dict:
        """Validate and persist a pre-computed TaskPlan without calling the Planning Agent.

        Used by the Planning Agent's chat-mode `save_plan` tool. The agent
        itself produces the plan JSON in conversation; this method validates
        it and applies it to the mission plan, the same way refine() does
        but without the recursive _call_planning_agent() call.

        Returns a dict with plan_id, version, task_count, and reconciliation stats.

        Raises:
            ValidationError: If the plan fails schema or semantic validation.
        """
        mission_budget_usd = mission_budget_usd or get_default_budget_usd()

        from modules.backend.agents.mission_control.plan_validator import validate_plan
        from modules.backend.agents.mission_control.roster import derive_roster_from_team

        # Schema validation
        try:
            candidate = TaskPlan.model_validate(plan_dict)
        except PydanticValidationError as e:
            raise ValidationError(f"TaskPlan schema validation failed: {e}") from e

        # Semantic validation (11 rules)
        roster = await derive_roster_from_team(mission_id, self._session)
        plan = await self._plan_svc.get_or_create_plan(mission_id)
        budget = plan.budget_usd_ceiling or mission_budget_usd

        validation = validate_plan(candidate, roster, budget)
        if not validation.is_valid:
            raise ValidationError("TaskPlan validation failed: " + "; ".join(validation.errors))

        reconcile_stats = await self._persist_plan(
            plan,
            candidate,
            source="planning_agent_chat",
        )

        return {
            "status": "saved",
            "plan_id": plan.id,
            "version": plan.version,
            "task_count": len(candidate.tasks),
            "reconciliation": reconcile_stats,
        }

    # ── Unified execution entry point (Plan 62) ────────────────────────

    async def run_objective(
        self,
        mission_id: str,
        objective: str,
        user_id: str,
        *,
        session_id: str | None = None,
        gate_mode: GateMode | None = None,
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
        if gate_mode is not None:
            try:
                plan.gate_mode = GateMode(gate_mode)
            except ValueError as exc:
                raise ValidationError(
                    f"Invalid gate_mode {gate_mode!r}. "
                    f"Must be one of: {[m.value for m in GateMode]}"
                ) from exc
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

        task_count = len(plan.tasks)

        # 5. Auto-approve (gate mode permitting)
        if plan.gate_mode != GateMode.AUTONOMOUS:
            self._log_operation(
                "run_objective: non-autonomous gate, stopping after refine",
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
        workflow_id = await mission_plan_dispatch.start_temporal_run_workflow(
            self,
            plan,
            session_id,
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
            "message": (
                f"Dispatched {len(approved_ids)} tasks via Temporal workflow "
                f"{workflow_id}. The agents are working now — you will be "
                f"notified when execution completes. Tell the user their "
                f"request is being executed and they can watch progress in "
                f"the Plan tab."
            ),
        }

    # ── Dispatch (delegates to mission_plan_dispatch.py) ────────────────

    async def dispatch_autonomous(
        self,
        mission_plan_id: str,
        session_id: str | None = None,
    ) -> dict:
        """Start a Temporal MissionRunWorkflow for autonomous multi-wave execution.

        Implementation lives in mission_plan_dispatch.py (Plan 84 Phase
        5.2) — kept as a method here so external callers (the
        missions_plan endpoint) keep the same call surface.
        """
        return await mission_plan_dispatch.dispatch_autonomous(self, mission_plan_id, session_id)

    async def dispatch_approved(
        self,
        mission_plan_id: str,
        user_id: str,
        *,
        temporal_workflow_id: str,
        session_id: str | None = None,
        skip_post_run_supervisor: bool = False,
    ) -> dict:
        """Dispatch all currently-approved tasks as a single run.

        Implementation lives in mission_plan_dispatch.py (Plan 84 Phase
        5.2) — kept as a method here so external callers (Temporal's
        execute_mission activity) keep the same call surface.
        """
        return await mission_plan_dispatch.dispatch_approved(
            self,
            mission_plan_id,
            user_id,
            temporal_workflow_id=temporal_workflow_id,
            session_id=session_id,
            skip_post_run_supervisor=skip_post_run_supervisor,
        )
