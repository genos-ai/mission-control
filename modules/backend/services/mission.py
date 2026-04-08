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

        # Auto-assign default agents based on tier
        await self._auto_assign_agents(mission.id, tier)

        self._log_operation(
            "Mission created",
            mission_id=mission.id,
            mission_name=name,
            tier=tier,
        )
        return mission

    async def _auto_assign_agents(self, mission_id: str, tier: str) -> None:
        """Auto-assign system + mission agents to a new mission.

        All missions get:
            - system.* agents (dispatch infrastructure, read-only visible)
            - mission.* agents (director, workflow architect)

        Platform missions additionally get:
            - platform.director.agent (admin conversational entry point)
        """
        from modules.backend.services.mission_team import MissionTeamService

        team_svc = MissionTeamService(self._session)

        # Collect agents to auto-assign from the registry
        from modules.backend.agents.mission_control.registry import get_registry
        registry = get_registry()

        auto_agents: list[str] = []
        for agent_info in registry.list_system():
            auto_agents.append(agent_info["agent_name"])
        for agent_info in registry.list_all(tier="user"):
            name = agent_info["agent_name"]
            if name.startswith("mission."):
                auto_agents.append(name)

        if tier == "platform":
            auto_agents.append("platform.director.agent")

        assigned = []
        for agent_name in auto_agents:
            try:
                await team_svc.add_agent_by_name(mission_id, agent_name)
                assigned.append(agent_name)
            except Exception as e:
                logger.debug(
                    "Could not auto-assign agent",
                    extra={"agent": agent_name, "error": str(e)},
                )

    async def delete_mission(self, mission_id: str) -> str:
        """Permanently delete a mission and all related data.

        Cascades through all FK dependencies in the correct order.
        Also cleans up any running containers for this mission.

        Returns the mission name for confirmation output.
        """
        from sqlalchemy import text

        mission = await self._mission_repo.get_by_id(mission_id)
        mission_name = mission.name

        # Clean up containers BEFORE deleting DB records
        # (cleanup_for_mission queries execution_environments table)
        try:
            from modules.backend.services.execution_environment import (
                ExecutionEnvironmentService,
            )
            from modules.backend.services.container_backend import ContainerBackend

            env_svc = ExecutionEnvironmentService(db_session=self._session)
            env_svc.register_backend("container", ContainerBackend())
            count = await env_svc.cleanup_for_mission(mission_id)
            if count:
                logger.info(
                    "Cleaned up mission containers",
                    extra={"mission_id": mission_id, "containers_removed": count},
                )
        except Exception:
            # Fallback: direct Docker cleanup by label
            try:
                self._cleanup_mission_containers(mission_id)
            except Exception:
                logger.debug("Container cleanup skipped (non-fatal)", exc_info=True)

        # Clear current_mission_id on any users pointing to this mission
        await self._session.execute(
            text("UPDATE users SET current_mission_id = NULL WHERE current_mission_id = :mid"),
            {"mid": mission_id},
        )

        # Delete in FK order (deepest children first)
        cascade_tables = [
            # Deepest children: task_attempts → task_executions → execution_records
            ("task_attempts", "task_execution_id", "task_executions", "execution_record_id",
             "execution_records", "mission_id"),
            # Children of execution_records
            ("execution_decisions", "execution_record_id", "execution_records", "mission_id"),
            ("task_executions", "execution_record_id", "execution_records", "mission_id"),
            # execution_records themselves
            ("execution_records", "mission_id", None, None),
            # Direct children of missions
            ("executions", "mission_id", None, None),
            ("milestone_summaries", "mission_id", None, None),
            ("mission_contexts", "mission_id", None, None),
            ("mission_decisions", "mission_id", None, None),
            ("mission_members", "mission_id", None, None),
            ("mission_team_members", "mission_id", None, None),
            # Workflow chain
            ("workflow_schedules", "mission_id", None, None),
            ("workflow_runs", "mission_id", None, None),
            ("workflow_definitions", "mission_id", None, None),
            # Execution environments
            ("execution_environments", "mission_id", None, None),
        ]

        for entry in cascade_tables:
            if len(entry) == 6:
                # 3-level deep: table → parent → grandparent → mission
                table, fk_col, parent, parent_fk, grandparent, gp_fk = entry
                await self._session.execute(
                    text(f"DELETE FROM {table} WHERE {fk_col} IN "
                         f"(SELECT id FROM {parent} WHERE {parent_fk} IN "
                         f"(SELECT id FROM {grandparent} WHERE {gp_fk} = :mid))"),
                    {"mid": mission_id},
                )
            elif len(entry) == 4:
                table, fk_col, parent_table, parent_fk = entry
                if parent_table:
                    await self._session.execute(
                        text(f"DELETE FROM {table} WHERE {fk_col} IN "
                             f"(SELECT id FROM {parent_table} WHERE {parent_fk} = :mid)"),
                        {"mid": mission_id},
                    )
                else:
                    await self._session.execute(
                        text(f"DELETE FROM {table} WHERE {fk_col} = :mid"),
                        {"mid": mission_id},
                    )

        # Delete the mission itself
        await self._session.execute(
            text("DELETE FROM missions WHERE id = :mid"),
            {"mid": mission_id},
        )

        await self._session.flush()

        self._log_operation(
            "Mission deleted",
            mission_id=mission_id,
            mission_name=mission_name,
        )
        return mission_name

    @staticmethod
    def _cleanup_mission_containers(mission_id: str) -> None:
        """Remove any Docker containers labeled with this mission ID."""
        try:
            import docker
            client = docker.from_env()
            containers = client.containers.list(
                all=True,
                filters={"label": f"mc-environment={mission_id}"},
            )
            for container in containers:
                container.remove(force=True)
        except ImportError:
            pass
        except Exception:
            pass

    async def get_mission(self, mission_id: str) -> Mission:
        """Get a mission by ID. Raises NotFoundError if not found."""
        return await self._mission_repo.get_by_id(mission_id)

    async def get_mission_by_name(self, name: str) -> Mission | None:
        """Get a mission by name. Returns None if not found."""
        return await self._mission_repo.get_by_name(name)

    async def resolve_mission(self, id_or_name: str) -> Mission:
        """Resolve a mission by ID or name. Raises NotFoundError."""
        mission = await self._mission_repo.get_by_id_or_none(id_or_name)
        if mission is None:
            mission = await self._mission_repo.get_by_name(id_or_name)
        if mission is None:
            raise NotFoundError(f"Mission not found: {id_or_name}")
        return mission

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
