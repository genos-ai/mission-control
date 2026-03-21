"""
Workflow Definition Repository.

Data access for DB-stored workflow definitions.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.workflow_definition import WorkflowDefinition
from modules.backend.repositories.base import BaseRepository


class WorkflowDefinitionRepository(BaseRepository[WorkflowDefinition]):
    """Repository for workflow_definitions table."""

    model = WorkflowDefinition

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_mission(
        self,
        mission_id: str,
        enabled_only: bool = True,
    ) -> list[WorkflowDefinition]:
        """List workflow definitions for a mission."""
        stmt = (
            select(WorkflowDefinition)
            .where(WorkflowDefinition.mission_id == mission_id)
            .order_by(WorkflowDefinition.name)
        )
        if enabled_only:
            stmt = stmt.where(WorkflowDefinition.enabled.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_mission_and_name(
        self,
        mission_id: str,
        name: str,
    ) -> WorkflowDefinition | None:
        """Get a workflow by mission + name (unique pair)."""
        result = await self.session.execute(
            select(WorkflowDefinition)
            .where(
                WorkflowDefinition.mission_id == mission_id,
                WorkflowDefinition.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def list_templates(self) -> list[WorkflowDefinition]:
        """List system templates (mission_id IS NULL)."""
        result = await self.session.execute(
            select(WorkflowDefinition)
            .where(WorkflowDefinition.mission_id.is_(None))
            .order_by(WorkflowDefinition.name)
        )
        return list(result.scalars().all())
