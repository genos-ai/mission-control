"""
Mission run API endpoints (Plan 88 step 88.1.12, contract 3.5.3).

    POST /missions/{id}/runs                       start a run for an objective (operator)
    GET  /missions/{id}/runs                       list, newest sequence first (access)
    GET  /missions/{id}/runs/{run_id_or_seq}       run, digest and tasks (access)
    POST /missions/{id}/runs/{run_id}/cancel       cancel (operator)

Every lookup is scoped by mission (contract 3.0.2): another mission's run is 404.
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
from modules.backend.schemas.mission_run import (
    MissionRunCreate,
    MissionRunListResponse,
    MissionRunResponse,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.services.mission_run import DEFAULT_RUN_LIST_LIMIT, MissionRunService

EventBus = Annotated[SessionEventBus, Depends(get_event_bus)]

router = APIRouter()


@router.post(
    "/{mission_id}/runs",
    response_model=ApiResponse,
    summary="Start a mission run for an objective",
)
async def start_run(
    mission_id: str,
    data: MissionRunCreate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Start a PENDING run; 409 when another run of the mission is active."""
    await require_mission_operator(db, mission_id, current_user)
    run = await MissionRunService(db, event_bus).start_run(
        mission_id,
        trigger=MissionRunTrigger.MANUAL,
        objective=data.objective,
        user_id=current_user.id,
        session_id=None,
    )
    return ApiResponse(
        success=True,
        data=MissionRunResponse.model_validate(run).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/runs",
    response_model=ApiResponse,
    summary="List mission runs",
)
async def list_runs(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
    status: list[MissionRunStatus] | None = Query(None),
    limit: int | None = Query(None, ge=1, le=200),
    before_sequence: int | None = Query(None),
) -> ApiResponse:
    """Newest sequence first; next_before_sequence is set when the page is full."""
    await require_existing_mission_access(db, mission_id, current_user)
    page_size = limit if limit is not None else DEFAULT_RUN_LIST_LIMIT
    runs = await MissionRunService(db, event_bus).list_runs(
        mission_id, statuses=status, limit=page_size, before_sequence=before_sequence
    )
    body = MissionRunListResponse(
        runs=[MissionRunResponse.model_validate(r) for r in runs],
        next_before_sequence=runs[-1].sequence if len(runs) == page_size else None,
    )
    return ApiResponse(
        success=True, data=body.model_dump(mode="json"), metadata={"request_id": request_id}
    )


@router.get(
    "/{mission_id}/runs/{run_id_or_seq}",
    response_model=ApiResponse,
    summary="Get a mission run by id or sequence",
)
async def get_run(
    mission_id: str,
    run_id_or_seq: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_existing_mission_access(db, mission_id, current_user)
    detail = await MissionRunService(db, event_bus).get_run_detail(mission_id, run_id_or_seq)
    return ApiResponse(
        success=True, data=detail.model_dump(mode="json"), metadata={"request_id": request_id}
    )


@router.post(
    "/{mission_id}/runs/{run_id}/cancel",
    response_model=ApiResponse,
    summary="Cancel a mission run",
)
async def cancel_run(
    mission_id: str,
    run_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    await require_mission_operator(db, mission_id, current_user)
    run = await MissionRunService(db, event_bus).cancel_run(
        mission_id,
        run_id,
        current_user.id,
        reason=MissionRunStatusReason.CANCELLED_BY_USER,
    )
    return ApiResponse(
        success=True,
        data=MissionRunResponse.model_validate(run).model_dump(mode="json"),
        metadata={"request_id": request_id},
    )
