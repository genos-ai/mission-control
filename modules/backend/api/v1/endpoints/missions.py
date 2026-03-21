"""
Mission management API endpoints.

CRUD for missions, team management, and mission-scoped workflow listing.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission import MissionCreate, MissionResponse, MissionUpdate
from modules.backend.schemas.mission_team import (
    MissionTeamAddRequest,
    MissionTeamMemberResponse,
    UserPromptUpdateRequest,
)
from modules.backend.schemas.workflow_schedule import (
    WorkflowScheduleCreateRequest,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdateRequest,
)
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_team import MissionTeamService

router = APIRouter()


# ---- Mission CRUD ----


@router.post("", response_model=ApiResponse, summary="Create mission")
async def create_mission(
    data: MissionCreate,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create a new mission."""
    service = MissionService(db)
    mission = await service.create_mission(
        name=data.name,
        description=data.description,
        brief=data.brief,
        owner_id=data.owner_id,
        team_id=data.team_id,
        default_roster=data.default_roster,
        budget_ceiling_usd=data.budget_ceiling_usd,
        repo_url=data.repo_url,
        repo_root=data.repo_root,
    )
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.get("", response_model=ApiResponse, summary="List missions")
async def list_missions(
    db: DbSession,
    request_id: RequestId,
    owner_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> ApiResponse:
    """List missions with optional filters."""
    service = MissionService(db)
    missions = await service.list_missions(
        owner_id=owner_id, status=status, limit=limit,
    )
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
) -> ApiResponse:
    """Get mission detail by ID."""
    service = MissionService(db)
    mission = await service.get_mission(mission_id)
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.patch("/{mission_id}", response_model=ApiResponse, summary="Update mission")
async def update_mission(
    mission_id: str,
    data: MissionUpdate,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update mission fields."""
    service = MissionService(db)
    updates = data.model_dump(exclude_none=True)
    mission = await service.update_mission(mission_id, **updates)
    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ---- Team management ----


@router.get(
    "/{mission_id}/team",
    response_model=ApiResponse,
    summary="List mission team",
)
async def list_mission_team(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List agents on a mission's team."""
    service = MissionTeamService(db)
    members = await service.list_team(mission_id, enabled_only=enabled_only)
    items = [
        MissionTeamMemberResponse.model_validate(m).model_dump()
        for m in members
    ]
    return ApiResponse(
        success=True,
        data={"team_members": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/team",
    response_model=ApiResponse,
    summary="Add agent to team",
)
async def add_agent_to_team(
    mission_id: str,
    data: MissionTeamAddRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Add an agent from the catalog to a mission's team."""
    service = MissionTeamService(db)
    member = await service.add_agent(
        mission_id=mission_id,
        agent_catalog_id=data.agent_catalog_id,
        user_prompt=data.user_prompt,
        display_order=data.display_order,
        custom_constraints=data.custom_constraints,
    )
    response = MissionTeamMemberResponse.model_validate(member)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/team/{member_id}",
    response_model=ApiResponse,
    summary="Remove agent from team",
)
async def remove_agent_from_team(
    mission_id: str,
    member_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Remove an agent from a mission's team."""
    service = MissionTeamService(db)
    await service.remove_agent(member_id)
    return ApiResponse(
        success=True,
        data={"removed": member_id},
        metadata={"request_id": request_id},
    )


@router.put(
    "/{mission_id}/team/{member_id}/prompt",
    response_model=ApiResponse,
    summary="Update user prompt",
)
async def update_team_member_prompt(
    mission_id: str,
    member_id: str,
    data: UserPromptUpdateRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update a team member's user prompt with version tracking."""
    service = MissionTeamService(db)
    member = await service.update_user_prompt(
        member_id=member_id,
        content=data.content,
        changed_by=data.changed_by,
        change_reason=data.change_reason,
    )
    response = MissionTeamMemberResponse.model_validate(member)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ---- Mission-scoped workflows ----


@router.get(
    "/{mission_id}/workflows",
    response_model=ApiResponse,
    summary="List mission workflows",
)
async def list_mission_workflows(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List DB-stored workflow definitions for a mission."""
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflows = await service.list_workflows(mission_id, enabled_only=enabled_only)
    items = [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "version": w.version,
            "enabled": w.enabled,
            "trigger_type": (w.trigger_config or {}).get("type", "on_demand"),
            "step_count": len(w.steps or []),
            "designed_by": w.designed_by,
            "locked_at": w.locked_at,
        }
        for w in workflows
    ]
    return ApiResponse(
        success=True,
        data={"workflows": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/workflows/import",
    response_model=ApiResponse,
    summary="Import workflow from template",
)
async def import_workflow_template(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    template_name: str = "",
    name_override: str | None = None,
) -> ApiResponse:
    """Import a YAML workflow template as a DB-stored workflow for a mission."""
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflow = await service.import_from_template(
        mission_id=mission_id,
        template_name=template_name,
        name_override=name_override,
    )
    return ApiResponse(
        success=True,
        data={
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "mission_id": workflow.mission_id,
        },
        metadata={"request_id": request_id},
    )


# ---- Workflow schedules ----


@router.get(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    summary="List mission schedules",
)
async def list_mission_schedules(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List workflow schedules for a mission."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    schedules = await service.list_by_mission(mission_id, enabled_only=enabled_only)
    items = [
        WorkflowScheduleResponse.model_validate(s).model_dump()
        for s in schedules
    ]
    return ApiResponse(
        success=True,
        data={"schedules": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    summary="Create workflow schedule",
)
async def create_mission_schedule(
    mission_id: str,
    data: WorkflowScheduleCreateRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create a cron-based schedule for a workflow."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    schedule = await service.create_schedule(
        workflow_definition_id=data.workflow_definition_id,
        mission_id=mission_id,
        cron_expression=data.cron_expression,
        timezone=data.timezone,
        description=data.description,
        budget_per_run_usd=data.budget_per_run_usd,
        max_iterations=data.max_iterations,
        cooldown_seconds=data.cooldown_seconds,
        created_by="user:api",
    )
    response = WorkflowScheduleResponse.model_validate(schedule)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.patch(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Update workflow schedule",
)
async def update_mission_schedule(
    mission_id: str,
    schedule_id: str,
    data: WorkflowScheduleUpdateRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update a workflow schedule's configuration."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    updates = data.model_dump(exclude_none=True)
    schedule = await service.update_schedule(schedule_id, **updates)
    response = WorkflowScheduleResponse.model_validate(schedule)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Delete workflow schedule",
)
async def delete_mission_schedule(
    mission_id: str,
    schedule_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Delete a workflow schedule."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    await service.delete_schedule(schedule_id)
    return ApiResponse(
        success=True,
        data={"deleted": schedule_id},
        metadata={"request_id": request_id},
    )
