"""
Mission management API endpoints.

Core mission CRUD and environment status. Team, workflow, schedule,
context, and console endpoints live in sub-modules and are included
as nested routers to keep each file under the 500-line target.
"""

from fastapi import APIRouter

from modules.backend.api.v1.endpoints import (
    missions_artifacts,
    missions_context,
    missions_plan,
    missions_team,
    missions_workflows,
)
from modules.backend.core.dependencies import CurrentUser, DbSession, Idempotency, RequestId
from modules.backend.core.exceptions import AuthorizationError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission import (
    MissionCreate,
    MissionResponse,
    MissionUpdate,
)
from modules.backend.services.mission import MissionService

router = APIRouter()

# Include sub-routers (preserves existing URL structure)
router.include_router(missions_team.router)
router.include_router(missions_workflows.router)
router.include_router(missions_context.router)
router.include_router(missions_plan.router)
router.include_router(missions_artifacts.router)


# ---- Mission CRUD ----


@router.post("", response_model=ApiResponse, summary="Create mission")
async def create_mission(
    data: MissionCreate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    idempotency: Idempotency,
) -> ApiResponse:
    """Create a new mission.

    Platform missions (tier='platform') require admin role.
    The owner_id is set to the authenticated user.

    Supports Idempotency-Key header — safe to retry on network timeout.
    """
    if idempotency:
        cached = await idempotency.get_cached_response()
        if cached:
            return ApiResponse(**cached)

    if data.tier == "platform" and not current_user.has_role("admin"):
        raise AuthorizationError("Platform missions require admin role")

    service = MissionService(db)
    mission = await service.create_mission(
        name=data.name,
        description=data.description,
        brief=data.brief,
        owner_id=current_user.id,
        team_id=data.team_id,
        default_roster=data.default_roster,
        budget_ceiling_usd=data.budget_ceiling_usd,
        repo_url=data.repo_url,
        repo_root=data.repo_root,
        tier=data.tier,
    )
    response = MissionResponse.model_validate(mission)
    result = ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )
    if idempotency:
        await idempotency.cache_response(result.model_dump())
    return result


@router.get("", response_model=ApiResponse, summary="List missions")
async def list_missions(
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    status: str | None = None,
    limit: int = 50,
) -> ApiResponse:
    """List missions visible to the current user.

    Admins see all missions. Users see missions they own or are members of.
    Platform missions are only visible to admins.
    """
    service = MissionService(db)
    if current_user.has_role("admin"):
        missions = await service.list_missions(status=status, limit=limit)
    else:
        missions = await service.list_missions(
            owner_id=current_user.id, status=status, limit=limit,
        )
        # Filter out platform missions for non-admin users
        missions = [m for m in missions if getattr(m, 'tier', 'user') != 'platform']
    items = [MissionResponse.model_validate(m).model_dump() for m in missions]
    return ApiResponse(
        success=True,
        data={"missions": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.get("/{mission_id}", response_model=ApiResponse, summary="Get mission detail")
async def get_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Get mission detail by ID. Owner, member, or admin only."""
    service = MissionService(db)
    mission = await service.get_mission(mission_id)
    # Admin sees everything; users must own or be a member
    if not current_user.has_role("admin") and mission.owner_id != current_user.id:
        # Check membership
        is_member = any(m.user_id == current_user.id for m in mission.members)
        if not is_member:
            raise AuthorizationError("You don't have access to this mission")
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/environment",
    response_model=ApiResponse,
    summary="Get execution environment status",
)
async def get_mission_environment(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get the execution environment (container/worktree) status for a mission."""
    from modules.backend.services.execution_environment import ExecutionEnvironmentService

    service = ExecutionEnvironmentService(db_session=db)
    data = await service.list_environments_for_mission(mission_id)

    return ApiResponse(
        success=True,
        data=data,
        metadata={"request_id": request_id},
    )


@router.delete("/{mission_id}", response_model=ApiResponse, summary="Delete mission")
async def delete_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Permanently delete a mission and all related data.

    Cascades through executions, records, team, workflows, and containers.
    Admin can delete any mission. Users can only delete their own missions.
    """
    service = MissionService(db)
    mission = await service.get_mission(mission_id)
    if not current_user.has_role("admin") and mission.owner_id != current_user.id:
        raise AuthorizationError("Cannot delete missions you don't own")
    name = await service.delete_mission(mission_id)
    return ApiResponse(
        success=True,
        data={"id": mission_id, "name": name, "deleted": True},
        metadata={"request_id": request_id},
    )


@router.patch("/{mission_id}", response_model=ApiResponse, summary="Update mission")
async def update_mission(
    mission_id: str,
    data: MissionUpdate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Update mission fields. Owner or admin only."""
    service = MissionService(db)
    existing = await service.get_mission(mission_id)
    if not current_user.has_role("admin") and existing.owner_id != current_user.id:
        raise AuthorizationError("Cannot update missions you don't own")
    updates = data.model_dump(exclude_none=True)
    mission = await service.update_mission(mission_id, **updates)
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ---- Narrative timeline ----


@router.get(
    "/{mission_id}/narrative",
    response_model=ApiResponse,
    summary="Get narrative timeline from DB",
)
async def get_narrative(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    limit: int = 200,
) -> ApiResponse:
    """Return persisted narrative events from the mission_events table.

    Events are written by SessionEventBus.publish() for event types
    listed in events.yaml persist_event_types. This replaces the old
    multi-table reconstruction approach.
    """
    svc = MissionService(db)
    events = await svc.get_narrative_events(mission_id, limit=limit)

    return ApiResponse(
        success=True,
        data={"events": events, "count": len(events)},
        metadata={"request_id": request_id},
    )
