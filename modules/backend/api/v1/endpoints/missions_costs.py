"""
Mission cost API endpoints (Plan 60).

Per-mission token economics — reuses TokenEconomicsService with mission_id scope.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
from modules.backend.core.exceptions import AuthorizationError
from modules.backend.schemas.base import ApiResponse
from modules.backend.services.mission import MissionService

router = APIRouter()


async def _require_mission_access(db, mission_id: str, current_user) -> None:
    """Admin, mission owner, or member can read costs.

    NOTE: This access check is duplicated across mission sub-routers
    (artifacts, plan, costs, streams). A shared utility would be better
    but is outside the scope of Plan 60.
    """
    mission = await MissionService(db).get_mission(mission_id)
    if current_user.has_role("admin"):
        return
    if mission.owner_id == current_user.id:
        return
    if any(m.user_id == current_user.id for m in mission.members):
        return
    raise AuthorizationError("You don't have access to this mission")


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
    await _require_mission_access(db, mission_id, current_user)

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
