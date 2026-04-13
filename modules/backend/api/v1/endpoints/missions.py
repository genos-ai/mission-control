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
from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
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
    limit: int = 100,
) -> ApiResponse:
    """Reconstruct narrative events from persisted data.

    Combines execution records, plan task states, and artifacts into
    a timeline the Narrative tab can render on mount — before any
    live SSE events arrive. Returns the same event shapes the
    Narrative tab already handles.
    """
    from sqlalchemy import select

    from modules.backend.models.execution_record import ExecutionRecord
    from modules.backend.models.mission_artifact import MissionArtifact
    from modules.backend.models.mission_plan import (
        MissionPlan,
        PlanTaskState,
    )

    events: list[dict] = []

    # 1. Execution runs → system.execution.created / completed
    exec_rows = await db.execute(
        select(ExecutionRecord)
        .where(ExecutionRecord.mission_id == mission_id)
        .order_by(ExecutionRecord.created_at.desc())
        .limit(limit)
    )
    for rec in exec_rows.scalars().all():
        events.append({
            "event_id": str(rec.id) + "-created",
            "event_type": "system.execution.created",
            "category": "execution",
            "timestamp": str(rec.started_at or rec.created_at),
            "source": rec.roster_name or "dispatch",
            "data": {
                "objective": rec.objective_statement,
                "roster_name": rec.roster_name,
            },
        })
        if rec.completed_at:
            events.append({
                "event_id": str(rec.id) + "-completed",
                "event_type": "system.execution.completed",
                "category": "execution",
                "timestamp": str(rec.completed_at),
                "source": rec.roster_name or "dispatch",
                "data": {
                    "status": rec.status,
                    "total_cost_usd": rec.total_cost_usd,
                    "duration_seconds": (
                        (rec.completed_at - rec.started_at).total_seconds()
                        if rec.started_at and rec.completed_at else None
                    ),
                },
            })

    # 2. Plan task states → plan.step.completed
    plan_rows = await db.execute(
        select(MissionPlan).where(MissionPlan.mission_id == mission_id)
    )
    for plan in plan_rows.scalars().all():
        task_rows = await db.execute(
            select(PlanTaskState)
            .where(PlanTaskState.mission_plan_id == plan.id)
            .order_by(PlanTaskState.updated_at)
        )
        for ts in task_rows.scalars().all():
            if ts.status in ("completed", "failed", "skipped", "cancelled"):
                events.append({
                    "event_id": str(ts.id),
                    "event_type": "plan.step.completed",
                    "category": "execution",
                    "timestamp": str(ts.updated_at),
                    "source": f"dispatch:{mission_id}",
                    "data": {
                        "step_id": ts.task_id,
                        "status": "success" if ts.status == "completed" else ts.status,
                        "result_summary": ts.result_summary,
                        "cost_usd": ts.cost_usd,
                        "duration_seconds": ts.duration_seconds,
                    },
                })

    # 3. Artifacts → mission.artifact.found
    artifact_rows = await db.execute(
        select(MissionArtifact)
        .where(MissionArtifact.mission_id == mission_id)
        .order_by(MissionArtifact.created_at)
        .limit(limit)
    )
    for art in artifact_rows.scalars().all():
        events.append({
            "event_id": str(art.id),
            "event_type": "mission.artifact.found",
            "category": "execution",
            "timestamp": str(art.created_at),
            "source": art.agent_id or "agent",
            "data": {
                "title": art.title,
                "artifact_type": art.artifact_type,
                "content": art.content[:500] if art.content else "",
            },
        })

    # Sort by timestamp ascending
    events.sort(key=lambda e: e["timestamp"])
    events = events[-limit:]

    return ApiResponse(
        success=True,
        data={"events": events, "count": len(events)},
        metadata={"request_id": request_id},
    )
