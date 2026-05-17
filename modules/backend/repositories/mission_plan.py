"""
Mission Plan Repository.

Data access for MissionPlan (Plan 42, updated by Plan 72). Task-state
operations have moved to TaskRepository (Plan 72).
"""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from modules.backend.models.mission_plan import (
    MissionPlan,
    MissionPlanStatus,
)
from modules.backend.repositories.base import BaseRepository


class MissionPlanRepository(BaseRepository[MissionPlan]):
    """Repository for MissionPlan CRUD.

    One plan per mission (enforced at the schema level). `get_by_mission_id`
    is the usual entry point — callers typically know a mission_id, not a
    plan_id.

    Task-state operations moved to TaskRepository (Plan 72).
    """

    model = MissionPlan

    # ── Plan-level queries ───────────────────────────────────────────────

    async def get_by_mission_id(self, mission_id: str) -> MissionPlan | None:
        """Return the plan for a mission, or None if not yet created."""
        result = await self.session.execute(
            select(MissionPlan)
            .where(MissionPlan.mission_id == mission_id)
            .options(selectinload(MissionPlan.tasks))
        )
        return result.scalar_one_or_none()

    async def get_by_mission_id_required(self, mission_id: str) -> MissionPlan:
        """Return the plan for a mission. Raises if it does not exist."""
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
        """
        plan = MissionPlan(
            mission_id=mission_id,
            gate_mode=gate_mode,
            status=MissionPlanStatus.ACTIVE,
            version=1,
            budget_usd_ceiling=budget_usd_ceiling,
            total_spent_usd=0.0,
            veto_window_sec=veto_window_sec,
        )
        self.session.add(plan)
        await self.session.flush()
        await self.session.refresh(plan)
        return plan
