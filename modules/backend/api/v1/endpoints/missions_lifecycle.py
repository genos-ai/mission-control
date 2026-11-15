"""
Mission lifecycle API endpoints (Plan 88 step 88.4.5, contracts 3.2.2 and 3.5.3).

    POST /missions/{id}/pause       ACTIVE to PAUSED (USER); signals the active run (operator)
    POST /missions/{id}/resume      PAUSED to ACTIVE; records the pause's slots as MISSED (operator)
    POST /missions/{id}/archive     ACTIVE or PAUSED to ARCHIVED (owner or admin)
    POST /missions/{id}/unarchive   ARCHIVED to PAUSED (owner or admin)

Mission status changes only through these routes; every handler checks access,
then calls MissionLifecycleService.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    get_event_bus,
    require_mission_operator,
    require_mission_owner,
)
from modules.backend.events.bus import SessionEventBus
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission import MissionPauseReason
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_lifecycle import MissionLifecycleService

EventBus = Annotated[SessionEventBus, Depends(get_event_bus)]

router = APIRouter()


async def _envelope(db: DbSession, mission: object, request_id: str) -> ApiResponse:
    response = (await MissionService(db).to_responses([mission]))[0]
    return ApiResponse(
        success=True,
        data=response.model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.post("/{mission_id}/pause", response_model=ApiResponse, summary="Pause a mission")
async def pause_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Pause the mission; its running run pauses at the next layer boundary."""
    await require_mission_operator(db, mission_id, current_user)
    mission = await MissionLifecycleService(db, event_bus).pause_mission(
        mission_id, reason=MissionPauseReason.USER, user_id=current_user.id
    )
    return await _envelope(db, mission, request_id)


@router.post("/{mission_id}/resume", response_model=ApiResponse, summary="Resume a mission")
async def resume_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Resume the mission; refused while a timed-out gate is undecided or a cap is breached."""
    await require_mission_operator(db, mission_id, current_user)
    mission = await MissionLifecycleService(db, event_bus).resume_mission(
        mission_id, current_user.id
    )
    return await _envelope(db, mission, request_id)


@router.post("/{mission_id}/archive", response_model=ApiResponse, summary="Archive a mission")
async def archive_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Archive the mission's schedules, cancel its active run and its undecided gates."""
    await require_mission_owner(db, mission_id, current_user)
    mission = await MissionLifecycleService(db, event_bus).archive_mission(
        mission_id, current_user.id
    )
    return await _envelope(db, mission, request_id)


@router.post("/{mission_id}/unarchive", response_model=ApiResponse, summary="Unarchive a mission")
async def unarchive_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Restore the mission as PAUSED; its schedules stay archived."""
    await require_mission_owner(db, mission_id, current_user)
    mission = await MissionLifecycleService(db, event_bus).unarchive_mission(
        mission_id, current_user.id
    )
    return await _envelope(db, mission, request_id)
