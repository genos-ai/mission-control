"""
Mission Plan Repository.

Data access for MissionPlan and PlanTaskState (Plan 42). Handles the
one-per-mission constraint, task-state upsert by string task_id, and
grouped-by-status queries that back the Plan tab.

The repository is intentionally thin — business logic (dependency closure
on approval, clean-slate refinement, gate mode validation) lives in
MissionPlanService.
"""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from modules.backend.models.mission_plan import (
    MissionPlan,
    MissionPlanStatus,
    PlanTaskState,
    PlanTaskStatus,
)
from modules.backend.repositories.base import BaseRepository


class MissionPlanRepository(BaseRepository[MissionPlan]):
    """Repository for MissionPlan CRUD + task-state management.

    One plan per mission (enforced at the schema level). `get_by_mission_id`
    is the usual entry point — callers typically know a mission_id, not a
    plan_id.
    """

    model = MissionPlan

    # ── Plan-level queries ───────────────────────────────────────────────

    async def get_by_mission_id(self, mission_id: str) -> MissionPlan | None:
        """Return the plan for a mission, or None if not yet created."""
        result = await self.session.execute(
            select(MissionPlan)
            .where(MissionPlan.mission_id == mission_id)
            .options(selectinload(MissionPlan.task_states))
        )
        return result.scalar_one_or_none()

    async def get_by_mission_id_required(self, mission_id: str) -> MissionPlan:
        """Return the plan for a mission. Raises if it does not exist.

        Callers that want lazy initialization should use
        MissionPlanService.get_or_create_plan instead.
        """
        plan = await self.get_by_mission_id(mission_id)
        if plan is None:
            from modules.backend.core.exceptions import NotFoundError
            raise NotFoundError(
                f"MissionPlan not found for mission {mission_id}"
            )
        return plan

    async def create_for_mission(
        self,
        mission_id: str,
        *,
        gate_mode: str | None = None,
        budget_usd_ceiling: float | None = None,
        veto_window_sec: int | None = None,
    ) -> MissionPlan:
        """Create a new empty plan for a mission.

        The unique constraint on mission_id will raise IntegrityError if a
        plan already exists — callers must check first or handle the error.
        Use MissionPlanService.get_or_create_plan for the safe path.
        """
        plan = MissionPlan(
            mission_id=mission_id,
            task_plan_json=None,
            gate_mode=gate_mode,
            status=MissionPlanStatus.ACTIVE.value,
            version=1,
            budget_usd_ceiling=budget_usd_ceiling,
            total_spent_usd=0.0,
            veto_window_sec=veto_window_sec,
        )
        self.session.add(plan)
        await self.session.flush()
        await self.session.refresh(plan)
        return plan

    # ── Task-state queries ──────────────────────────────────────────────

    async def get_task_states(
        self,
        mission_plan_id: str,
        *,
        status: PlanTaskStatus | None = None,
    ) -> list[PlanTaskState]:
        """Return all task-state rows for a plan, optionally filtered.

        Ordered by created_at for stable listing.
        """
        query = select(PlanTaskState).where(
            PlanTaskState.mission_plan_id == mission_plan_id
        )
        if status is not None:
            query = query.where(PlanTaskState.status == status.value)
        query = query.order_by(PlanTaskState.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_task_state(
        self,
        mission_plan_id: str,
        task_id: str,
    ) -> PlanTaskState | None:
        """Look up a single task-state row by (plan_id, task_id)."""
        result = await self.session.execute(
            select(PlanTaskState).where(
                PlanTaskState.mission_plan_id == mission_plan_id,
                PlanTaskState.task_id == task_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_task_state_required(
        self,
        mission_plan_id: str,
        task_id: str,
    ) -> PlanTaskState:
        """Like get_task_state but raises NotFoundError if missing."""
        state = await self.get_task_state(mission_plan_id, task_id)
        if state is None:
            from modules.backend.core.exceptions import NotFoundError
            raise NotFoundError(
                f"PlanTaskState not found for plan {mission_plan_id} "
                f"task {task_id!r}"
            )
        return state

    async def create_task_state(
        self,
        mission_plan_id: str,
        task_id: str,
        *,
        status: PlanTaskStatus = PlanTaskStatus.PROPOSED,
    ) -> PlanTaskState:
        """Create a new task-state row. Caller must ensure uniqueness."""
        state = PlanTaskState(
            mission_plan_id=mission_plan_id,
            task_id=task_id,
            status=status.value,
        )
        self.session.add(state)
        await self.session.flush()
        await self.session.refresh(state)
        return state

    async def delete_task_states(self, mission_plan_id: str) -> None:
        """Delete all task-state rows for a plan.

        Used by clean-slate refinement when the TaskPlan is replaced and
        cross-reference by task_id can't be guaranteed. Terminal-state rows
        that link to completed runs should be archived rather than deleted —
        the service layer handles that policy; this is the raw operation.
        """
        states = await self.get_task_states(mission_plan_id)
        for state in states:
            await self.session.delete(state)
        await self.session.flush()
