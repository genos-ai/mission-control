"""
Mission schedule API endpoints (Plan 88 step 88.1.12, contract 3.5.3).

    POST   /missions/{id}/schedules                  create (operator)
    GET    /missions/{id}/schedules                  list (access)
    GET    /missions/{id}/schedules/{sid}            get, with next fire times (access)
    PATCH  /missions/{id}/schedules/{sid}            update (operator)
    POST   /missions/{id}/schedules/{sid}/pause      pause (operator)
    POST   /missions/{id}/schedules/{sid}/resume     resume (operator)
    DELETE /missions/{id}/schedules/{sid}            archive (operator)

Every handler checks access first, then calls MissionScheduleService only.
A create whose Temporal sync failed still returns 201 with
temporal_sync_state="failed": the row exists and the reconciler retries.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    get_event_bus,
    require_existing_mission_access,
    require_mission_operator,
)
from modules.backend.events.bus import SessionEventBus
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission_schedule import (
    MissionScheduleCreate,
    MissionScheduleResponse,
    MissionScheduleUpdate,
)
from modules.backend.services.mission_schedule import MissionScheduleService
from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway

EventBus = Annotated[SessionEventBus, Depends(get_event_bus)]

# GET of a single schedule shows this many upcoming fire times (contract 3.5.3).
_NEXT_FIRE_TIMES = 5

router = APIRouter()


async def _service(db: DbSession, event_bus: SessionEventBus) -> MissionScheduleService:
    """Built after the access check, so an unauthorised caller never reaches Temporal."""
    return MissionScheduleService(db, await TemporalScheduleGateway.create(), event_bus)


def _render(schedule, next_fire_times: list | None = None) -> dict:
    response = MissionScheduleResponse.model_validate(schedule)
    response.next_fire_times = next_fire_times or []
    return response.model_dump(mode="json")


@router.post(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    status_code=201,
    summary="Create a mission schedule",
)
async def create_schedule(
    mission_id: str,
    data: MissionScheduleCreate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_mission_operator(db, mission_id, current_user)
    svc = await _service(db, event_bus)
    schedule = await svc.create_schedule(mission_id, data, current_user.id)
    return ApiResponse(success=True, data=_render(schedule), metadata={"request_id": request_id})


@router.get(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    summary="List mission schedules",
)
async def list_schedules(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
    include_archived: bool = Query(False),
) -> ApiResponse:
    await require_existing_mission_access(db, mission_id, current_user)
    svc = await _service(db, event_bus)
    schedules = await svc.list_schedules(mission_id, include_archived=include_archived)
    return ApiResponse(
        success=True,
        data={"schedules": [_render(s) for s in schedules]},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Get a mission schedule with its next fire times",
)
async def get_schedule(
    mission_id: str,
    schedule_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_existing_mission_access(db, mission_id, current_user)
    svc = await _service(db, event_bus)
    schedule = await svc.get_schedule(mission_id, schedule_id)
    next_fire_times = await svc.next_fire_times(schedule, _NEXT_FIRE_TIMES)
    return ApiResponse(
        success=True,
        data=_render(schedule, next_fire_times),
        metadata={"request_id": request_id},
    )


@router.patch(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Update a mission schedule",
)
async def update_schedule(
    mission_id: str,
    schedule_id: str,
    data: MissionScheduleUpdate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_mission_operator(db, mission_id, current_user)
    svc = await _service(db, event_bus)
    schedule = await svc.update_schedule(mission_id, schedule_id, data, current_user.id)
    return ApiResponse(success=True, data=_render(schedule), metadata={"request_id": request_id})


@router.post(
    "/{mission_id}/schedules/{schedule_id}/pause",
    response_model=ApiResponse,
    summary="Pause a mission schedule",
)
async def pause_schedule(
    mission_id: str,
    schedule_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_mission_operator(db, mission_id, current_user)
    svc = await _service(db, event_bus)
    schedule = await svc.pause_schedule(mission_id, schedule_id, current_user.id)
    return ApiResponse(success=True, data=_render(schedule), metadata={"request_id": request_id})


@router.post(
    "/{mission_id}/schedules/{schedule_id}/resume",
    response_model=ApiResponse,
    summary="Resume a mission schedule",
)
async def resume_schedule(
    mission_id: str,
    schedule_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_mission_operator(db, mission_id, current_user)
    svc = await _service(db, event_bus)
    schedule = await svc.resume_schedule(mission_id, schedule_id, current_user.id)
    return ApiResponse(success=True, data=_render(schedule), metadata={"request_id": request_id})


@router.delete(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Archive a mission schedule",
)
async def archive_schedule(
    mission_id: str,
    schedule_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_mission_operator(db, mission_id, current_user)
    svc = await _service(db, event_bus)
    schedule = await svc.archive_schedule(mission_id, schedule_id, current_user.id)
    return ApiResponse(success=True, data=_render(schedule), metadata={"request_id": request_id})
