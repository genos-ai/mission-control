"""
Mission Service.

Business logic for mission lifecycle management, membership,
and mission-scoping enforcement.
"""

import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.agent_registry import get_registry
from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole, MissionStatus
from modules.backend.models.mission_event import MissionEvent
from modules.backend.models.mission_plan import VALID_GATE_MODES
from modules.backend.repositories.mission import MissionMemberRepository, MissionRepository
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

        # Seed initial intent from brief (Plan 57 Phase C)
        if brief:
            try:
                from modules.backend.services.mission_intent import MissionIntentService

                intent_svc = MissionIntentService(self._session)
                await intent_svc.create_intent(
                    mission.id,
                    brief,
                    source="system",
                    reason="Initial intent from mission brief",
                )
            except Exception:
                logger.debug("Intent seeding skipped", extra={"mission_id": mission.id})

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

        Cleanup order:
        1. Cancel any running Temporal workflows for this mission
        2. Remove Docker containers
        3. Clear user.current_mission_id references
        4. Delete all DB records in FK order (deepest children first)
        5. Delete the mission itself

        Returns the mission name for confirmation output.
        """
        from sqlalchemy import text

        mission = await self._mission_repo.get_by_id(mission_id)
        mission_name = mission.name

        # Cancel running Temporal workflows for this mission
        try:
            from modules.backend.temporal.client import get_temporal_client

            client = await get_temporal_client()

            # Cancel MissionRunWorkflow if running
            for plan in mission.plans if hasattr(mission, "plans") else []:
                workflow_id = f"mission-run-{plan.id}"
                try:
                    handle = client.get_workflow_handle(workflow_id)
                    await handle.terminate(reason=f"Mission {mission_name} deleted")
                except Exception:
                    logger.debug(
                        "Temporal workflow terminate failed (not running or already completed): %s",
                        workflow_id,
                        exc_info=True,
                    )
        except Exception:
            logger.debug("Temporal cleanup skipped (non-fatal)", exc_info=True)

        # Clean up containers BEFORE deleting DB records
        # (cleanup_for_mission queries execution_environments table)
        try:
            from modules.backend.services.container_backend import ContainerBackend
            from modules.backend.services.execution_environment import ExecutionEnvironmentService

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

        # Delete in FK order (deepest children first).
        # Each tuple: (table_name, fk_column, mission_id_value)
        # For nested FKs, use subqueries to resolve the parent chain.
        mid = mission_id

        # ── Level 3: deepest children (FK → FK → mission_id) ──
        # task_attempts → task_executions → execution_records
        await self._session.execute(
            text(
                "DELETE FROM task_attempts WHERE task_execution_id IN "
                "(SELECT id FROM task_executions WHERE execution_record_id IN "
                "(SELECT id FROM execution_records WHERE mission_id = :mid))"
            ),
            {"mid": mid},
        )
        # session_messages / session_channels → sessions → mission_id
        await self._session.execute(
            text(
                "DELETE FROM session_messages WHERE session_id IN "
                "(SELECT id FROM sessions WHERE mission_id = :mid)"
            ),
            {"mid": mid},
        )
        await self._session.execute(
            text(
                "DELETE FROM session_channels WHERE session_id IN "
                "(SELECT id FROM sessions WHERE mission_id = :mid)"
            ),
            {"mid": mid},
        )

        # ── Level 2: children of mission-scoped parents ──
        # Children of execution_records
        await self._session.execute(
            text(
                "DELETE FROM execution_decisions WHERE execution_record_id IN "
                "(SELECT id FROM execution_records WHERE mission_id = :mid)"
            ),
            {"mid": mid},
        )
        await self._session.execute(
            text(
                "DELETE FROM task_executions WHERE execution_record_id IN "
                "(SELECT id FROM execution_records WHERE mission_id = :mid)"
            ),
            {"mid": mid},
        )
        # Children of mission_plans (tasks, task_dependencies) cascade at
        # the DB level via ondelete=CASCADE when mission_plans rows go.

        # ── Level 1: direct children of missions ──
        direct_tables = [
            "execution_records",
            "mission_plans",
            "mission_artifacts",
            "mission_events",
            "mission_contexts",
            "context_changes",
            "context_milestones",
            "mission_decisions",
            "milestone_summaries",
            "mission_members",
            "mission_team_members",
            "sessions",
            "session_followups",
            "workflow_schedules",
            "workflow_runs",
            "workflow_definitions",
            "execution_environments",
            "llm_calls",
            "mission_intents",
            "mission_learnings",
            "embeddings",
        ]
        for table in direct_tables:
            await self._session.execute(
                text(f"DELETE FROM {table} WHERE mission_id = :mid"),
                {"mid": mid},
            )

        # ── Delete the mission itself ──
        await self._session.execute(
            text("DELETE FROM missions WHERE id = :mid"),
            {"mid": mid},
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
            logger.debug(
                "Docker container cleanup failed for mission %s", mission_id, exc_info=True
            )

    async def is_member(self, mission_id: str, user_id: str) -> bool:
        """Check if a user is a member of a mission."""
        membership = await self._member_repo.get_membership(mission_id, user_id)
        return membership is not None

    async def get_mission(self, mission_id: str) -> Mission:
        """Get a mission by ID. Raises NotFoundError if not found."""
        return await self._mission_repo.get_by_id(mission_id)

    async def get_mission_by_name(self, name: str) -> Mission | None:
        """Get a mission by name. Returns None if not found."""
        return await self._mission_repo.get_by_name(name)

    async def get_narrative_events(
        self,
        mission_id: str,
        *,
        limit: int = 200,
    ) -> list[dict]:
        """Return persisted narrative events for a mission timeline."""
        rows = await self._session.execute(
            select(MissionEvent)
            .where(MissionEvent.mission_id == mission_id)
            .order_by(MissionEvent.timestamp.desc())
            .limit(limit)
        )
        events = []
        for row in reversed(rows.scalars().all()):
            data = row.data
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {}
            events.append(
                {
                    "event_id": str(data.get("event_id") or row.id),
                    "event_type": row.event_type,
                    "category": "execution",
                    "timestamp": row.timestamp,
                    "source": row.source,
                    "data": data,
                }
            )
        return events

    async def resolve_mission(self, id_or_name: str) -> Mission:
        """Resolve a mission by ID or name. Raises NotFoundError."""
        from uuid import UUID as _UUID

        mission = None
        # Only attempt ID lookup if the string is a valid UUID.
        try:
            _UUID(id_or_name)
            mission = await self._mission_repo.get_by_id_or_none(id_or_name)
        except ValueError:
            pass
        if mission is None:
            mission = await self._mission_repo.get_by_name(id_or_name)
        if mission is None:
            raise NotFoundError(f"Mission not found: {id_or_name}")
        return mission

    async def list_missions(
        self,
        owner_id: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[Mission]:
        """List missions, optionally filtered by owner and/or status.

        By default, archived missions are excluded. Pass include_archived=True
        or an explicit status to override this.
        """
        if owner_id:
            status_enum = MissionStatus(status) if status else None
            return await self._mission_repo.list_by_owner(
                owner_id,
                status=status_enum,
                limit=limit,
            )

        missions = await self._mission_repo.list_all(limit=limit)
        if not include_archived and status is None:
            missions = [m for m in missions if m.status != MissionStatus.ARCHIVED]
        return missions

    async def update_mission(
        self,
        mission_id: str,
        **updates,
    ) -> Mission:
        """Update mission fields."""
        return await self._mission_repo.update(mission_id, **updates)

    async def set_gate_mode(self, mission_id: str, mode: str) -> Mission:
        """Update the default gate mode for a mission."""
        if mode not in VALID_GATE_MODES:
            raise ValueError(
                f"Invalid gate mode: {mode}. " f"Valid: {', '.join(sorted(VALID_GATE_MODES))}"
            )
        mission = await self.get_mission(mission_id)
        mission.gate_mode = mode
        await self._session.flush()
        self._log_operation("Gate mode updated", mission_id=mission_id, gate_mode=mode)
        return mission

    async def archive_mission(self, mission_id: str) -> Mission:
        """Archive a mission. No new executions can be created."""
        return await self._mission_repo.update(
            mission_id,
            status=MissionStatus.ARCHIVED,
        )

    async def unarchive_mission(self, mission_id: str) -> Mission:
        """Restore an archived mission to active status."""
        return await self._mission_repo.update(
            mission_id,
            status=MissionStatus.ACTIVE,
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
            select(func.count())
            .select_from(MissionTeamMember)
            .where(MissionTeamMember.mission_id == mission_id)
        )
        team_count = team_result.scalar() or 0

        wf_result = await self._session.execute(
            select(func.count())
            .select_from(WorkflowDefinition)
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
            raise NotFoundError(f"User '{user_id}' is not a member of mission '{mission_id}'")

        member = await self._member_repo.update(
            member.id,
            role=MissionMemberRole(role),
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
            raise NotFoundError(f"User '{user_id}' is not a member of mission '{mission_id}'")

        await self._member_repo.delete(member.id)
        self._log_operation(
            "Member removed from mission",
            mission_id=mission_id,
            user_id=user_id,
        )
