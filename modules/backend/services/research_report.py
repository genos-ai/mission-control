"""
Research Report Service (Plan 40 §5).

Persistence and retrieval for deep research reports. Called by the
research loop executor (Phase 6: Persist) and by the API endpoints.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.models.research_report import ResearchReport
from modules.backend.repositories.research_report import ResearchReportRepository

logger = get_logger(__name__)


class ResearchReportService:
    """Service for research report CRUD."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ResearchReportRepository(session)

    async def create_report(
        self,
        *,
        mission_id: str,
        query: str,
        report_markdown: str,
        report_structured: dict | None = None,
        sources: list | None = None,
        metadata_json: dict | None = None,
        execution_id: str | None = None,
        status: str = "draft",
        tags: list | None = None,
        citation_count: int = 0,
        verification_score: float | None = None,
    ) -> ResearchReport:
        """Create and persist a new research report."""
        report = ResearchReport(
            mission_id=mission_id,
            execution_id=execution_id,
            query=query,
            report_markdown=report_markdown,
            report_structured=report_structured or {},
            sources=sources or [],
            metadata_json=metadata_json or {},
            status=status,
            tags=tags or [],
            citation_count=citation_count,
            verification_score=verification_score,
        )
        self._session.add(report)
        await self._session.flush()
        await self._session.refresh(report)

        logger.info(
            "Research report created",
            extra={
                "report_id": report.id,
                "mission_id": mission_id,
                "query": query[:80],
                "status": status,
            },
        )
        return report

    async def get_report(self, report_id: str) -> ResearchReport | None:
        """Get a single report by ID."""
        return await self._repo.get_by_id_or_none(report_id)

    async def get_by_execution(self, execution_id: str) -> ResearchReport | None:
        """Get a report by its execution ID."""
        return await self._repo.get_by_execution(execution_id)

    async def list_for_mission(
        self,
        mission_id: str,
        *,
        limit: int = 20,
        status: str | None = None,
    ) -> list[ResearchReport]:
        """List reports for a mission, newest first."""
        return await self._repo.list_for_mission(
            mission_id, limit=limit, status=status,
        )

    async def update_status(
        self, report_id: str, status: str
    ) -> ResearchReport:
        """Update report status (draft → verified → published)."""
        report = await self._repo.get_by_id(report_id)
        report.status = status
        await self._session.flush()
        await self._session.refresh(report)
        return report
