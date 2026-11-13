"""
Mission Plan Orchestrator — orchestration layer for mission plan dispatch and refinement.

Extracted from mission_plan.py (Plan 38 section 2.1) and converted from a mixin
to a standalone BaseService subclass. Contains refine, apply_plan and their
helper methods.

This is the documented service-agent boundary crossing point: methods here
call into the agents layer (handle_mission, Planning Agent) and use
MissionPlanService for state CRUD.

Plan 84 Phase 5.2: task-materialization internals live in the sibling
mission_plan_taskio.py module. This file keeps the public API (refine,
apply_plan, _persist_plan, _emit). Runs are started by MissionRunService
(Plan 88 step 88.1.7) and their tasks run one activity each in
MissionRunWorkflow (Plan 88 step 88.2.6).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.protocols import EventBusProtocol
from modules.backend.events.types import MissionPlanRefinedEvent, SystemEvent
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.task import TaskRepository
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services import mission_plan_taskio
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
        mission_run_id: str | None,
        mission_budget_usd: float,
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
            mission_run_id: The run whose tasks (plus the backlog) the planner
                sees and reconciliation touches. None means the mission's
                active run, or the backlog only when no run is active.
            mission_budget_usd: Budget to validate the new plan against.
                Required: the run planning path passes the run's headroom,
                Director callers the plan's per-run cap.

        Returns:
            The refreshed MissionPlan with updated tasks and bumped
            version. Task rows are reconciled in the same transaction.

        Raises:
            NotFoundError: If the plan does not exist.
            ValidationError: If the Planning Agent returns an invalid
                TaskPlan (fails plan_validator's 11 rules).
        """
        from modules.backend.agents.mission_control.helpers.agent_executor import (
            _call_planning_agent,
        )
        from modules.backend.agents.mission_control.plan_validator import validate_plan
        from modules.backend.agents.mission_control.roster import derive_roster_from_team

        plan = await self._repo.get_by_id(mission_plan_id)
        mission_run_id = await mission_plan_taskio.resolve_run_scope(
            self, plan.mission_id, mission_run_id
        )

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
        budget = mission_budget_usd

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
                current_plan=mission_plan_taskio.materialize_plan_dict(
                    plan, mission_run_id=mission_run_id
                ),
                task_states=mission_plan_taskio.materialize_task_states(
                    plan, mission_run_id=mission_run_id
                ),
                refinement_instructions=refinement_prompt,
                plan_version=next_version,
                mission_run_id=mission_run_id,
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

        await self._persist_plan(
            plan, new_plan, source="mission_plan_orchestrator", mission_run_id=mission_run_id
        )

        # Refetch with tasks relationship loaded
        return await self._repo.get_by_mission_id_required(plan.mission_id)

    # ── Shared persist helper ────────────────────────────────────────────

    async def _persist_plan(
        self,
        plan: "MissionPlan",
        candidate: TaskPlan,
        *,
        source: str = "mission_plan_orchestrator",
        mission_run_id: str | None,
    ) -> dict[str, int]:
        """Reconcile tasks, persist plan metadata, bump version, emit event.

        Shared by refine() and apply_plan(). Reconciliation is scoped to
        mission_run_id (see mission_plan_taskio.reconcile_tasks). Returns
        reconciliation stats.
        """
        reconcile_stats = await mission_plan_taskio.reconcile_tasks(
            self, plan, candidate, mission_run_id=mission_run_id
        )
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
        mission_budget_usd: float,
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
        budget = mission_budget_usd

        validation = validate_plan(candidate, roster, budget)
        if not validation.is_valid:
            raise ValidationError("TaskPlan validation failed: " + "; ".join(validation.errors))

        reconcile_stats = await self._persist_plan(
            plan,
            candidate,
            source="planning_agent_chat",
            mission_run_id=None,
        )

        return {
            "status": "saved",
            "plan_id": plan.id,
            "version": plan.version,
            "task_count": len(candidate.tasks),
            "reconciliation": reconcile_stats,
        }
