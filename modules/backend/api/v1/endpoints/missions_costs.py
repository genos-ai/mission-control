"""
Mission cost API endpoints (Plan 60).

Per-mission token economics — reuses TokenEconomicsService with mission_id scope.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    require_mission_access,
)
from modules.backend.schemas.base import ApiResponse
from modules.backend.services.mission import MissionService

router = APIRouter()


@router.get(
    "/{mission_id}/costs",
    response_model=ApiResponse,
    summary="Mission cost breakdown",
)
async def mission_costs(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    timeframe: str | None = None,
) -> ApiResponse:
    """Token economics scoped to a single mission.

    Optional timeframe filter: 24h, 7d, 30d. Omit for all-time.
    """
    # An unknown mission is a 404 for everyone: the shared check lets an admin through without
    # looking, and they would be shown an all-zero breakdown for a mission that does not exist.
    await MissionService(db).get_mission(mission_id)
    await require_mission_access(db, mission_id, current_user)

    from modules.backend.services.token_economics import TokenEconomicsService

    service = TokenEconomicsService(db)
    kw = {"mission_id": mission_id, "timeframe": timeframe}
    summary = await service.get_summary(**kw)
    by_agent = await service.get_token_breakdown(**kw)
    cache = await service.get_cache_performance(**kw)
    efficiency = await service.get_output_efficiency(**kw)
    calls = await service.get_expensive_calls(limit=10, **kw)

    return ApiResponse(
        success=True,
        data={
            "mission_id": mission_id,
            "summary": summary,
            "by_agent": by_agent,
            "cache_performance": cache,
            "output_efficiency": efficiency,
            "expensive_calls": calls,
        },
        metadata={"request_id": request_id},
    )
