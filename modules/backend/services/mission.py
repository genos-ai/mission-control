"""
Mission Service.

Business logic for mission lifecycle management, membership,
and mission-scoping enforcement.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func, select

from modules.backend.core.logging import get_logger
from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.models.mission import (
    Mission,
    MissionMember,
    MissionMemberRole,
    MissionStatus,
)
from modules.backend.repositories.mission import (
    MissionMemberRepository,
    MissionRepository,
)
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class MissionService(BaseService):
    """Service for mission CRUD, membership, and scoping."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._mission_repo = MissionRepository(session)
        self._member_repo = MissionMemberRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["MissionService", None]:
        """Create a MissionService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield MissionService(db)
            await db.commit()

    async def create_mission(
        self,
        *,
        name: str,
        description: str,
        owner_id: str,
        brief: str | None = None,
        team_id: str | None = None,
        default_roster: str = "default",
        budget_ceiling_usd: float | None = None,
        repo_url: str | None = None,
        repo_root: str | None = None,
        gate_mode: str | None = None,
        tier: str = "user",
    ) -> Mission:
        """Create a new mission with initial owner membership.

        Creates: missions row, mission_members row (owner), seed MCD.
        """
        existing = await self._mission_repo.get_by_name(name)
        if existing:
            raise ConflictError(f"Mission name already exists: {name}")

        mission = await self._mission_repo.create(
            name=name,
            description=description,
            brief=brief,
            owner_id=owner_id,
            team_id=team_id,
            default_roster=default_roster,
            budget_ceiling_usd=budget_ceiling_usd,
            repo_url=repo_url,
            repo_root=repo_root,
            gate_mode=gate_mode,
            tier=tier,
        )

        # Auto-create owner membership
        await self._member_repo.create(
            mission_id=mission.id,
            user_id=owner_id,
            role=MissionMemberRole.OWNER,
        )

        # Create seed MCD
        from modules.backend.services.mission_context import MissionContextManager
        mcd_manager = MissionContextManager(self._session)
        await mcd_manager.create_context(
            mission_id=mission.id,
            mission_name=name,
            description=description,
        )

        self._log_operation(
            "Mission created",
            mission_id=mission.id,
            mission_name=name,
        )
        return mission

    async def get_mission(self, mission_id: str) -> Mission:
        """Get a mission by ID. Raises NotFoundError if not found."""
        return await self._mission_repo.get_by_id(mission_id)

    async def get_mission_by_name(self, name: str) -> Mission | None:
        """Get a mission by name. Returns None if not found."""
        return await self._mission_repo.get_by_name(name)

    async def list_missions(
        self,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Mission]:
        """List missions, optionally filtered by owner and/or status."""
        if owner_id:
            status_enum = MissionStatus(status) if status else None
            return await self._mission_repo.list_by_owner(
                owner_id, status=status_enum, limit=limit,
            )
        return await self._mission_repo.list_active(limit=limit)

    async def update_mission(
        self,
        mission_id: str,
        **updates,
    ) -> Mission:
        """Update mission fields."""
        return await self._mission_repo.update(mission_id, **updates)

    async def set_gate_mode(self, mission_id: str, mode: str) -> Mission:
        """Update the default gate mode for a mission."""
        valid_modes = {"off", "interactive", "ai_assisted", "autonomous"}
        if mode not in valid_modes:
            raise ValueError(f"Invalid gate mode: {mode}. Valid: {', '.join(sorted(valid_modes))}")
        mission = await self.get_mission(mission_id)
        mission.gate_mode = mode
        await self._session.flush()
        self._log_operation("Gate mode updated", mission_id=mission_id, gate_mode=mode)
        return mission

    async def resolve_gate(self, mission_id: str, gate_override: str | None = None):
        """Resolve gate reviewer: explicit override > mission default > off.

        Returns a GateReviewer instance, or None if mode is off.
        """
        mode = gate_override
        if mode is None:
            mission = await self.get_mission(mission_id)
            mode = mission.gate_mode

        if not mode or mode == "off":
            return None

        from modules.backend.agents.mission_control.gate import create_gate
        return create_gate(mode_override=mode)

    async def archive_mission(self, mission_id: str) -> Mission:
        """Archive a mission. No new executions can be created."""
        return await self._mission_repo.update(
            mission_id, status=MissionStatus.ARCHIVED,
        )

    async def unarchive_mission(self, mission_id: str) -> Mission:
        """Restore an archived mission to active status."""
        return await self._mission_repo.update(
            mission_id, status=MissionStatus.ACTIVE,
        )

    async def get_stats(self, mission_id: str) -> dict:
        """Get aggregated stats for a mission.

        Returns team_count, workflow_count, execution_count,
        total_cost_usd, last_run_at, last_run_status.
        """
        from modules.backend.models.execution_record import ExecutionRecord
        from modules.backend.models.mission_team import MissionTeamMember
        from modules.backend.models.workflow_definition import WorkflowDefinition

        await self._mission_repo.get_by_id(mission_id)  # ensure exists

        team_result = await self._session.execute(
            select(func.count()).select_from(MissionTeamMember)
            .where(MissionTeamMember.mission_id == mission_id)
        )
        team_count = team_result.scalar() or 0

        wf_result = await self._session.execute(
            select(func.count()).select_from(WorkflowDefinition)
            .where(WorkflowDefinition.mission_id == mission_id)
        )
        workflow_count = wf_result.scalar() or 0

        exec_result = await self._session.execute(
            select(
                func.count().label("count"),
                func.coalesce(func.sum(ExecutionRecord.total_cost_usd), 0.0).label("cost"),
            ).where(ExecutionRecord.mission_id == mission_id)
        )
        row = exec_result.one()
        execution_count = row.count
        total_cost_usd = float(row.cost)

        last_run_result = await self._session.execute(
            select(ExecutionRecord.created_at, ExecutionRecord.status)
            .where(ExecutionRecord.mission_id == mission_id)
            .order_by(ExecutionRecord.created_at.desc())
            .limit(1)
        )
        last_run = last_run_result.first()

        return {
            "team_count": team_count,
            "workflow_count": workflow_count,
            "execution_count": execution_count,
            "total_cost_usd": total_cost_usd,
            "last_run_at": last_run.created_at.isoformat() if last_run else None,
            "last_run_status": last_run.status if last_run else None,
        }

    # ---- Mission membership (human users) ----

    async def list_members(self, mission_id: str) -> list[MissionMember]:
        """List all human members of a mission."""
        await self._mission_repo.get_by_id(mission_id)  # ensure mission exists
        return await self._member_repo.get_members(mission_id)

    async def add_member(
        self,
        mission_id: str,
        user_id: str,
        role: str = "viewer",
    ) -> MissionMember:
        """Add a human user to a mission."""
        await self._mission_repo.get_by_id(mission_id)

        existing = await self._member_repo.get_membership(mission_id, user_id)
        if existing:
            raise ConflictError("User is already a member of this mission")

        member = await self._member_repo.create(
            mission_id=mission_id,
            user_id=user_id,
            role=MissionMemberRole(role),
        )
        self._log_operation(
            "Member added to mission",
            mission_id=mission_id,
            user_id=user_id,
            role=role,
        )
        return member

    async def update_member_role(
        self,
        mission_id: str,
        user_id: str,
        role: str,
    ) -> MissionMember:
        """Update a mission member's role."""
        member = await self._member_repo.get_membership(mission_id, user_id)
        if not member:
            raise NotFoundError(
                f"User '{user_id}' is not a member of mission '{mission_id}'"
            )

        member = await self._member_repo.update(
            member.id, role=MissionMemberRole(role),
        )
        self._log_operation(
            "Mission member role updated",
            mission_id=mission_id,
            user_id=user_id,
            new_role=role,
        )
        return member

    async def remove_member(
        self,
        mission_id: str,
        user_id: str,
    ) -> None:
        """Remove a human user from a mission."""
        member = await self._member_repo.get_membership(mission_id, user_id)
        if not member:
            raise NotFoundError(
                f"User '{user_id}' is not a member of mission '{mission_id}'"
            )

        await self._member_repo.delete(member.id)
        self._log_operation(
            "Member removed from mission",
            mission_id=mission_id,
            user_id=user_id,
        )
