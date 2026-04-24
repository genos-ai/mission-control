"""
Research Report Repository (Plan 40 §5).

Data access for ResearchReport. Thin repository — business logic
lives in ResearchReportService.
"""

from sqlalchemy import select

from modules.backend.models.research_report import ResearchReport
from modules.backend.repositories.base import BaseRepository


class ResearchReportRepository(BaseRepository[ResearchReport]):
    """Repository for ResearchReport CRUD."""

    model = ResearchReport

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        limit: int = 20,
        status: str | None = None,
    ) -> list[ResearchReport]:
        """Return reports for a mission, newest first."""
        query = (
            select(ResearchReport)
            .where(ResearchReport.mission_id == mission_id)
            .order_by(ResearchReport.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            query = query.where(ResearchReport.status == status)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_execution(
        self, execution_id: str
    ) -> ResearchReport | None:
        """Get a report by its execution ID."""
        result = await self.session.execute(
            select(ResearchReport)
            .where(ResearchReport.execution_id == execution_id)
        )
        return result.scalar_one_or_none()
