"""
Research Reports API endpoints (Plan 40 §5).

Read-only endpoints for retrieving deep research reports. Reports are
created by the research loop executor, not by the API. Listed and
retrieved by mission ID or individual report ID.
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
from modules.backend.core.exceptions import AuthorizationError, NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.research_report import (
    ResearchReportResponse,
    ResearchReportSummary,
)
from modules.backend.services.mission import MissionService
from modules.backend.services.research_report import ResearchReportService

router = APIRouter()


async def _require_mission_access(db, mission_id: str, current_user) -> None:
    """Admin or mission owner can read research reports."""
    mission = await MissionService(db).get_mission(mission_id)
    if current_user.has_role("admin"):
        return
    if str(mission.owner_id) == str(current_user.id):
        return
    raise AuthorizationError("Not authorized to view this mission's research")


@router.get(
    "/missions/{mission_id}/research/reports",
    response_model=ApiResponse[list[ResearchReportSummary]],
    summary="List research reports for a mission",
)
async def list_reports(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    limit: int = Query(default=20, le=100),
    status: str | None = Query(default=None),
):
    """List research reports for a mission, newest first."""
    await _require_mission_access(db, mission_id, current_user)
    svc = ResearchReportService(db)
    reports = await svc.list_for_mission(mission_id, limit=limit, status=status)
    return ApiResponse(data=[ResearchReportSummary.model_validate(r) for r in reports])


@router.get(
    "/research/reports/{report_id}",
    response_model=ApiResponse[ResearchReportResponse],
    summary="Get a research report by ID",
)
async def get_report(
    report_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
):
    """Get a single research report with full content."""
    svc = ResearchReportService(db)
    report = await svc.get_report(report_id)
    if report is None:
        raise NotFoundError(f"Research report {report_id} not found")
    await _require_mission_access(db, report.mission_id, current_user)
    return ApiResponse(data=ResearchReportResponse.model_validate(report))
