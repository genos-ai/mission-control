"""
Mission budget API endpoints (Plan 88 step 88.4.1, contracts 3.5.3).

    GET /missions/{id}/budget   caps, spend and breach (mission access)
    PUT /missions/{id}/budget   replace the caps (mission operator)

``breach`` is the lowercase ``MissionPauseReason`` value or null. Updating the
caps never resumes a paused mission.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    require_existing_mission_access,
    require_mission_operator,
)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.budget import BudgetCapsUpdate, BudgetStatus, BudgetStatusResponse
from modules.backend.services.budget import BudgetService

router = APIRouter()


def _envelope(status: BudgetStatus, request_id: str) -> ApiResponse:
    response = BudgetStatusResponse.model_validate(status.model_dump())
    return ApiResponse(
        success=True,
        data=response.model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/budget",
    response_model=ApiResponse,
    summary="Get the mission's budget caps and spend",
)
async def get_budget(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Per-run, per-month and lifetime caps, this month's and lifetime spend, and any breach."""
    await require_existing_mission_access(db, mission_id, current_user)
    status = await BudgetService(db).get_status(mission_id)
    return _envelope(status, request_id)


@router.put(
    "/{mission_id}/budget",
    response_model=ApiResponse,
    summary="Replace the mission's budget caps",
)
async def put_budget(
    mission_id: str,
    data: BudgetCapsUpdate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Validate and write the caps; a null lifetime_usd removes the lifetime cap."""
    await require_mission_operator(db, mission_id, current_user)
    status = await BudgetService(db).update_caps(mission_id, data, current_user.id)
    return _envelope(status, request_id)
