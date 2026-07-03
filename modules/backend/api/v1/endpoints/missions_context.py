"""
Mission context and console history API endpoints.

MCD (Mission Context Document) CRUD and unified console timeline.
Split from missions.py for file size compliance.
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    require_mission_access,
)
from modules.backend.schemas.base import ApiResponse

router = APIRouter()


# ---- Mission Context (MCD) ----


@router.get(
    "/{mission_id}/context",
    response_model=ApiResponse,
    summary="Get Mission Context Document",
)
async def get_mission_context(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get the full MCD content with version and size metrics."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.mission_context import MissionContextManager

    manager = MissionContextManager(db)
    context_data = await manager.get_context(mission_id)
    size = await manager.get_context_size(mission_id)
    return ApiResponse(
        success=True,
        data={
            "mission_id": mission_id,
            "context_data": context_data,
            **size,
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/context/history",
    response_model=ApiResponse,
    summary="Get MCD change history",
)
async def get_context_history(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    limit: int = Query(30, ge=1, le=100),
) -> ApiResponse:
    """Get recent changes to the Mission Context Document."""
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.schemas.mission_context import ContextChangeResponse
    from modules.backend.services.mission_context import MissionContextManager

    manager = MissionContextManager(db)
    changes = await manager.get_history(mission_id, limit=limit)
    items = [ContextChangeResponse.model_validate(c).model_dump() for c in changes]
    return ApiResponse(
        success=True,
        data={"changes": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


# ---- Mission Console History ----


@router.get(
    "/{mission_id}/console/history",
    response_model=ApiResponse,
    summary="Get mission console history",
)
async def get_console_history(
    mission_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    limit: int = Query(200, ge=1, le=1000),
) -> ApiResponse:
    """Get a unified timeline of recent session messages and execution events.

    Queries all sessions belonging to this mission, collects their messages
    and execution records, and returns them as a single timeline sorted by
    timestamp descending.

    Each item has: event_id, event_type, category, timestamp, source, data.
    """
    await require_mission_access(db, mission_id, current_user)
    from modules.backend.services.console import get_console_history

    timeline = await get_console_history(db, mission_id, limit=limit)

    return ApiResponse(
        success=True,
        data={
            "events": timeline,
            "total": len(timeline),
            "mission_id": mission_id,
        },
        metadata={"request_id": request_id},
    )
