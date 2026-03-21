"""
Mission Service.

Business logic for mission lifecycle management, membership,
and mission-scoping enforcement.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.mission import (
    Mission,
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
    ) -> Mission:
        """Create a new mission with initial owner membership.

        Creates: missions row, mission_members row (owner), seed MCD.
        """
        existing = await self._mission_repo.get_by_name(name)
        if existing:
            from modules.backend.core.exceptions import ConflictError
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

    async def archive_mission(self, mission_id: str) -> Mission:
        """Archive a mission. No new executions can be created."""
        return await self._mission_repo.update(
            mission_id, status=MissionStatus.ARCHIVED,
        )
